# First Slice E: Roles, Grants, RLS, Definer Functions and the Hardened Destination (T09, T10) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every runtime process connects as its own PostgreSQL role holding exactly its AM-20.2 grants; every run transition, decision, grant, attempt step and event goes through a `SECURITY DEFINER` function owned by `app_definer`; every tenant table is under forced row-level security with the AM-20.5 policy; the test clock exists only where the `testclock` Alembic branch is applied; and incident-sim's key table is atomic, permanent and executor-only, with abort, permanent rejection, a test-only fault factory and a detective check (T09, T10; R006–R009, R084, R106, R124, R126, R128, R010, R047, R096, R098).

**Architecture:** Three Alembic revisions on the `app` main line (now labelled `app`) and one on the `testclock` branch. Revision `0002_roles_grants_rls` adds the columns, tables and composite foreign keys AM-20 needs, transfers ownership to `migrator`, applies the grant matrix from `ops_core.privileges` (one source of truth for the migration and the R124 test), enables and forces RLS with the NULLIF policy, and creates `app.current_time()`. Revisions `0003_run_path_functions` and `0004_write_path_functions` create the fourteen definer functions the running services call today plus the internal helpers, each passed to `op.execute` as one string, each with `REVOKE … FROM PUBLIC` and `GRANT EXECUTE` to its named callers in the same transaction. `tc_0001_test_clock` (branch `testclock`, `depends_on` 0002) adds `app.test_clock` and the `test_harness` grants. Role creation and passwords are a bootstrap concern: `scripts/skeleton.py migrate` creates or re-keys the login roles from per-role secret files, creates the `NOLOGIN` owner roles, and fixes database `CONNECT` before running Alembic. `ops_core.persistence` becomes a thin layer of one Python wrapper per definer function with SQLSTATE-class `OC` errors mapped to typed exceptions, and `Session.unit(tenant_id)` sets the transaction-local tenant before any tenant table is touched. The services switch to their roles (api, worker, mcp_read, mcp_exec). incident-sim keeps role `incident` but loses ownership (a `NOLOGIN` `incident_owner` owns the schema; `incident` holds INSERT and SELECT only), gains `POST /internal/actions/{id}/abort`, permanent `REJECTED` keys, a 403 for authenticated-but-wrong-audience tokens, and a fault factory that exists only under `PROFILE=test`. Live tests run against per-session databases (`ops_test`, `incident_test`) created by the e2e fixture, migrated to `heads` so the test clock exists there and never in the dev database.

**Tech Stack:** unchanged from Plan D (Python 3.13 uv workspace, psycopg 3.3.6 async, SQLAlchemy 2.1.4 + Alembic 1.20.0 for migrations only, FastAPI 0.143.0, `mcp==2.3.0`, PyJWT 2.15.1, httpx2 2.13.1, pytest 9.1.1 + pytest-asyncio 1.4.0, ruff 0.16.10, mypy strict), PostgreSQL 17.11 (pgvector image) and Keycloak 26.8.0 from the Plan B dev stack. No new dependency.

**Spec:** `SPEC_AMENDMENTS.md` (OPS-BUILD-1.3.6) over `BUILD_SPEC.md`. The fact sheet `docs/superpowers/research/2026-10-08-plan-e-inputs.md` (T09/T10 verbatim, AM-20.1–20.7 row by row, the tree as it is, 16 open questions) and the measured spike `docs/superpowers/research/2026-10-08-plan-e-spike.md` (definer pattern, RLS, grants, Alembic branches, advisory locks and the clock, destination races) are committed with this plan; the rulings below answer the fact sheet's questions and cite the spike's measurements by section (`spike §n`). Earlier artefacts this plan builds on: revision 1 of both databases (`migrations/app`, `migrations/incident`), `ops_core.persistence`/`settings`/`tokens`/`states`/`jobs`/`outcomes` (Plans C and D), the five services, `scripts/skeleton.py`, `tests/e2e/`.

## Global Constraints

- **Debt before code (SA:698).** The Plan E debt list (below) is committed in Task 1 before any migration or service code changes. Nothing not on the list may be shortcut; every line names its owning task.
- **Authority boundaries stay where the spec puts them.** Runtime roles never UPDATE `runs.state`, never INSERT into `events`, `decisions`, `proposals`, `execution_grant` or `action_attempt_state` (SA:387); `mcp_read`, `mcp_exec` and `operator` hold no table grant (SA:437); functions decide by `session_user` (SA:389); `app_definer` owns no table (SA:396); `migrator` is never a runtime role (SA:521); only `migrator` data migrations write seed rows (SA:440).
- **Every definer function**: `SECURITY DEFINER`, owner `app_definer`, `SET search_path = app, pg_temp`, `SET app.tenant_id = ''` as a function attribute, `REVOKE ALL … FROM PUBLIC` then `GRANT EXECUTE … TO <named callers>` in the creating migration's transaction, resolves the tenant through `run_directory` (or the handle, or the tenant argument) and sets it with `set_config(name, value, true)` before touching tenant rows, reads the setting as `NULLIF(current_setting('app.tenant_id', true), '')::uuid`, and names its allowed callers in `_authority`, which raises `authority_violation` (SQLSTATE `OC001`); the EXECUTE ACL (revoked from PUBLIC, granted to the callers) refuses every other login role first with 42501, so `_authority` is defence in depth for a session that holds EXECUTE through role membership or superuser status (measured in round 1). Internal helpers (`_` prefix) are plain PL/pgSQL owned by `app_definer`, revoked from PUBLIC, granted to nobody, and carry **no** `SET app.tenant_id` attribute (it would blank the tenant the outer function set; spike §1 D).
- **One string per function.** Each `CREATE FUNCTION … $fn$ … $fn$; ALTER FUNCTION … OWNER TO …; REVOKE …; GRANT …;` block is one `op.execute` string (spike §4: revision 1's `split(";\n")` cuts dollar-quoted bodies; a colon followed by a word is a SQLAlchemy bind unless the colon follows a word character or another colon, so `':1'` and `':timeout'` are binds too — fact sheet §4.3, round-1 finding B2; Task 3's unit test loads every revision and asserts no `op.execute` string carries a bind). Never `current_time` unqualified: it is the SQL keyword; always `app.current_time()` (spike §5).
- **Clock.** Every lease, expiry, freshness and deadline comparison and every row the functions stamp (`at`, `occurred_at`, `revoked_at`, `granted_at`, `frozen_at`, `decided_at`) uses `app.current_time()`; column defaults for `created_at`/`updated_at` stay `now()` (SA:157, SA:528). `app.current_time()` never reads a GUC (R126).
- **Hashed bytes.** Nothing re-serialises a proposal: `freeze_proposal` hashes the canonical bytes it stores and compares them with the draft's hash; the destination recomputes over the bytes it receives (SA:268).
- **Secrets** live only as files under `OPS_SECRETS_DIR`; one file per login role (`postgres_<role>_password`), generated by `scripts/bootstrap_dev.py secrets`, declared in `SECRET_NAMES` and in compose's top-level `secrets:` (Plan B's tests enforce both). No secret in an environment variable, URL, log line, exception message, assertion message, evidence file, migration string or review report. Passwords reach `CREATE ROLE` through `set_config` + `format(%L)` server-side, never through a Python-built SQL string (`scripts/skeleton.py` already does this for `incident`).
- **Loopback only, async only, autocommit connections with explicit units** (Plan D rulings 15, 23, 24): unchanged. A unit that touches a tenant table is `Session.unit(tenant_id)`; a unit without a tenant may touch only non-RLS tables and definer functions.
- **Live tests never touch the dev databases.** The e2e fixture creates `ops_test` and `incident_test` (dropped and recreated per session), migrates them (`heads` for app, so `app.test_clock` exists there), and every live test and skeleton process runs against them with `PROFILE=test`. The dev `ops` database never carries `app.test_clock`; `skeleton.py up` refuses to start when it does.
- **Tests:** unit tests in `tests/plan_e/` (DB-free), live tests in `tests/e2e/` gated by `OPS_LIVE=1` (Plan D ruling 26); existing `tests/plan_d/` tests are updated where an interface they fake changes, never deleted. Acceptance rows name the live test that evidences them. No xfail or skip except the live gate (BS:597).
- **Comments** per `docs/CODE_COMMENTS.md` (why, not what; one-line PEP 257 docstring on every public def; shortcuts carry `TODO(Txx)`; SQL bodies get `--` comments for the non-obvious lock or guard, not for every statement). ≤120 columns, no `type: ignore`, ruff + mypy strict clean, UTF-8 without BOM, LF.
- **Gates:** `uv run ruff format <every file the task created or modified> && uv run ruff check --fix <same>` (ruff's ISC004 flags an unparenthesised multi-line string element inside a tuple or list and `--fix` does not repair it: write each such element inside its own parentheses), then `PYTHONUTF8=1 uv run python scripts/check.py` GREEN after every task; `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts` exit 0; the live suite `OPS_LIVE=1 PYTHONUTF8=1 uv run python -m pytest tests/e2e tests/plan_b/live -q` against the running dev stack after every task that changes a migration, `persistence`, a service or a live test. mypy's incremental cache can report spurious `Module "ops_core" has no attribute …` after many edits; rerun with `--no-incremental` before treating it as real.
- **Interim red (declared).** Revision 0002 (Task 2) changes the schema under Plan D's persistence code, which is rewritten only in Task 5, and the services follow in Tasks 6–7. From Task 2 to Task 7 the following stay red and are not a gate failure: `tests/e2e/test_worker_live.py`, `test_mcp_read_live.py`, `test_mcp_write_live.py`, `test_r105_walking_skeleton.py`, and the Plan D tests inside `test_migrations_and_persistence.py` until Task 5 rewrites them; `check.py`'s mypy step may fail only in `api/`, `worker/`, `mcp-read/` and `mcp-write/` at call sites of `persistence` names Task 5 removed or re-signed (`transition`, `check_invocation`, `resolve_handle`, `Session.read`, `create_run`, `append_event`, `claim_job`). Each task's gate step lists exactly what may be red; anything else must be green. Task 7 restores every gate.
- **Commits:** one logical group per step; messages free of any attribution trailer; never push.
- **Bash tool (Git Bash)**; never PowerShell redirection; tests via `python -m pytest` from the repo root; never `docker compose down -v`; never change system settings; never drop a role or database other than `ops_test` / `incident_test`.

## Review Focus

1. **A definer function called with a preset `app.tenant_id` (session-level, by a compromised `mcp_exec`) must ignore it and must not leak its own tenant into the caller's session.** Spike §1 D measured that only "attribute + transaction-local `set_config`" does this. Pinned in Task 3 (`test_resolve_identity_ignores_a_preset_tenant_and_restores_it`, `test_every_run_path_function_leaves_the_callers_tenant_unchanged`), Task 4 (`test_resolve_invocation_binds_server_azp_expiry_and_revocation`, `test_write_path_grant_sent_outcome_once_and_only_once` and `test_mark_unknown_…`, each with a preset BETA and a restore assertion) and Task 3's catalog test of the attribute on every function in `pg_proc.proconfig`.
2. **A reused connection whose GUC is `''` must see zero rows, not raise.** Spike §2: the policy as written in SA:512 raises 22P02 on `''`. Pinned in Task 2's R008 test (two tenants on one connection, then a bare statement after the unit ends → zero rows, no error).
3. **`transition_run` called by `worker` with a post-grant target, or by any role but `worker`, must be refused and must leave `runs` untouched.** Pinned in Task 3 (R128: `api` calling it → 42501 from the EXECUTE ACL; the superuser, who bypasses the ACL, → `OC001` from `_authority`; `worker` asking for `EXECUTING` → `OC005 POST_GRANT_TARGET`; the row and its history unchanged).
4. **A second `create_incident` for the same run, or a concurrent one, must never produce a second grant, a second `action_id` or a second incident; and a POST or abort onto an `ABORTED` or `REJECTED` key must return that tombstone whatever hash it carries.** Pinned in Task 6's replay test (unchanged review focus from Plan D over the new functions) and Task 7's race tests (`asyncio.gather` create-vs-abort ×20, spike §6).
5. **`mcp_exec` must not be able to read any table, and `api` must not be able to write a decision or an event directly, even through `INSERT … ON CONFLICT` or `SELECT … FOR UPDATE` tricks.** Pinned in Task 2's R084/R124/R128 tests (every runtime role, every table, every privilege kind enumerated; `FOR UPDATE` by `mcp_exec` on `runs` → 42501).

## Rulings (decisions the spec leaves to this plan)

Each answers a fact-sheet §5 question (Qn), cites what the spike measured, and names the cost if wrong. Where a ruling reads the spec one of two ways it is proposed to the owner as an erratum in Task 9. Executors do not re-litigate them.

1. **Scope of definer functions (Q1): the functions that have callers today, plus the ones T09 names.** This plan creates `create_run`, `transition_run`, `append_event`, `freeze_proposal`, `record_decision`, `resolve_invocation`, `grant_execution`, `mark_sent`, `record_outcome`, `lookup_action`, `mark_unknown`, `revoke_handles`, the 24th function `resolve_identity` (ruling 4) and `app.current_time()`, with the internal helpers `_authority`, `_tenant_of_run`, `_tenant_of_action`, `_resolve_handle`, `_latest_attempt`, `_append_event`, `_transition`. `create_revision`, `create_manual_proposal`, `expire_proposal`, `request_cancel` (T21), `asset_scope`, `search_procedures_scoped` (T15–T17), `request_abort`, `escalate_run`, `resolve_escalation` (T22), `sync_memberships` (T11) and `reclaim_leases` (T13) arrive with their owning tasks, each in its own revision following the pattern set here; the grant matrix and RLS skeleton already cover their tables. Stub bodies that raise `not_implemented` were rejected: they would carry EXECUTE grants that mislead R124's enumeration and test nothing. Cost if wrong: later tasks write their functions against a pattern that is already measured; nothing here is thrown away.
2. **Tables and columns (Q2).** Revision 0002 adds `tenant_id` to `run_state_history`, `jobs` (nullable: sweeper jobs have no tenant, SA:504), `drafts`, `decisions`, `execution_grant`, `action_attempt`, `action_attempt_state` (backfilled through `runs`, `proposals`, `execution_grant`, `action_attempt`), composite tenant foreign keys everywhere a child references a parent (R009: `(tenant_id, run_id) → runs`, `(tenant_id, proposal_id) → proposals` from `decisions` and from `execution_grant`, `(tenant_id, draft_id) → drafts`, `(tenant_id, action_id) → execution_grant`, `(tenant_id, action_id, attempt_no) → action_attempt`, `(tenant_id, message_id) → messages`; `jobs` carries `CHECK ((run_id IS NULL) = (tenant_id IS NULL))` so a run-bound job cannot dodge the key with a NULL tenant), `runs.slot_held` (the partial unique index moves from `state IN (…)` to `WHERE slot_held`, SA:451), `runs.next_event_seq` (SA:439), `runs.cancel_requested_at`, `runs.checkpoint_id`, `runs.budget_used` (so the AM-20.2 column grants can be exact), `decisions.idempotency_key`, `jobs.run_id` nullable, `invocation_context.handle_sha256` replacing the raw `handle` (the table is truncated: handles live 60 s), `invocation_context.fence bigint`, and the tables T09 names: `run_directory`, `run_lease` (shape SA:173; lease semantics are T13's), `sessions` (shape BS:229; T11 may alter it). `outbox`, `feedback`, `idempotency_request`, `operator_resolutions`, `documents`/`chunks`/`embeddings`, `model_permit` and schema `checkpoints` are created by their owners (T14, T12, T22, T17, T13, T20), who add their rows to the grant matrix. **R122 is deferred to T20**: `langgraph-checkpoint-postgres` is not locked (fact sheet §2.3), so "migrator ran setup()" cannot be evidenced here; the matrix row stays `NOT_RUN` with that note. Cost if wrong: a later revision adds a column; the composite keys and RLS are the hard part and they are done once.
3. **Roles and passwords (Q3): every role now; bootstrap creates them; Alembic still runs as the Compose superuser.** `scripts/skeleton.py migrate` creates or re-keys the login roles `api`, `worker`, `sweeper`, `mcp_read`, `mcp_exec`, `operator`, `test_harness` (one secret file each, `postgres_<role>_password`) and `incident` (existing), and creates the `NOLOGIN` roles `migrator` (`BYPASSRLS`, granted by the superuser; owns schema `app` and its tables after revision 0002), `app_definer` (owns every definer function) and `incident_owner` (owns schema `incident`). `migrator` holds no login in this plan: Alembic keeps running as the Compose superuser `ops`, revision 0002 transfers ownership of everything in `app` to `migrator`, and later revisions create objects as `ops` and transfer them explicitly; a `migrator` login with its own secret is T30's (containerised migrations). All five processes switch to their roles in this plan (api → `api`, worker → `worker`, mcp-read → `mcp_read`, mcp-write → `mcp_exec`, incident-sim stays `incident`); `sweeper` and `operator` have no process until T13/T22 but exist so the per-role tests can connect as them. `CONNECT` is revoked from `PUBLIC` on both databases and granted to exactly the roles that use each (spike §3 measured the revoke on `incident`; `incident` can no longer connect to `ops`). `test_harness` is created only by a test-profile `migrate` (SA:403: test profile only) and receives its schema `USAGE`, its EXECUTE on `app.current_time()` and its table grants from the `testclock` branch, its `CONNECT` from the test-profile bootstrap; a dev or demo `migrate` neither creates it nor grants it anything (the role is cluster-wide, so a cluster that also runs the live suite holds it with no privilege in the dev database). Cost if wrong: a role is one `CREATE ROLE` and one secret file; the matrix test catches a wrong grant.
4. **Identity before tenant (Q4): a 24th definer function, `resolve_identity(issuer, subject)`, granted to `api` (T11's sweeper sync adds itself when it has a caller), iterating `tenants` the way SA:520 prescribes for the sweeper.** `memberships` is under `tenant_isolation` (SA:510) and SA:520 allows no further policy; `tenants` has no RLS (SA:523); so the function sets `app.tenant_id` per tenant and collects the active rows for `(issuer, subject)`. O(tenants) per request, tenants are few, and nothing new is granted. Proposed erratum (Task 9). Cost if wrong: T11's `sessions` stores the active tenant and the function becomes a one-tenant lookup.
5. **`persistence.py` becomes one thin wrapper per definer function with the spec's signature (Q5).** `transition()` is replaced by `transition_run()` (worker only); `create_run`, `append_event`, `freeze_proposal`, `record_decision`, `resolve_invocation`, `grant_execution`, `mark_sent`, `record_outcome`, `lookup_action`, `mark_unknown`, `revoke_handles`, `resolve_identity` are each `SELECT app.<fn>(…)` plus error translation. The events `run.accepted`, `run.failed`, `run.insufficient_evidence`, `proposal.ready`, `approval.recorded`, `run.rejected`, `action.granted`, `action.dispatched`, `action.confirmed/failed/conflict` and `action.uncertain` are emitted inside the functions (SA:452 refuses them from `append_event`). `ops_core.states.require_transition` stays as the Python mirror and as the source of `app.transitions` (ruling 10); `ops_core.outcomes.event_rules_ok` stays as the Python mirror of `_append_event`'s rules. Signature deviations, each a proposed erratum: `create_run` takes `request` as jsonb `{message_id, requester, asset_id, start_at, end_at}` and returns `(run_id, state_version)` (the id is minted inside); `transition_run` takes a sixth argument `detail jsonb` (the `run.failed` message, erratum 8 of Plan C); `freeze_proposal` takes the canonical bytes and the expiry instead of a jsonb payload (jsonb normalises key order, so SQL cannot recompute Plan C's canonical form; hashing the stored bytes preserves "the bytes frozen are the bytes validated"); `record_decision` takes `tenant_id` and `reviewer` first (the API is the identity trust anchor, exactly as for `create_run`'s tenant); `append_event` takes an optional `source` (only `worker` may pass `model_summary`, only for `explanation.ready`) and refuses every type a definer function emits (`run.*`, `action.*`, `review.*`, `proposal.*`, `approval.*`, `clarification.requested`), not only the three families SA:452 names; `freeze_proposal` verifies that the frozen bytes carry `runs.supersedes_run_id` rather than injecting it (the bytes are hashed before the function sees them, so injection would change the hash; the worker reads the value from `runs`, never from the draft).
6. **mcp-write's UNKNOWN path (Q6): `mark_unknown` stays `worker`-only.** After a transport failure past `SENT`, mcp-write records nothing and returns the `UNKNOWN` envelope; the worker, which holds the `mark_unknown` grant (SA:467), records `OUTCOME_UNKNOWN` and `action.uncertain` when it receives that envelope. If the worker never receives it (mcp-write died mid-call), the attempt stays `SENT` and the run `EXECUTING`; the execute job is re-queued and the replay resends (idempotent at the destination) — T22's reconciliation closes the rest. `requeue_job` keeps writing `jobs.available_at`, so the `worker` grant (and only the worker's) gains that column (proposed erratum; the alternative, a non-spec definer function, buys nothing). The worker dispatches an `execute` job whose run is `APPROVED` **or** `EXECUTING` (`JOB_RULES[EXECUTE].run_states`): after a transport failure past the grant, the re-queued job must resend under the same action id, which `grant_execution`'s replay rule provides. Cost if wrong: a one-line grant change.
7. **Tenant context for reads (Q7): `Session.read` is removed; every tenant read is a unit with the tenant set first.** `Session.unit(tenant_id)` runs `SELECT set_config('app.tenant_id', %s, true)` as the unit's first statement; `Session.unit()` (no tenant) is for non-RLS work and definer calls; `Session.ping()` replaces `read("SELECT 1")` for health. The AM-20.5 policy is written with `NULLIF(current_setting('app.tenant_id', true), '')::uuid` (spike §2: the literal text raises 22P02 on the `''` every reused connection holds), matching SA:446; R106 compares `pg_policies.qual` with the normalized form of that text. Proposed erratum.
8. **Live tests (Q8, Q9): per-session databases, `PROFILE=test`, `heads`.** The e2e `migrated` fixture drops and recreates `ops_test` and `incident_test` (superuser, `WITH (FORCE)`), sets `OPS_PG_DB`, `OPS_INCIDENT_PG_DB` and `PROFILE=test` in the process environment before anything reads settings, and runs `skeleton.migrate(profile="test")`, which upgrades `migrations/app` to `heads` (so `app.test_clock` exists) and `migrations/incident` to `head`. Dev and demo run `migrate(profile="dev")` → `app@head` (revision 0001 gains the `app` label; spike §4 measured both targets). Test seeding and purging stay on the superuser connection (`app_conn`); assertions about role behaviour use `role_conn(role)` connections. `scripts/check.py --profile test` sets `OPS_LIVE=1` and runs the same four steps, which is this repository's reading of SA:529 (proposed erratum); plain `check.py` stays database-free. Every service asserts at start that `app.test_clock` is absent unless `PROFILE=test` (SA:528), and `skeleton.py up` refuses outside the test profile when it exists. Cost if wrong: the fixture is forty lines.
9. **R082's "logged" half (Q10).** A refused transition raises `OC004 illegal_transition` with `DETAIL` naming the run, the states and the caller; PostgreSQL writes every `ERROR` to the server log, and the Python wrapper logs the refusal at WARNING with the same fields before re-raising as `IllegalTransition`. No autonomous write: a row in the same transaction would roll back with it, and the image has no `dblink`.
10. **The transition table lives in SQL as data, generated from the Python table.** Revision 0002 creates `app.transitions(src, dst, performer, reasons text[])` (not in AM-20.2; `app_definer` sel only; `src = ''` for the creation row) and fills it from `ops_core.states.TRANSITIONS` at migration time; `_transition` requires a row and, when the row names reasons, a reason from them. A unit test asserts the migration's rows equal the Python table, so the two cannot drift (R082 "one table").
11. **T10 abort and rejection (Q11).** `POST /internal/actions/{action_id}/abort` with body `{"payload_sha256": <grant hash>, "reason": "cancelled_before_send" | "expired" | "deadline"}` runs `INSERT … ('ABORTED', reason) ON CONFLICT (action_id) DO NOTHING` then reads the row (SA:263, SA:266): an existing `COMMITTED` key answers with the receipt (or `CONFLICT` if the hash differs), an existing tombstone answers with that tombstone. A POST whose envelope parses (valid `action_id` and `payload_sha256`) but whose `payload_canonical` is not a non-empty JSON object, or whose recomputed hash differs, writes a permanent `REJECTED` key with reason `invalid_payload` or `hash_mismatch` and answers 200 with the tombstone (SA:261, SA:267; Plan D ruling 9's 422-without-key is superseded); a body that does not parse to an envelope at all is still 422 with no key (there is nothing to key). The fault `reject_next` produces `REJECTED` with reason `policy`. mcp-write's abort client and the `abort_incident` tool are T22/T47's; the destination side is complete here.
12. **403 for authenticated-but-wrong-audience tokens (Q12), shared.** `ops_core.tokens` raises `WrongAudience(TokenRejected)` for an audience or `azp` mismatch after the signature, issuer and expiry checks passed; every existing `except TokenRejected` keeps answering 401 (Plan D ruling 25 stands for the API and the MCP servers), and incident-sim catches `WrongAudience` first and answers 403 `FORBIDDEN` with no action id (SA:357).
13. **Fault factory (Q13).** `ops_core.testing.faults.Faults(profile)` refuses to construct unless `profile == "test"` (R098); it is framework-free (`arm(kind, count)`, `take(kind) -> bool`, `armed() -> dict`). incident-sim mounts `POST /internal/faults/{kind}` (same workload token as the other routes, body `{"count": n}`) only under `PROFILE=test`; in `dev`/`demo` the route does not exist (404). T10 implements three of BS:405's nine faults — `reject_next` (the next POST is `REJECTED`), `drop_before_commit` (the next POST answers 503 without writing), `lose_after_commit` (the next POST commits the key and then answers 503, so only a lookup recovers it) — and T13 the rest.
14. **Detective check (Q14).** `scripts/skeleton.py keys` connects as the superuser to both configured databases and prints every `incident.action_key` row whose `(action_id, payload_sha256)` has no `app.execution_grant` row, exit 1 if any; the live suite runs it after the R105 run and asserts zero orphans. On demand, operator-run; a schedule is T32's.
15. **Key permanence (Q15): grants, not triggers.** Revision 0002 of `migrations/incident` transfers `incident.*` to `incident_owner` and grants `incident` `USAGE` on the schema and sequence and `SELECT, INSERT` on both tables; `INSERT … ON CONFLICT DO NOTHING RETURNING *` needs exactly that (spike §3). `DELETE`, `UPDATE` and `TRUNCATE` by `incident` are 42501 (R096 test). `action_key` gains `CHECK ((state = 'COMMITTED') = (incident_id IS NOT NULL))` and `CHECK ((state = 'COMMITTED') = (receipt_id IS NOT NULL))`.
16. **Leftover `spike_*` roles (Q16): none exist** (checked 2026-10-08 before this plan); R124's enumeration is restricted to the AM-20.1 names anyway.
17. **`app.current_time()` is `SECURITY DEFINER` owned by `app_definer`** so its dynamic `SELECT clock_offset FROM app.test_clock` runs with `app_definer`'s `sel` grant (SA:433) and no caller needs a grant on the table. EXECUTE is granted to every runtime role and revoked from PUBLIC (proposed erratum: the spec does not say who may call it).
18. **The worker claims across tenants by iterating `tenants`.** `jobs` is under `tenant_isolation` for `worker` (only `sweeper` has `sweeper_all`), so `claim_job` sets the tenant and tries `FOR UPDATE SKIP LOCKED` per tenant, rotating the start tenant for fairness; O(tenants) per poll until T13's wake-ups. The claimed job row carries its `tenant_id`, which the handler's unit then sets.
19. **Composite-key names and backfills are deterministic.** Every added constraint is named (`<table>_tenant_<parent>_fkey`), every backfill is `UPDATE … FROM` the parent, and revision 0002 is reversible: `downgrade()` drops the policies, revokes the grants, drops the functions, tables and columns it added and restores the state-based slot index; the live R006 test upgrades a fresh database to `heads`, downgrades to `0001_walking_skeleton`, and upgrades again.
20. **Error vocabulary.** SQLSTATE class `OC` (spike §1: an unknown class reaches psycopg as `DatabaseError` with `.sqlstate` set and never collides with built-in handling): `OC001` authority_violation (reachable only by a session that holds EXECUTE through membership or superuser status; a plain wrong role is 42501 from the ACL), `OC002` not_found, `OC003` version_conflict, `OC004` illegal_transition, `OC005` refused (with `DETAIL` = a short code: `SLOT_OCCUPIED`, `POST_GRANT_TARGET`, `ANSWER_ONLY`, `PAYLOAD_RUN_MISMATCH`, `SUPERSEDES_MISMATCH`, `NOT_REVIEWER`, `SELF_REVIEW`, `OTHER_PROPOSAL`, `PROPOSAL_NOT_IN_RUN`, `NOT_ACTIVE_APPROVED`, `NO_APPROVAL`, `CANCELLED`, `MEMBERSHIP_INACTIVE`, `INVALID_ARGUMENT`; `PAYLOAD_RUN_MISMATCH` and `SUPERSEDES_MISMATCH` are `OC005`, never `OC007`), `OC006` event_rule_violation, `OC007` hash_mismatch, `OC008` handle_rejected. `ops_core.persistence` maps them to `AuthorityViolation`, `NotFound`, `VersionConflict`, `ops_core.states.IllegalTransition`, `Refused(code)`, `ops_core.outcomes.EventRuleViolation`, `HashMismatch`, `HandleRejected`; any other `psycopg.Error` propagates (503 at the API, as before). Messages never carry a handle, a token or a secret.
21. **Handles are hashed everywhere.** `mint_handle` stores `sha256_hex(handle)`; `_resolve_handle` hashes with `encode(sha256(convert_to(p_raw_handle, 'UTF8')), 'hex')`, which equals `ops_core.canonical.sha256_hex` over the UTF-8 bytes. The server binding comes from `session_user` (`mcp_read` → read handles, `mcp_exec` → write handles) **and** from the job type (SA:496), never from the worker-written `server` column alone; the tool allowlist stays in Python (`JOB_RULES`), so `resolve_invocation` returns `job_type` rather than `allowed_tools`.
23. **Row locks versus grants.** AM-20.3's lock column asks for `proposals`, `decisions`, `memberships` and `execution_grant` `FOR SHARE`, but a row lock needs UPDATE on at least one column and AM-20.2 gives `app_definer` `sel`/`ins` only on those tables (measured in round 1: 42501 on every call). The `runs … FOR UPDATE` taken first in every function already serialises every writer of a run's proposal, decision and grant rows, and those tables are insert-only, so the functions take no lock on them; the `memberships` race against T11's sync is recorded as T11's. Proposed erratum (the alternative, an UPDATE grant on four audit-adjacent tables, contradicts SA:442).
24. **Time in the job queue.** `insert_job`, `claim_job`, `finish_job` and `requeue_job` compare and stamp with `app.current_time()` (SA:156, R126), never `now()`.
22. **Unit tests for Plan E live in `tests/plan_e/`**; live tests in `tests/e2e/` are added or updated per task. `tests/plan_d/` fakes that change shape (`FakeStore` in `test_api.py`, the incident-sim `FakeStore`, `test_persistence_pure.py`) are updated in the task that changes the interface.

## Debt-list additions (committed in Task 1, before coding)

Appended to `SESSION_STATE.md` as a new section `## Plan E debt list (T09, T10; committed before coding) [R6-B7]`, verbatim:

```markdown
Allowed shortcuts in T09/T10, each with its owning task:
- the definer functions without a caller today arrive with their owners: `create_revision`, `create_manual_proposal`, `expire_proposal`, `request_cancel` → T21; `asset_scope`, `search_procedures_scoped` → T15/T16/T17; `request_abort`, `escalate_run`, `resolve_escalation` → T22; `sync_memberships` → T11; `reclaim_leases` → T13;
- `run_lease` exists with no lease taken; `resolve_invocation`, `grant_execution`, `mark_sent` and `record_outcome` check no fence; `mark_unknown` and `revoke_handles` accept `fence` and ignore it; no asset-guard advisory lock → T13/T21;
- the worker polls per tenant (one claim attempt per tenant per poll) → T13 wake-ups;
- `migrator` holds no login: Alembic runs as the Compose superuser and transfers ownership explicitly → T30;
- schema `checkpoints` and R122 are deferred: `langgraph-checkpoint-postgres` is not locked → T20;
- `record_decision` and `grant_execution` do not enforce proposal expiry or asset freshness → T21;
- the `recover` job `mark_unknown` enqueues is claimed and finished unhandled by the worker → T22;
- `sessions` has the BUILD_SPEC §6 shape and no reader or writer → T11;
- `check.py --profile test` runs the live suite against per-session databases rather than a Compose test profile → T30;
- the fault factory implements `reject_next`, `drop_before_commit` and `lose_after_commit`; the other six BS:405 faults → T13;
- `outbox`, `feedback`, `idempotency_request`, `operator_resolutions`, `documents`/`chunks`/`embeddings`, `model_permit` are absent, so their AM-20.2 rows are not yet in the grant matrix → T14/T12/T22/T17/T13;
- the definer functions take no row lock on `proposals`, `decisions`, `memberships` or `execution_grant` (AM-20.3's lock column asks for `FOR SHARE`; a lock needs UPDATE, which AM-20.2 withholds); `runs FOR UPDATE` serialises the writers, and the `memberships` race against the sync → T11.
```

## Role and process map

| Process | Role (login) | Secret file | Definer functions it may EXECUTE | Table grants it uses directly |
|---|---|---|---|---|
| api | `api` | `postgres_api_password` | `resolve_identity`, `create_run`, `record_decision`, `append_event`, `app.current_time` | `conversations`/`messages` ins+sel, `runs` sel, `proposals`/`decisions`/`events`/`execution_grant`/`action_attempt*` sel, `run_directory` sel, `tenants`/`memberships` sel, `jobs` ins, `sessions`, `feedback`*, `idempotency_request`* |
| worker | `worker` | `postgres_worker_password` | `transition_run`, `append_event`, `freeze_proposal`, `mark_unknown`, `revoke_handles`, `app.current_time` | `jobs` sel/ins/upd(claimed_by, claimed_at, done_at, attempts, available_at), `runs` sel/upd(checkpoint_id, budget_used), `messages` sel, `drafts` ins/sel, `invocation_context` ins, `run_lease`, `tenants` sel, `run_directory` sel, `proposals`/`decisions`/`events`/`execution_grant`/`action_attempt*` sel |
| mcp-read | `mcp_read` | `postgres_mcp_read_password` | `resolve_invocation`, `app.current_time` | none |
| mcp-write | `mcp_exec` | `postgres_mcp_exec_password` | `resolve_invocation`, `grant_execution`, `mark_sent`, `record_outcome`, `lookup_action`, `app.current_time` | none |
| incident-sim | `incident` (database `incident`) | `postgres_incident_password` | — | `action_key`, `incidents` sel+ins; sequence usage |
| (none yet) | `sweeper` | `postgres_sweeper_password` | `append_event`, `app.current_time` | per AM-20.2 (`sweeper_all` on `memberships`, `jobs`) |
| (none yet) | `operator` | `postgres_operator_password` | `app.current_time` (`resolve_escalation` → T22) | none |
| (test only) | `test_harness` | `postgres_test_harness_password` | `app.current_time` | `app.test_clock` ins/upd/del (branch `testclock`) |
| migrations | superuser `ops` → owner `migrator` (NOLOGIN, BYPASSRLS) | `postgres_password` | — | owns schema `app` and every table |
| functions | `app_definer` (NOLOGIN) | — | owns every definer function | the `app_definer` column of AM-20.2 |

`*` = table absent until its owner task; the matrix gains the row then.

Environment every process reads (set by `scripts/skeleton.py` from `.env`; defaults in `ops_core.settings`): as in Plan D plus `PROFILE` (`dev` | `test` | `demo`, default `dev`), `OPS_PG_DB` (default `ops`), `OPS_INCIDENT_PG_DB` (default `incident`). `OPS_PG_USER` is gone: the role is the process's own.

## Task overview

| Task | Delivers | Tests |
|---|---|---|
| 1 | Debt list; research files committed; seven role secrets (`bootstrap_dev.py`, `compose.yaml`); `ops_core.settings` (`Profile`, `Role`, `superuser_postgres`, `app_postgres(role)`); `ops_core.privileges` (roles, grant matrix, policy text, statement renderers, definer caller lists); `tests/plan_e` package | `tests/plan_e/test_settings_roles.py`, `tests/plan_e/test_privileges.py`; updated Plan B static tests |
| 2 | `scripts/skeleton.py` `ensure_roles`, `migrate(profile)`, `up` refusal, `keys`; revision `0002_roles_grants_rls`; branch `tc_0001_test_clock`; `0001` labelled `app`; e2e fixtures (per-session databases, `role_conn`); live R006/R007/R008/R009/R084/R124/R126 tests | `tests/plan_e/test_skeleton_cli.py`; `tests/e2e/test_migrations_and_persistence.py` (updated), `tests/e2e/test_roles_live.py`, `tests/e2e/test_clock_live.py` |
| 3 | Revision `0003_run_path_functions`: helpers, `app.transitions`, `create_run`, `transition_run`, `append_event`, `resolve_identity`, `revoke_handles`; live R128/R106(part) tests | `tests/plan_e/test_transitions_table.py`; `tests/e2e/test_definers_run_path_live.py` |
| 4 | Revision `0004_write_path_functions`: `freeze_proposal`, `record_decision`, `resolve_invocation`, `grant_execution`, `mark_sent`, `record_outcome`, `lookup_action`, `mark_unknown`; live tests incl. preset-tenant and cross-tenant (R106) | `tests/e2e/test_definers_write_path_live.py` |
| 5 | `ops_core.persistence` rewritten on the functions (`Session.unit(tenant_id)`, wrappers, error mapping, hashed handles, `claim_job` per tenant, clock-profile assertion); `tests/plan_d/test_persistence_pure.py` updated | `tests/plan_e/test_persistence_errors.py`; `tests/e2e/test_migrations_and_persistence.py` (updated to the wrappers) |
| 6 | api and worker on their roles and the functions (identity, admission, decision, reads; claim per tenant, freeze, UNKNOWN → `mark_unknown`, `revoke_handles`); `tests/plan_d/test_api.py` and `test_worker.py` updated | `tests/plan_e/test_api_store_mapping.py`; `tests/e2e/test_worker_live.py` (updated) |
| 7 | mcp-read and mcp-write on their roles and the functions (`resolve_invocation`, `grant_execution`/`mark_sent`/`record_outcome`/`lookup_action`, UNKNOWN without recording); `tests/plan_d/test_mcp_write.py` updated; R105 re-run | `tests/e2e/test_mcp_read_live.py`, `tests/e2e/test_mcp_write_live.py`, `tests/e2e/test_r105_walking_skeleton.py` (updated) |
| 8 | T10: `ops_core.tokens.WrongAudience`; `ops_core.testing.faults`; `migrations/incident` revision `0002_destination_hardening`; incident-sim abort, `REJECTED`, 403, faults, profile; live races; `keys` detective check | `tests/plan_e/test_tokens_audience.py`, `test_faults.py`, `test_incident_sim_t10.py`; `tests/e2e/test_incident_sim_live.py` (R010, R047, R096, R098) |
| 9 | `check.py --profile`; runbooks; handoff docs (tasks, matrix, backlog, STATUS, SESSION_STATE, README); evidence; errata list | docs; `verify_handoff.py`; full live suite |

---
### Task 1: Debt before code — role secrets, settings (profile, roles), the privilege matrix

**Files:**
- Modify: `SESSION_STATE.md` (new debt section), `scripts/bootstrap_dev.py` (`SECRET_NAMES`), `compose.yaml` (top-level `secrets:`), `core/src/ops_core/settings.py`, `scripts/skeleton.py:98-99` and `tests/e2e/conftest.py:56`, `api/src/ops_api/app.py`, `worker/src/ops_worker/main.py:81-82`, `mcp-read/src/ops_mcp_read/server.py`, `mcp-write/src/ops_mcp_write/server.py` (mechanical rename `app_postgres()` → `superuser_postgres()`; the role switch is Tasks 6–7), `pyproject.toml` (`testpaths` gains `tests/plan_e`)
- Create: `core/src/ops_core/privileges.py`, `tests/plan_e/__init__.py`, `tests/plan_e/test_settings_roles.py`, `tests/plan_e/test_privileges.py`

**Interfaces:**
- Produces: `ops_core.settings.Profile` (`StrEnum`: `DEV = "dev"`, `TEST = "test"`, `DEMO = "demo"`), `profile() -> Profile` (env `PROFILE`, default `dev`, anything else → `SettingsError`), `Role` (`StrEnum`: `API = "api"`, `WORKER = "worker"`, `SWEEPER = "sweeper"`, `MCP_READ = "mcp_read"`, `MCP_EXEC = "mcp_exec"`, `OPERATOR = "operator"`, `TEST_HARNESS = "test_harness"`), `superuser_postgres() -> Postgres` (user `OPS_PG_SUPERUSER` default `ops`, db `OPS_PG_DB` default `ops`, secret `postgres_password`), `app_postgres(role: Role) -> Postgres` (user `role.value`, same db, secret `postgres_<role>_password`), `incident_postgres()` unchanged (db from `OPS_INCIDENT_PG_DB`), `secret_name(role) -> str`.
- Produces: `ops_core.privileges` — `SCHEMA = "app"`, `RUNTIME_ROLES`, `DEFINER_ROLE = "app_definer"`, `OWNER_ROLE = "migrator"`, `GRANTEES`, `POLICY_ROLES`, `Grant` (frozen dataclass: `sel`, `ins`, `upd: tuple[str, ...] | bool`, `dele`; `privileges() -> set[tuple[str, str | None]]`), `GRANTS: dict[str, dict[str, Grant]]`, `RLS_TABLES`, `SWEEPER_ALL`, `NO_RLS`, `TENANT_EXPR`, `POLICY_QUAL`, `DEFINER_FUNCTIONS: dict[str, tuple[str, tuple[str, ...]]]` (name → (argument type list, callers)), `HELPER_FUNCTIONS: dict[str, str]`, `MAIN_ROLES`, `TEST_ONLY_ROLES`, `MAIN_GRANTEES`, `schema_usage_statements(roles=MAIN_GRANTEES)`, `grant_statements(tables)`, `rls_statements(tables)`, `function_grant_statements(name, roles=None)`, `AUDIT_TABLES`.
- Produces: the seven secret files' names; `tests/plan_e` on `testpaths`.

- [ ] **Step 1: Commit the debt list (before any code)**

Append the section from this plan's "Debt-list additions" to `SESSION_STATE.md` immediately after the `## Walking-skeleton debt list …` section's "Not debt" paragraph (before `## Environment (observed)`). Then:

```bash
git add SESSION_STATE.md
git commit -m "docs: declare Plan E's shortcuts before coding (T09/T10 debt list)"
```

- [ ] **Step 2: Write the failing settings tests**

Create `tests/plan_e/__init__.py` (empty) and `tests/plan_e/test_settings_roles.py`:

```python
"""Per-role database settings and the profile switch (AM-20.1 one login per service; AM-20.6/20.7 profiles).

Catches: a service that could still connect as the owner by default, a role whose secret file name does not follow
the `postgres_<role>_password` pattern the bootstrap generates, a profile value that is not one of the three, and a
password that reaches a repr.
"""

from pathlib import Path

import pytest
from ops_core import settings
from ops_core.settings import Profile, Role, SettingsError


@pytest.fixture
def secrets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("OPS_SECRETS_DIR", str(tmp_path))
    monkeypatch.delenv("PROFILE", raising=False)
    monkeypatch.delenv("OPS_PG_DB", raising=False)
    (tmp_path / "postgres_password").write_text("owner-pw\n", encoding="utf-8")
    for role in Role:
        (tmp_path / f"postgres_{role.value}_password").write_text(f"{role.value}-pw\n", encoding="utf-8")
    return tmp_path


def test_every_role_reads_its_own_secret_file_and_connects_as_itself(secrets: Path) -> None:
    for role in Role:
        pg = settings.app_postgres(role)
        assert pg.user == role.value and pg.dbname == "ops" and pg.password == f"{role.value}-pw"
        assert f"user={role.value}" in pg.conninfo() and "owner-pw" not in pg.conninfo()
        assert "-pw" not in repr(pg)


def test_superuser_is_explicit_and_the_database_name_follows_the_environment(
    secrets: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert settings.app_postgres.__defaults__ is None  # the role is required: no caller connects as the owner by accident
    monkeypatch.setenv("OPS_PG_DB", "ops_test")
    assert settings.superuser_postgres().user == "ops" and settings.superuser_postgres().dbname == "ops_test"
    assert settings.app_postgres(Role.API).dbname == "ops_test"


def test_missing_role_secret_names_the_file_not_the_path(secrets: Path) -> None:
    (secrets / "postgres_sweeper_password").unlink()
    with pytest.raises(SettingsError) as exc:
        settings.app_postgres(Role.SWEEPER)
    assert "postgres_sweeper_password" in str(exc.value) and str(secrets) not in str(exc.value)


@pytest.mark.parametrize(("raw", "expected"), [(None, Profile.DEV), ("test", Profile.TEST), ("demo", Profile.DEMO)])
def test_profile_defaults_to_dev(monkeypatch: pytest.MonkeyPatch, raw: str | None, expected: Profile) -> None:
    if raw is None:
        monkeypatch.delenv("PROFILE", raising=False)
    else:
        monkeypatch.setenv("PROFILE", raw)
    assert settings.profile() is expected


def test_unknown_profile_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROFILE", "prod")
    with pytest.raises(SettingsError):
        settings.profile()


def test_secret_names_match_the_bootstrap_list() -> None:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from scripts.bootstrap_dev import SECRET_NAMES

    for role in Role:
        assert settings.secret_name(role) in SECRET_NAMES
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/plan_e/test_settings_roles.py -q`
Expected: FAIL with `ImportError: cannot import name 'Profile'`.

- [ ] **Step 4: Extend `ops_core.settings`**

In `core/src/ops_core/settings.py` add after the imports `from enum import StrEnum`, and replace the block from `def _pg_host_port()` through `def app_postgres()` with:

```python
class Profile(StrEnum):
    """The three v1 profiles (SA:40); R098's "default" profile means dev and demo (SA:49)."""

    DEV = "dev"
    TEST = "test"
    DEMO = "demo"


def profile() -> Profile:
    """The process profile from `PROFILE`; dev when unset; anything else is a refusal to start."""
    raw = env("PROFILE", Profile.DEV.value)
    try:
        return Profile(raw)
    except ValueError as exc:
        raise SettingsError("PROFILE must be one of dev, test, demo") from exc


class Role(StrEnum):
    """The login roles of AM-20.1; each process connects as exactly one of them (never as the owner)."""

    API = "api"
    WORKER = "worker"
    SWEEPER = "sweeper"
    MCP_READ = "mcp_read"
    MCP_EXEC = "mcp_exec"
    OPERATOR = "operator"
    TEST_HARNESS = "test_harness"


def secret_name(role: Role) -> str:
    """The secret file that holds a role's password; scripts/bootstrap_dev.py generates one per role."""
    return f"postgres_{role.value}_password"


def _pg_host_port() -> tuple[str, int]:
    return env("OPS_PG_HOST", "127.0.0.1"), env_int("OPS_PG_PORT", 15432)


def _app_db() -> str:
    return env("OPS_PG_DB", "ops")


def superuser_postgres() -> Postgres:
    """The Compose superuser: migrations, role bootstrap and test fixtures only, never a service (SA:395, SA:521)."""
    host, port = _pg_host_port()
    return Postgres(host, port, env("OPS_PG_SUPERUSER", "ops"), _app_db(), read_secret("postgres_password"))


def app_postgres(role: Role) -> Postgres:
    """The application database as one runtime role; the role is required so no caller inherits the owner."""
    host, port = _pg_host_port()
    return Postgres(host, port, role.value, _app_db(), read_secret(secret_name(role)))
```

Update the module docstring's last sentence to say that every service connects as its own AM-20.1 role and that `PROFILE` selects the profile.

- [ ] **Step 5: Rename the six existing callers mechanically**

Replace `settings.app_postgres()` with `settings.superuser_postgres()` in `scripts/skeleton.py` (`migrate`), `tests/e2e/conftest.py` (`app_conn`), `tests/plan_d/test_settings.py:51` (and add `OPS_PG_SUPERUSER` to that test's `delenv` list), `tests/e2e/test_mcp_write_live.py:109` (the witness connection), `api/src/ops_api/app.py` (the production store factory), `worker/src/ops_worker/main.py` (both connections; put the trailing comment on its own line above, the renamed line is over 120 columns otherwise), `mcp-read/src/ops_mcp_read/server.py` and `mcp-write/src/ops_mcp_write/server.py` (`production_app`). The four service sites get the comment `# TODO(T09): connect as this service's own role (Task 6/7)`; the skeleton, conftest and test sites stay superuser by design and get no comment. Add `"tests/plan_e"` to `testpaths` in `pyproject.toml` (after `tests/plan_d`).

- [ ] **Step 6: Add the seven secrets to the bootstrap and compose**

In `scripts/bootstrap_dev.py`, append to `SECRET_NAMES` (after `kc_persona_jordan_password`):

```python
    # One login per AM-20.1 role (T09); read by scripts/skeleton.py migrate and by each service, never mounted.
    "postgres_api_password",
    "postgres_worker_password",
    "postgres_sweeper_password",
    "postgres_mcp_read_password",
    "postgres_mcp_exec_password",
    "postgres_operator_password",
    "postgres_test_harness_password",
```

In `compose.yaml`, append to the top-level `secrets:` map, after `kc_persona_jordan_password`:

```yaml
  postgres_api_password:
    file: ${OPS_SECRETS_DIR}/postgres_api_password
  postgres_worker_password:
    file: ${OPS_SECRETS_DIR}/postgres_worker_password
  postgres_sweeper_password:
    file: ${OPS_SECRETS_DIR}/postgres_sweeper_password
  postgres_mcp_read_password:
    file: ${OPS_SECRETS_DIR}/postgres_mcp_read_password
  postgres_mcp_exec_password:
    file: ${OPS_SECRETS_DIR}/postgres_mcp_exec_password
  postgres_operator_password:
    file: ${OPS_SECRETS_DIR}/postgres_operator_password
  postgres_test_harness_password:
    file: ${OPS_SECRETS_DIR}/postgres_test_harness_password
```

Then generate the files on this machine (idempotent; existing files are kept; it rewrites `.env` with identical content): `uv run python scripts/bootstrap_dev.py secrets`. Confirm with `ls "$(grep OPS_SECRETS_DIR .env | cut -d= -f2)" | grep -c postgres_` → `9`. Never print a file's content.

- [ ] **Step 7: Run the settings tests and the Plan B static tests**

Run: `uv run python -m pytest tests/plan_e/test_settings_roles.py tests/plan_b/test_bootstrap_dev.py tests/plan_b/test_compose_dev.py tests/plan_d/test_settings.py -q`
Expected: PASS.

- [ ] **Step 8: Write the failing privilege-matrix tests**

Create `tests/plan_e/test_privileges.py`:

```python
"""The AM-20.2 matrix as data (R124's source of truth) and the statements rendered from it.

Catches: a table that is neither an RLS table nor a declared no-RLS table, a function-only role with a table grant
(R084), an audit table that any role could UPDATE or DELETE (AM-20 principle 2), a definer function granted to an
unknown role, a policy text that is not the NULLIF form (spike §2), and a rendered statement that SQLAlchemy would
parse as a bind parameter (fact sheet §4.3).
"""

import re

from ops_core import privileges as p


def test_every_table_is_classified_once() -> None:
    assert set(p.GRANTS) == set(p.RLS_TABLES) | set(p.NO_RLS)
    assert not set(p.RLS_TABLES) & set(p.NO_RLS)
    assert set(p.SWEEPER_ALL) <= set(p.RLS_TABLES)


def test_function_only_roles_have_no_table_grant() -> None:
    for table, grants in p.GRANTS.items():
        for role in ("mcp_read", "mcp_exec", "operator"):
            assert role not in grants, (table, role)
    for grants in p.GRANTS.values():
        assert set(grants) <= set(p.GRANTEES)


def test_audit_tables_are_append_only_and_only_the_definer_writes_them() -> None:
    for table in p.AUDIT_TABLES:
        for role, grant in p.GRANTS[table].items():
            assert grant.upd is False and grant.dele is False, (table, role)
            assert not grant.ins or role == p.DEFINER_ROLE, (table, role)


def test_runtime_roles_never_write_state_or_events_directly() -> None:
    assert p.GRANTS["runs"]["api"].upd == ("cancel_requested", "cancel_requested_at")
    assert p.GRANTS["runs"]["worker"].upd == ("checkpoint_id", "budget_used")
    assert "state" in p.GRANTS["runs"][p.DEFINER_ROLE].upd
    for table in ("events", "decisions", "proposals", "execution_grant", "action_attempt_state"):
        assert [r for r, g in p.GRANTS[table].items() if g.ins] == [p.DEFINER_ROLE], table


def test_definer_callers_are_runtime_roles() -> None:
    for name, (_, callers) in p.DEFINER_FUNCTIONS.items():
        assert callers and set(callers) <= set(p.RUNTIME_ROLES), name
    assert p.DEFINER_FUNCTIONS["transition_run"][1] == ("worker",)
    assert p.DEFINER_FUNCTIONS["mark_unknown"][1] == ("worker",)
    assert set(p.DEFINER_FUNCTIONS["resolve_invocation"][1]) == {"mcp_read", "mcp_exec"}
    assert all(name.startswith("_") for name in p.HELPER_FUNCTIONS)


def test_rendered_statements() -> None:
    grants = p.grant_statements(["runs"])
    assert grants[0] == "REVOKE ALL ON app.runs FROM " + ", ".join(p.MAIN_GRANTEES)
    assert p.grant_statements(["test_clock"])[0] == "REVOKE ALL ON app.test_clock FROM " + ", ".join(p.GRANTEES)
    assert "GRANT UPDATE (cancel_requested, cancel_requested_at) ON app.runs TO api" in grants
    assert "GRANT SELECT ON app.runs TO sweeper" in grants
    assert "GRANT INSERT, SELECT ON app.runs TO app_definer" in grants
    rls = p.rls_statements(["jobs"])
    assert rls[0] == "ALTER TABLE app.jobs ENABLE ROW LEVEL SECURITY"
    assert rls[1] == "ALTER TABLE app.jobs FORCE ROW LEVEL SECURITY"
    assert any(s.startswith("CREATE POLICY tenant_isolation ON app.jobs FOR ALL TO api, worker, sweeper, app_definer") for s in rls)
    assert any("CREATE POLICY sweeper_all ON app.jobs FOR ALL TO sweeper USING (true) WITH CHECK (true)" in s for s in rls)
    assert p.TENANT_EXPR == "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    fn = p.function_grant_statements("create_run")
    assert fn == [
        "REVOKE ALL ON FUNCTION app.create_run(uuid, uuid, jsonb, text, uuid) FROM PUBLIC",
        "GRANT EXECUTE ON FUNCTION app.create_run(uuid, uuid, jsonb, text, uuid) TO api",
    ]
    clock = p.function_grant_statements("current_time", roles=p.MAIN_ROLES)
    assert clock[1] == "GRANT EXECUTE ON FUNCTION app.current_time() TO " + ", ".join(p.MAIN_ROLES)
    assert p.function_grant_statements("current_time", roles=p.TEST_ONLY_ROLES)[1].endswith("TO test_harness")
    assert p.GRANTS["jobs"]["sweeper"].upd == ("claimed_by", "claimed_at", "done_at", "attempts")
    assert p.GRANTS["jobs"]["worker"].upd == ("claimed_by", "claimed_at", "done_at", "attempts", "available_at")
    bind = re.compile(r"(?<![:\w]):\w")  # ` :name` is a SQLAlchemy bind; `::uuid` is a cast
    for statement in [*grants, *rls, *fn, *p.schema_usage_statements()]:
        assert not bind.search(statement), statement
```

- [ ] **Step 9: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/plan_e/test_privileges.py -q`
Expected: FAIL with `ImportError: cannot import name 'privileges' from 'ops_core'`.

- [ ] **Step 10: Write `ops_core.privileges`**

Create `core/src/ops_core/privileges.py`:

```python
"""The AM-20 privilege matrix as data: roles, per-table grants, the RLS tables and policy text, and each definer
function's callers (SPEC_AMENDMENTS AM-20.1, AM-20.2, AM-20.3, AM-20.5).

One source of truth for two consumers: the migrations render GRANT, REVOKE and POLICY statements from it for the
tables each revision creates or changes (never for "every table": an applied revision must not change when a row is
added here), and the R124/R106 tests enumerate the catalogs against it, so an extra or missing grant fails a test
instead of hiding. Rows exist only for tables that exist; the owners of later tables (outbox → T14, feedback and idempotency_request
→ T12, operator_resolutions → T22, documents/chunks/embeddings → T17, model_permit → T13) add their rows. Four
departures from the printed table, each a proposed erratum (Plan E rulings 6, 10, 17, 23): the worker (not the
sweeper) may UPDATE jobs.available_at (re-queue after a transport failure), app_definer may UPDATE runs.updated_at,
the `transitions` table (the T07 table mirrored in SQL) is readable by app_definer only, and no definer function
takes a row lock on proposals, decisions, memberships or execution_grant (a lock needs UPDATE, which the matrix
withholds). `test_harness` exists only in the test profile: the main-line revisions grant it nothing; the testclock
branch grants it schema USAGE, EXECUTE on current_time() and its test_clock cells.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

SCHEMA: Final = "app"
RUNTIME_ROLES: Final = ("api", "worker", "sweeper", "mcp_read", "mcp_exec", "operator", "test_harness")
DEFINER_ROLE: Final = "app_definer"
OWNER_ROLE: Final = "migrator"
TEST_ONLY_ROLES: Final = ("test_harness",)  # SA:403: created and granted in the test profile only
MAIN_ROLES: Final = tuple(r for r in RUNTIME_ROLES if r not in TEST_ONLY_ROLES)
GRANTEES: Final = (*RUNTIME_ROLES, DEFINER_ROLE)
MAIN_GRANTEES: Final = (*MAIN_ROLES, DEFINER_ROLE)
POLICY_ROLES: Final = ("api", "worker", "sweeper", DEFINER_ROLE)  # SA:514


@dataclass(frozen=True)
class Grant:
    """One cell of AM-20.2: `upd` is True for every column, a tuple for exactly those columns, False for none."""

    sel: bool = False
    ins: bool = False
    upd: tuple[str, ...] | bool = False
    dele: bool = False

    def privileges(self) -> set[tuple[str, str | None]]:
        """(privilege, column) pairs as the catalogs report them; column is None for a whole-table privilege."""
        out: set[tuple[str, str | None]] = set()
        if self.sel:
            out.add(("SELECT", None))
        if self.ins:
            out.add(("INSERT", None))
        if self.dele:
            out.add(("DELETE", None))
        if self.upd is True:
            out.add(("UPDATE", None))
        elif self.upd:
            out.update(("UPDATE", column) for column in self.upd)
        return out


_S = Grant(sel=True)
_SI = Grant(sel=True, ins=True)
_INS = Grant(ins=True)
_JOB_COLUMNS = ("claimed_by", "claimed_at", "done_at", "attempts")  # AM-20.2; the worker alone adds available_at

GRANTS: Final[dict[str, dict[str, Grant]]] = {
    "tenants": {"api": _S, "worker": _S, "sweeper": _S, DEFINER_ROLE: _S},
    "memberships": {
        "api": _S,
        "worker": _S,
        "sweeper": Grant(sel=True, upd=("active", "permission_version", "synced_at")),
        DEFINER_ROLE: _S,
    },
    "sessions": {
        "api": Grant(sel=True, ins=True, upd=("last_seen_at", "revoked_at"), dele=True),
        "sweeper": Grant(dele=True),
    },
    "conversations": {"api": _SI, "worker": _S, DEFINER_ROLE: _S},
    "messages": {"api": _SI, "worker": _S, DEFINER_ROLE: _S},
    "runs": {
        "api": Grant(sel=True, upd=("cancel_requested", "cancel_requested_at")),
        "worker": Grant(sel=True, upd=("checkpoint_id", "budget_used")),
        "sweeper": _S,
        DEFINER_ROLE: Grant(
            ins=True,
            sel=True,
            upd=(
                "state",
                "state_version",
                "reason",
                "active_proposal_id",
                "next_event_seq",
                "slot_held",
                "supersedes_run_id",
                "updated_at",
            ),
        ),
    },
    "run_directory": {"api": _S, "worker": _S, "sweeper": _S, DEFINER_ROLE: _SI},
    "run_state_history": {DEFINER_ROLE: _INS},
    "run_lease": {
        "worker": Grant(sel=True, ins=True, upd=True),
        "sweeper": Grant(sel=True, upd=("lease_until",)),
        DEFINER_ROLE: _S,
    },
    "jobs": {
        "api": _INS,
        "worker": Grant(sel=True, ins=True, upd=(*_JOB_COLUMNS, "available_at")),
        "sweeper": Grant(sel=True, ins=True, upd=_JOB_COLUMNS),
        DEFINER_ROLE: _SI,
    },
    "invocation_context": {"worker": _INS, "sweeper": _S, DEFINER_ROLE: Grant(sel=True, upd=("revoked_at",))},
    "drafts": {"worker": _SI, DEFINER_ROLE: _S},
    "proposals": {"api": _S, "worker": _S, "sweeper": _S, DEFINER_ROLE: _SI},
    "decisions": {"api": _S, "worker": _S, DEFINER_ROLE: _SI},
    "execution_grant": {"api": _S, "worker": _S, "sweeper": _S, DEFINER_ROLE: _SI},
    "action_attempt": {"api": _S, "worker": _S, "sweeper": _S, DEFINER_ROLE: _SI},
    "action_attempt_state": {"api": _S, "worker": _S, "sweeper": _S, DEFINER_ROLE: _SI},
    "events": {"api": _S, "worker": _S, "sweeper": _S, DEFINER_ROLE: _SI},
    "transitions": {DEFINER_ROLE: _S},
    "test_clock": {DEFINER_ROLE: _S, "test_harness": Grant(ins=True, upd=True, dele=True)},
}

# AM-20.5 tenant tables (of those that exist); FORCE applies to the owner, who is exempt only through BYPASSRLS.
RLS_TABLES: Final = (
    "memberships",
    "conversations",
    "messages",
    "runs",
    "run_state_history",
    "jobs",
    "drafts",
    "proposals",
    "decisions",
    "execution_grant",
    "action_attempt",
    "action_attempt_state",
    "events",
)
SWEEPER_ALL: Final = ("memberships", "jobs")  # SA:520: the only policies besides tenant_isolation
NO_RLS: Final = ("tenants", "run_directory", "run_lease", "sessions", "invocation_context", "transitions", "test_clock")
AUDIT_TABLES: Final = ("run_state_history", "action_attempt_state", "events")  # AM-20 principle 2

# The policy expression (SA:446's NULLIF form, not SA:512's bare cast: '' raises 22P02, measured in the spike), and
# the text PostgreSQL stores for it in pg_policies.qual, which R106 compares.
TENANT_EXPR: Final = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
POLICY_QUAL: Final = "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)"

# name -> (argument types, callers granted EXECUTE); the signature text is what GRANT needs to name an overload.
DEFINER_FUNCTIONS: Final[dict[str, tuple[str, tuple[str, ...]]]] = {
    "current_time": ("", RUNTIME_ROLES),
    "resolve_identity": ("text, uuid", ("api",)),  # the sweeper's membership sync (T11) adds itself
    "create_run": ("uuid, uuid, jsonb, text, uuid", ("api",)),
    "transition_run": ("uuid, text, text, text, integer, jsonb", ("worker",)),
    "append_event": ("uuid, text, jsonb, text", ("api", "worker", "sweeper")),
    "revoke_handles": ("uuid, bigint", ("worker",)),
    "freeze_proposal": ("uuid, uuid, bytea, timestamptz", ("worker",)),
    "record_decision": ("uuid, uuid, uuid, text, text, text, text", ("api",)),
    "resolve_invocation": ("text, text", ("mcp_read", "mcp_exec")),
    "grant_execution": ("text, uuid", ("mcp_exec",)),
    "mark_sent": ("uuid", ("mcp_exec",)),
    "record_outcome": ("uuid, text, jsonb", ("mcp_exec",)),
    "lookup_action": ("text", ("mcp_exec",)),
    "mark_unknown": ("uuid, bigint", ("worker",)),
}
# Internal helpers: owned by app_definer, revoked from PUBLIC, granted to nobody (SA:474).
HELPER_FUNCTIONS: Final[dict[str, str]] = {
    "_authority": "text, text[]",
    "_tenant_of_run": "uuid",
    "_tenant_of_action": "uuid",
    "_resolve_handle": "text, text, text",
    "_latest_attempt": "uuid",
    "_append_event": "uuid, uuid, text, text, jsonb",
    "_transition": "uuid, text, text, text, integer, text, jsonb",
}


def _roles(roles: Iterable[str]) -> str:
    return ", ".join(roles)


def schema_usage_statements(roles: Iterable[str] = MAIN_GRANTEES) -> list[str]:
    """The grantees may see the schema; what they may touch inside is the matrix's business."""
    return [f"GRANT USAGE ON SCHEMA {SCHEMA} TO {_roles(roles)}"]


def grant_statements(tables: Iterable[str]) -> list[str]:
    """REVOKE ALL then exactly the matrix's grants for each table; re-runnable by any later revision."""
    out: list[str] = []
    for table in tables:
        # Only roles that exist in every profile are named in a REVOKE: the test-only role's grants live on the branch.
        revokees = [r for r in GRANTEES if r not in TEST_ONLY_ROLES or table == "test_clock"]
        out.append(f"REVOKE ALL ON {SCHEMA}.{table} FROM {_roles(revokees)}")
        for role, grant in GRANTS[table].items():
            whole = [name for name, flag in (("INSERT", grant.ins), ("SELECT", grant.sel), ("DELETE", grant.dele)) if flag]
            if grant.upd is True:
                whole.append("UPDATE")
            if whole:
                out.append(f"GRANT {', '.join(whole)} ON {SCHEMA}.{table} TO {role}")
            if isinstance(grant.upd, tuple) and grant.upd:
                out.append(f"GRANT UPDATE ({', '.join(grant.upd)}) ON {SCHEMA}.{table} TO {role}")
    return out


def rls_statements(tables: Iterable[str]) -> list[str]:
    """ENABLE + FORCE and the AM-20.5 policies; DROP IF EXISTS first so a revision can re-apply them."""
    out: list[str] = []
    for table in tables:
        rel = f"{SCHEMA}.{table}"
        out.append(f"ALTER TABLE {rel} ENABLE ROW LEVEL SECURITY")
        out.append(f"ALTER TABLE {rel} FORCE ROW LEVEL SECURITY")
        out.append(f"DROP POLICY IF EXISTS tenant_isolation ON {rel}")
        out.append(
            f"CREATE POLICY tenant_isolation ON {rel} FOR ALL TO {_roles(POLICY_ROLES)}"
            f" USING (tenant_id = {TENANT_EXPR}) WITH CHECK (tenant_id = {TENANT_EXPR})"
        )
        if table in SWEEPER_ALL:
            out.append(f"DROP POLICY IF EXISTS sweeper_all ON {rel}")
            out.append(f"CREATE POLICY sweeper_all ON {rel} FOR ALL TO sweeper USING (true) WITH CHECK (true)")
    return out


def function_grant_statements(name: str, roles: Iterable[str] | None = None) -> list[str]:
    """REVOKE from PUBLIC, then GRANT EXECUTE to the named callers (none for a helper), in that order (SA:446).

    `roles` narrows the callers for a main-line revision (the test-only role gets its EXECUTE on the branch).
    """
    if name in HELPER_FUNCTIONS:
        return [f"REVOKE ALL ON FUNCTION {SCHEMA}.{name}({HELPER_FUNCTIONS[name]}) FROM PUBLIC"]
    args, callers = DEFINER_FUNCTIONS[name]
    signature = f"{SCHEMA}.{name}({args})"
    grantees = [r for r in callers if roles is None or r in roles]
    out = [f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC"]
    if grantees:
        out.append(f"GRANT EXECUTE ON FUNCTION {signature} TO {_roles(grantees)}")
    return out
```

- [ ] **Step 11: Run the tests and the gate**

Run: `uv run ruff format core/src/ops_core/settings.py core/src/ops_core/privileges.py tests/plan_e scripts/bootstrap_dev.py scripts/skeleton.py tests/e2e/conftest.py tests/e2e/test_mcp_write_live.py tests/plan_d/test_settings.py api/src/ops_api/app.py worker/src/ops_worker/main.py mcp-read/src/ops_mcp_read/server.py mcp-write/src/ops_mcp_write/server.py && uv run ruff check --fix core/src tests/plan_e tests/plan_d tests/e2e scripts api/src worker/src mcp-read/src mcp-write/src && uv run python -m pytest tests/plan_e -q`
Expected: PASS. Then `PYTHONUTF8=1 uv run python scripts/check.py` → GREEN (`tests/plan_b` compose and bootstrap tests pass with the thirteen+seven secrets; Plan D's settings test passes because Step 5 renamed its call).

- [ ] **Step 12: Commit**

```bash
git add SESSION_STATE.md scripts/bootstrap_dev.py compose.yaml pyproject.toml core/src/ops_core/settings.py core/src/ops_core/privileges.py tests/plan_e tests/plan_d/test_settings.py tests/e2e/test_mcp_write_live.py scripts/skeleton.py tests/e2e/conftest.py api/src/ops_api/app.py worker/src/ops_worker/main.py mcp-read/src/ops_mcp_read/server.py mcp-write/src/ops_mcp_write/server.py
git commit -m "feat(core): per-role database settings, the profile switch and the AM-20 privilege matrix as data (T09)"
```

---
### Task 2: Roles, revision 0002 (schema, ownership, grants, RLS, clock), the `testclock` branch, per-session test databases

**Files:**
- Modify: `scripts/skeleton.py` (role bootstrap, `migrate(profile)`, `downgrade`, `clock_guard`, `keys`, `process_environment`), `migrations/app/versions/0001_walking_skeleton.py:22` (`branch_labels = ("app",)`), `tests/e2e/conftest.py`, `tests/e2e/test_migrations_and_persistence.py`, `docs/runbooks/walking-skeleton.md` (migrate profiles and the new secrets; one paragraph)
- Create: `migrations/app/versions/0002_roles_grants_rls.py`, `migrations/app/versions/tc_0001_test_clock.py`, `tests/plan_e/test_skeleton_cli.py`, `tests/e2e/test_roles_live.py`, `tests/e2e/test_clock_live.py`

**Interfaces:**
- Consumes: `ops_core.settings.Role`, `Profile`, `superuser_postgres()`, `app_postgres(role)`, `secret_name(role)`; `ops_core.privileges.*` (Task 1).
- Produces: `scripts/skeleton.py` — `ensure_roles(superuser: Postgres, app_db: str, incident_db: str, profile: Profile) -> None`, `migrate(profile: Profile | None = None) -> int`, `migrate_target(profile: Profile) -> str` (`"heads"` for test, `"app@head"` otherwise), `upgrade(tree, pg, target)`, `downgrade(tree, pg, target)`, `clock_guard(superuser: Postgres, profile: Profile) -> None` (raises `RuntimeError` when `app.test_clock` exists outside the test profile), `orphan_keys(keys, grants) -> list[tuple[UUID, str]]`, `keys() -> int`; the CLI commands `migrate | up | down | status | keys`.
- Produces: database roles `migrator` (NOLOGIN, BYPASSRLS), `app_definer` (NOLOGIN), `incident_owner` (NOLOGIN), the seven login roles, `incident`; schema `app` owned by `migrator`; the AM-20.2 grants and AM-20.5 policies on the fifteen revision-1 tables plus `run_directory`, `run_lease`, `sessions`, `transitions`; `app.current_time()`; `app.test_clock` (test profile).
- Produces: e2e fixtures `env` (sets `OPS_PG_DB=ops_test`, `OPS_INCIDENT_PG_DB=incident_test`, `PROFILE=test`), `migrated` (recreates both databases, `migrate(Profile.TEST)`), `app_conn` (superuser on `ops_test`), `role_conn` (async factory `(Role) -> Conn`), `incident_conn` (role `incident` on `incident_test`), `purge_run`/`purge_tenant` (unchanged, superuser).

- [ ] **Step 1: Write the failing CLI unit tests**

Create `tests/plan_e/test_skeleton_cli.py`:

```python
"""The pure parts of scripts/skeleton.py: the Alembic target per profile (SA:529), and the detective check's set
arithmetic (T10 review note 3). The database-touching parts are proved live in tests/e2e."""

import sys
from pathlib import Path
from uuid import UUID

from ops_core.settings import Profile

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.skeleton import migrate_target, orphan_keys  # ruff allows an import after a sys.path edit


def test_only_the_test_profile_applies_the_testclock_branch() -> None:
    assert migrate_target(Profile.TEST) == "heads"
    assert migrate_target(Profile.DEV) == "app@head"
    assert migrate_target(Profile.DEMO) == "app@head"


def test_orphan_keys_are_destination_keys_without_a_matching_grant_hash() -> None:
    a, b, c = UUID(int=1), UUID(int=2), UUID(int=3)
    keys = [(a, "h1"), (b, "h2"), (c, "h3")]
    grants = {(a, "h1"), (b, "other-hash")}
    assert orphan_keys(keys, grants) == [(b, "h2"), (c, "h3")]
    assert orphan_keys([], grants) == []
```

Run: `uv run python -m pytest tests/plan_e/test_skeleton_cli.py -q` → FAIL (`ImportError: cannot import name 'migrate_target'`).

- [ ] **Step 2: Extend `scripts/skeleton.py`**

Replace the module docstring, the imports block's `from ops_core import settings` line and everything from `def ensure_incident_role` through `def migrate()` with:

```python
"""Walking-skeleton operations (T08, T09, T10): `migrate` both databases, `up`/`down`/`status` the five processes,
`keys` the destination-vs-grant detective check.

Reads `.env` (written by scripts/bootstrap_dev.py) for ports and the secrets directory, exports the `OPS_*` variables
every service reads (ops_core.settings), and runs the two Alembic trees programmatically with a shared connection
(Alembic cookbook: "Sharing a Connection across one or more programmatic migration commands"); the engine is built
from a `URL` object, so the password is never rendered into a string. Roles and their passwords are a bootstrap
concern, schema and grants are the migrations' (SA:395): every AM-20.1 login role is created or re-keyed from its
secret file on each run, the NOLOGIN owner roles are created, and database CONNECT is narrowed to the roles that use
each database, all before Alembic runs. The profile picks the Alembic target: only the test profile applies the
`testclock` branch (SA:529), and `up` refuses to start the dev skeleton against a database that carries it.
"""
```

```python
from ops_core import privileges, settings
from ops_core.settings import Profile, Role
from psycopg import sql
```

```python
NOLOGIN_ROLES: tuple[tuple[str, bool], ...] = (("migrator", True), ("app_definer", False), ("incident_owner", False))
TEST_ONLY_ROLES: frozenset[Role] = frozenset(Role(r) for r in privileges.TEST_ONLY_ROLES)  # SA:403; one source


def login_roles(profile: Profile) -> tuple[Role, ...]:
    """The AM-20.1 login roles a profile has: every role, or every role but the test harness."""
    return tuple(r for r in Role if profile is Profile.TEST or r not in TEST_ONLY_ROLES)


def ensure_login_role(conn: psycopg.Connection[object], name: str, password: str) -> None:
    """CREATE or re-key one LOGIN role with its secret file's value; idempotent so `migrate` can be re-run."""
    # Utility statements take no bind parameters, so the name and password travel through session settings and
    # format(%I/%L) quotes them server-side; neither appears in a Python-built SQL string.
    conn.execute(
        "SELECT set_config('ops.role_name', %s, false), set_config('ops.role_password', %s, false)", (name, password)
    )
    try:
        # A failing EXECUTE would carry the formatted statement, password included, in its CONTEXT (measured in the
        # round-1 review); the handler re-raises a message that names only the role, with the original SQLSTATE.
        conn.execute(
            """
            DO $$
            BEGIN
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = current_setting('ops.role_name')) THEN
                        EXECUTE format('CREATE ROLE %I LOGIN PASSWORD %L',
                                       current_setting('ops.role_name'), current_setting('ops.role_password'));
                    ELSE
                        EXECUTE format('ALTER ROLE %I LOGIN PASSWORD %L',
                                       current_setting('ops.role_name'), current_setting('ops.role_password'));
                    END IF;
                EXCEPTION WHEN OTHERS THEN
                    RAISE EXCEPTION 'role bootstrap failed for %', current_setting('ops.role_name') USING ERRCODE = SQLSTATE;
                END;
            END
            $$
            """
        )
    finally:
        conn.execute("SELECT set_config('ops.role_name', '', false), set_config('ops.role_password', '', false)")


def ensure_nologin_role(conn: psycopg.Connection[object], name: str, bypassrls: bool) -> None:
    """CREATE a NOLOGIN role (owner or definer) and pin its BYPASSRLS attribute either way."""
    conn.execute("SELECT set_config('ops.role_name', %s, false)", (name,))
    conn.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = current_setting('ops.role_name')) THEN
                EXECUTE format('CREATE ROLE %I NOLOGIN', current_setting('ops.role_name'));
            END IF;
        END
        $$
        """
    )
    attribute = sql.SQL("BYPASSRLS") if bypassrls else sql.SQL("NOBYPASSRLS")
    conn.execute(sql.SQL("ALTER ROLE {} {}").format(sql.Identifier(name), attribute))
    conn.execute("SELECT set_config('ops.role_name', '', false)")


def narrow_connect(conn: psycopg.Connection[object], database: str, roles: tuple[str, ...]) -> None:
    """Only the named roles may connect to `database` (BS:246; spike §3 measured the revoke on `incident`)."""
    conn.execute(sql.SQL("REVOKE CONNECT ON DATABASE {} FROM PUBLIC").format(sql.Identifier(database)))
    grantees = sql.SQL(", ").join(sql.Identifier(r) for r in roles)
    conn.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(database), grantees))


def ensure_roles(superuser: settings.Postgres, app_db: str, incident_db: str, profile: Profile) -> None:
    """Every AM-20.1 role of the profile with its password and CONNECT, before any migration runs (ruling 3)."""
    roles = login_roles(profile)
    with psycopg.connect(superuser.conninfo(), autocommit=True) as conn:
        for name, bypassrls in NOLOGIN_ROLES:
            ensure_nologin_role(conn, name, bypassrls)
        for role in roles:
            ensure_login_role(conn, role.value, settings.read_secret(settings.secret_name(role)))
        ensure_login_role(conn, "incident", settings.read_secret("postgres_incident_password"))
        narrow_connect(conn, app_db, tuple(r.value for r in roles))
        narrow_connect(conn, incident_db, ("incident",))


def _config(tree: str, connection: object) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS[tree]))
    cfg.attributes["connection"] = connection
    return cfg


def _engine(pg: settings.Postgres) -> Engine:
    url = URL.create(
        "postgresql+psycopg", username=pg.user, password=pg.password, host=pg.host, port=pg.port, database=pg.dbname
    )
    return create_engine(url)


def upgrade(tree: str, pg: settings.Postgres, target: str) -> None:
    """Upgrade one tree to `target` (`app@head`, `heads`, or a revision id) inside one transaction."""
    engine = _engine(pg)
    with engine.begin() as connection:
        command.upgrade(_config(tree, connection), target)
    engine.dispose()


def downgrade(tree: str, pg: settings.Postgres, target: str) -> None:
    """Downgrade one tree to `target` (a revision id, `<label>@base` or `base`); R006's up/down evidence."""
    engine = _engine(pg)
    with engine.begin() as connection:
        command.downgrade(_config(tree, connection), target)
    engine.dispose()


def migrate_target(profile: Profile) -> str:
    """`heads` applies the labelled `testclock` branch too; every other profile stops at the `app` main line."""
    return "heads" if profile is Profile.TEST else "app@head"


def migrate(profile: Profile | None = None) -> int:
    """Roles first, then both trees; the profile (default: `PROFILE`, else dev) decides whether the test clock exists."""
    export_environment(load_dotenv(ROOT / ".env"))
    profile = profile or settings.profile()
    superuser = settings.superuser_postgres()
    incident_db = settings.env("OPS_INCIDENT_PG_DB", "incident")
    incident_as_superuser = settings.Postgres(superuser.host, superuser.port, superuser.user, incident_db, superuser.password)
    ensure_roles(superuser, superuser.dbname, incident_db, profile)
    target = migrate_target(profile)
    upgrade("app", superuser, target)
    upgrade("incident", incident_as_superuser, "head")
    print(f"MIGRATE: app at {target}, incident at head (profile {profile.value})")
    return 0


def clock_guard(superuser: settings.Postgres, profile: Profile) -> None:
    """Refuse to run the dev or demo skeleton against a database that carries app.test_clock (SA:529)."""
    if profile is Profile.TEST:
        return
    with psycopg.connect(superuser.conninfo(), autocommit=True) as conn:
        row = conn.execute("SELECT to_regclass('app.test_clock') IS NOT NULL").fetchone()
    if row is not None and row[0]:
        raise RuntimeError(f"app.test_clock exists in {superuser.dbname}; the {profile.value} profile refuses to start")


def orphan_keys(
    keys: list[tuple[UUID, str]], grants: set[tuple[UUID, str]]
) -> list[tuple[UUID, str]]:
    """Destination keys whose (action_id, payload_sha256) no execution grant carries (T10 review note 3)."""
    return [key for key in keys if key not in grants]


def keys() -> int:
    """The detective check: every incident.action_key must match a grant hash; exit 1 and list the ones that do not."""
    export_environment(load_dotenv(ROOT / ".env"))
    superuser = settings.superuser_postgres()
    incident_db = settings.env("OPS_INCIDENT_PG_DB", "incident")
    destination = settings.Postgres(superuser.host, superuser.port, superuser.user, incident_db, superuser.password)
    with psycopg.connect(superuser.conninfo(), autocommit=True) as app_conn:
        grants = {(row[0], row[1]) for row in app_conn.execute("SELECT action_id, payload_sha256 FROM app.execution_grant")}
    with psycopg.connect(destination.conninfo(), autocommit=True) as dest_conn:
        found = [(row[0], row[1]) for row in dest_conn.execute("SELECT action_id, payload_sha256 FROM incident.action_key")]
    orphans = orphan_keys(found, grants)
    print(f"KEYS: {len(found)} destination keys, {len(grants)} grants, {len(orphans)} without a matching grant hash")
    for action_id, digest in orphans:
        print(f"  orphan action_id={action_id} payload_sha256={digest}")
    return 1 if orphans else 0
```

Add `from sqlalchemy.engine import URL, Engine` (replacing the `URL` import) and `from uuid import UUID` to the imports. In `process_environment()`, add to the `setdefault` block:

```python
    env.setdefault("PROFILE", Profile.DEV.value)
    env.setdefault("OPS_PG_DB", "ops")
    env.setdefault("OPS_INCIDENT_PG_DB", "incident")
```

In `up()`, as its first statements (before the pids check, so `.env` is loaded before any setting is read):

```python
    export_environment(load_dotenv(ROOT / ".env"))
    try:
        clock_guard(settings.superuser_postgres(), settings.profile())
    except (RuntimeError, settings.SettingsError) as error:
        print(f"UP: refused — {error}")
        return 2
```

In `main()`, `commands = {"migrate": migrate, "up": up, "down": down, "status": status, "keys": keys}` and the `__doc__` usage lines gain `keys`. Note `migrate` is called with no argument from the CLI (profile from the environment).

- [ ] **Step 3: Run the CLI tests**

Run: `uv run python -m pytest tests/plan_e/test_skeleton_cli.py -q` → PASS.

- [ ] **Step 4: Label revision 0001 and write revision 0002**

In `migrations/app/versions/0001_walking_skeleton.py` set `branch_labels = ("app",)` and add to the docstring: "Carries the `app` branch label so `migrate` can name the main line (`app@head`) while the `testclock` branch stays test-only (spike §4)."

Create `migrations/app/versions/0002_roles_grants_rls.py`:

```python
"""Roles, grants and row-level security (T09; AM-20.1, AM-20.2, AM-20.5, AM-20.6): the columns and tables AM-20
needs, ownership to `migrator`, the grant matrix from ops_core.privileges, forced RLS with the NULLIF policy, and
app.current_time().

Revision ID: 0002_roles_grants_rls
Revises: 0001_walking_skeleton

Runs as the Compose superuser (Plan E ruling 3): scripts/skeleton.py ensure_roles has created every role, so this
revision only alters, transfers and grants. Each statement is one op.execute string and the PL/pgSQL body is never
split (spike §4). The backfills read through the parents (runs, proposals, execution_grant, action_attempt) before
the NOT NULL and the composite keys are added, so an existing revision-1 database upgrades in place (R006).
"""

from __future__ import annotations

import re

from alembic import op
from ops_core import privileges
from ops_core.states import TRANSITIONS

revision = "0002_roles_grants_rls"
down_revision = "0001_walking_skeleton"
branch_labels = None
depends_on = None

ACTIVE = (
    "'QUEUED','AWAITING_INPUT','RETRIEVING','DRAFTING','AWAITING_APPROVAL','APPROVED','EXECUTING','OUTCOME_UNKNOWN'"
)
# The tables that exist after this revision, as literals: an applied revision must not change when a later task
# adds a row to the live matrix (round-2 finding NI5); each later revision renders the statements for the tables it
# creates or changes. test_clock belongs to the testclock branch.
TABLES = (
    "tenants",
    "memberships",
    "sessions",
    "conversations",
    "messages",
    "runs",
    "run_directory",
    "run_state_history",
    "run_lease",
    "jobs",
    "invocation_context",
    "drafts",
    "proposals",
    "decisions",
    "execution_grant",
    "action_attempt",
    "action_attempt_state",
    "events",
    "transitions",
)
RLS = (
    "memberships",
    "conversations",
    "messages",
    "runs",
    "run_state_history",
    "jobs",
    "drafts",
    "proposals",
    "decisions",
    "execution_grant",
    "action_attempt",
    "action_attempt_state",
    "events",
)
_WORD = re.compile(r"^[A-Za-z_]+$")

SCHEMA_CHANGES = (
    # runs: the slot flag (SA:451), the event counter (SA:439) and the columns the AM-20.2 grants name.
    "ALTER TABLE app.runs"
    " ADD COLUMN slot_held boolean NOT NULL DEFAULT false,"
    " ADD COLUMN next_event_seq integer NOT NULL DEFAULT 0,"
    " ADD COLUMN cancel_requested_at timestamptz,"
    " ADD COLUMN checkpoint_id text,"
    " ADD COLUMN budget_used integer NOT NULL DEFAULT 0",
    f"UPDATE app.runs r SET slot_held = (r.state IN ({ACTIVE})),"
    " next_event_seq = COALESCE((SELECT max(e.sequence) FROM app.events e WHERE e.run_id = r.run_id), 0)",
    "DROP INDEX app.runs_one_active_per_conversation",
    "CREATE UNIQUE INDEX runs_one_active_per_conversation ON app.runs (conversation_id) WHERE slot_held",
    # R009: every child references its parent through the tenant.
    "ALTER TABLE app.messages ADD CONSTRAINT messages_tenant_message_key UNIQUE (tenant_id, message_id)",
    "ALTER TABLE app.runs DROP CONSTRAINT runs_message_id_fkey",
    "ALTER TABLE app.runs ADD CONSTRAINT runs_tenant_message_fkey"
    " FOREIGN KEY (tenant_id, message_id) REFERENCES app.messages (tenant_id, message_id)",
    "ALTER TABLE app.run_state_history ADD COLUMN tenant_id uuid",
    "UPDATE app.run_state_history h SET tenant_id = r.tenant_id FROM app.runs r WHERE r.run_id = h.run_id",
    "ALTER TABLE app.run_state_history ALTER COLUMN tenant_id SET NOT NULL,"
    " DROP CONSTRAINT run_state_history_run_id_fkey,"
    " ADD CONSTRAINT run_state_history_tenant_run_fkey"
    " FOREIGN KEY (tenant_id, run_id) REFERENCES app.runs (tenant_id, run_id)",
    # jobs: tenant nullable (sweeper jobs have none, SA:504) and run_id nullable for the same reason.
    "ALTER TABLE app.jobs ADD COLUMN tenant_id uuid",
    "UPDATE app.jobs j SET tenant_id = r.tenant_id FROM app.runs r WHERE r.run_id = j.run_id",
    "ALTER TABLE app.jobs ALTER COLUMN run_id DROP NOT NULL,"
    " DROP CONSTRAINT jobs_run_id_fkey,"
    " ADD CONSTRAINT jobs_tenant_run_fkey FOREIGN KEY (tenant_id, run_id) REFERENCES app.runs (tenant_id, run_id),"
    " ADD CONSTRAINT jobs_tenant_iff_run_check CHECK ((run_id IS NULL) = (tenant_id IS NULL))",
    "ALTER TABLE app.drafts ADD COLUMN tenant_id uuid",
    "UPDATE app.drafts d SET tenant_id = r.tenant_id FROM app.runs r WHERE r.run_id = d.run_id",
    "ALTER TABLE app.drafts ALTER COLUMN tenant_id SET NOT NULL,"
    " DROP CONSTRAINT drafts_run_id_fkey,"
    " ADD CONSTRAINT drafts_tenant_run_fkey FOREIGN KEY (tenant_id, run_id) REFERENCES app.runs (tenant_id, run_id),"
    " ADD CONSTRAINT drafts_tenant_id_key UNIQUE (tenant_id, id)",
    "ALTER TABLE app.proposals DROP CONSTRAINT proposals_run_id_fkey, DROP CONSTRAINT proposals_draft_id_fkey,"
    " ADD CONSTRAINT proposals_tenant_run_fkey FOREIGN KEY (tenant_id, run_id) REFERENCES app.runs (tenant_id, run_id),"
    " ADD CONSTRAINT proposals_tenant_draft_fkey FOREIGN KEY (tenant_id, draft_id) REFERENCES app.drafts (tenant_id, id),"
    " ADD CONSTRAINT proposals_tenant_proposal_key UNIQUE (tenant_id, proposal_id)",
    "ALTER TABLE app.decisions ADD COLUMN tenant_id uuid, ADD COLUMN idempotency_key text",
    "UPDATE app.decisions d SET tenant_id = p.tenant_id FROM app.proposals p WHERE p.proposal_id = d.proposal_id",
    "ALTER TABLE app.decisions ALTER COLUMN tenant_id SET NOT NULL,"
    " DROP CONSTRAINT decisions_proposal_id_fkey,"
    " ADD CONSTRAINT decisions_tenant_proposal_fkey"
    " FOREIGN KEY (tenant_id, proposal_id) REFERENCES app.proposals (tenant_id, proposal_id)",
    "ALTER TABLE app.execution_grant ADD COLUMN tenant_id uuid",
    "UPDATE app.execution_grant g SET tenant_id = r.tenant_id FROM app.runs r WHERE r.run_id = g.run_id",
    "ALTER TABLE app.execution_grant ALTER COLUMN tenant_id SET NOT NULL,"
    " DROP CONSTRAINT execution_grant_run_id_fkey, DROP CONSTRAINT execution_grant_proposal_id_fkey,"
    " ADD CONSTRAINT execution_grant_tenant_run_fkey"
    " FOREIGN KEY (tenant_id, run_id) REFERENCES app.runs (tenant_id, run_id),"
    " ADD CONSTRAINT execution_grant_tenant_proposal_fkey"
    " FOREIGN KEY (tenant_id, proposal_id) REFERENCES app.proposals (tenant_id, proposal_id),"
    " ADD CONSTRAINT execution_grant_tenant_action_key UNIQUE (tenant_id, action_id)",
    "ALTER TABLE app.action_attempt ADD COLUMN tenant_id uuid",
    "UPDATE app.action_attempt a SET tenant_id = g.tenant_id FROM app.execution_grant g WHERE g.action_id = a.action_id",
    "ALTER TABLE app.action_attempt ALTER COLUMN tenant_id SET NOT NULL,"
    " DROP CONSTRAINT action_attempt_action_id_fkey,"
    " ADD CONSTRAINT action_attempt_tenant_action_fkey"
    " FOREIGN KEY (tenant_id, action_id) REFERENCES app.execution_grant (tenant_id, action_id),"
    " ADD CONSTRAINT action_attempt_tenant_attempt_key UNIQUE (tenant_id, action_id, attempt_no)",
    "ALTER TABLE app.action_attempt_state ADD COLUMN tenant_id uuid",
    "UPDATE app.action_attempt_state s SET tenant_id = a.tenant_id FROM app.action_attempt a"
    " WHERE a.action_id = s.action_id AND a.attempt_no = s.attempt_no",
    "ALTER TABLE app.action_attempt_state ALTER COLUMN tenant_id SET NOT NULL,"
    " DROP CONSTRAINT action_attempt_state_action_id_attempt_no_fkey,"
    " ADD CONSTRAINT action_attempt_state_tenant_attempt_fkey"
    " FOREIGN KEY (tenant_id, action_id, attempt_no) REFERENCES app.action_attempt (tenant_id, action_id, attempt_no)",
    "ALTER TABLE app.events DROP CONSTRAINT events_run_id_fkey,"
    " ADD CONSTRAINT events_tenant_run_fkey FOREIGN KEY (tenant_id, run_id) REFERENCES app.runs (tenant_id, run_id)",
    # Handles are 60-second capabilities: nothing in the table is worth keeping, so the raw column is replaced
    # by its hash (SA:496, BS:360) on an empty table.
    "TRUNCATE app.invocation_context",
    "ALTER TABLE app.invocation_context DROP COLUMN handle",
    "ALTER TABLE app.invocation_context ADD COLUMN handle_sha256 text PRIMARY KEY, ALTER COLUMN fence TYPE bigint",
    # RLS-free bootstrap tables (SA:523): the directory the functions resolve a tenant through, the lease (T13 fills
    # it), the session store (T11 fills it), and the T07 transition table mirrored as data (ruling 10).
    "CREATE TABLE app.run_directory ("
    " run_id uuid PRIMARY KEY REFERENCES app.runs (run_id),"
    " tenant_id uuid NOT NULL REFERENCES app.tenants (tenant_id))",
    "INSERT INTO app.run_directory (run_id, tenant_id) SELECT run_id, tenant_id FROM app.runs",
    "CREATE TABLE app.run_lease ("
    " run_id uuid PRIMARY KEY REFERENCES app.runs (run_id),"
    " owner text NOT NULL,"
    " lease_until timestamptz NOT NULL,"
    " fence bigint NOT NULL DEFAULT 1)",
    "CREATE TABLE app.sessions ("
    " session_sha256 text PRIMARY KEY,"
    " issuer text NOT NULL,"
    " subject uuid NOT NULL,"
    " tenant_id uuid NOT NULL REFERENCES app.tenants (tenant_id),"
    " csrf_secret_sha256 text NOT NULL,"
    " created_at timestamptz NOT NULL DEFAULT now(),"
    " expires_at timestamptz NOT NULL,"
    " last_seen_at timestamptz NOT NULL DEFAULT now(),"
    " revoked_at timestamptz)",
    "CREATE TABLE app.transitions ("
    " src text NOT NULL,"
    " dst text NOT NULL,"
    " performer text NOT NULL,"
    " reasons text[] NOT NULL,"
    " PRIMARY KEY (src, dst, performer))",
)

OWNERSHIP = (
    "ALTER SCHEMA app OWNER TO migrator",
    # Tables, sequences and views alike: ALTER TABLE ... OWNER TO accepts all three relkinds.
    """
    DO $own$
    DECLARE
        r record;
    BEGIN
        FOR r IN SELECT c.oid::regclass AS rel FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                 WHERE n.nspname = 'app' AND c.relkind IN ('r', 'S', 'v')
        LOOP
            EXECUTE format('ALTER TABLE %s OWNER TO migrator', r.rel);
        END LOOP;
    END
    $own$
    """,
)

CURRENT_TIME = """
CREATE OR REPLACE FUNCTION app.current_time() RETURNS timestamptz
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = app, pg_temp SET app.tenant_id = '' AS $fn$
DECLARE
    v_offset interval;
BEGIN
    -- The table exists only where the testclock branch is applied, so the reference is dynamic (SA:528), and no
    -- GUC is consulted anywhere: a SET cannot move the clock (R126). Owned by app_definer so the read of
    -- test_clock uses its grant and no caller needs one (Plan E ruling 17).
    IF to_regclass('app.test_clock') IS NULL THEN
        RETURN clock_timestamp();
    END IF;
    EXECUTE 'SELECT clock_offset FROM app.test_clock LIMIT 1' INTO v_offset;
    RETURN clock_timestamp() + coalesce(v_offset, interval '0');
END
$fn$;
ALTER FUNCTION app.current_time() OWNER TO app_definer;
"""


def transition_rows() -> list[str]:
    """One INSERT per T07 row; the values are enum members, checked against a word pattern before they are quoted."""
    out: list[str] = []
    for row in TRANSITIONS:
        src = row.src.value if row.src is not None else ""
        parts = [src, row.dst.value, row.performer.value, *sorted(r.value for r in row.reasons)]
        if any(part and not _WORD.match(part) for part in parts):
            raise RuntimeError("transition table values must be plain words")
        reasons = ", ".join(f"'{r}'" for r in parts[3:])
        array = f"ARRAY[{reasons}]::text[]" if reasons else "ARRAY[]::text[]"
        out.append(
            f"INSERT INTO app.transitions (src, dst, performer, reasons) VALUES ('{src}', '{parts[1]}', '{parts[2]}', {array})"
        )
    return out


def upgrade() -> None:
    for statement in SCHEMA_CHANGES:
        op.execute(statement)
    for statement in transition_rows():
        op.execute(statement)
    for statement in OWNERSHIP:
        op.execute(statement)
    for statement in privileges.schema_usage_statements():  # the main-line grantees; test_harness is the branch's
        op.execute(statement)
    for statement in privileges.grant_statements(TABLES):
        op.execute(statement)
    for statement in privileges.rls_statements(RLS):
        op.execute(statement)
    op.execute(CURRENT_TIME)
    for statement in privileges.function_grant_statements("current_time", roles=privileges.MAIN_ROLES):
        op.execute(statement)


DOWNGRADE = (
    "DROP FUNCTION app.current_time()",
    *[f"DROP POLICY IF EXISTS sweeper_all ON app.{t}" for t in ("memberships", "jobs")],
    *[f"DROP POLICY IF EXISTS tenant_isolation ON app.{t}" for t in RLS],
    *[f"ALTER TABLE app.{t} NO FORCE ROW LEVEL SECURITY, DISABLE ROW LEVEL SECURITY" for t in RLS],
    f"REVOKE ALL ON ALL TABLES IN SCHEMA app FROM {', '.join(privileges.MAIN_GRANTEES)}",
    f"REVOKE USAGE ON SCHEMA app FROM {', '.join(privileges.MAIN_GRANTEES)}",
    "DROP TABLE app.transitions",
    "DROP TABLE app.sessions",
    "DROP TABLE app.run_lease",
    "DROP TABLE app.run_directory",
    "TRUNCATE app.invocation_context",
    "ALTER TABLE app.invocation_context DROP COLUMN handle_sha256, ALTER COLUMN fence TYPE integer",
    "ALTER TABLE app.invocation_context ADD COLUMN handle text PRIMARY KEY",
    "ALTER TABLE app.events DROP CONSTRAINT events_tenant_run_fkey,"
    " ADD CONSTRAINT events_run_id_fkey FOREIGN KEY (run_id) REFERENCES app.runs (run_id)",
    "ALTER TABLE app.action_attempt_state DROP CONSTRAINT action_attempt_state_tenant_attempt_fkey,"
    " ADD CONSTRAINT action_attempt_state_action_id_attempt_no_fkey"
    " FOREIGN KEY (action_id, attempt_no) REFERENCES app.action_attempt (action_id, attempt_no),"
    " DROP COLUMN tenant_id",
    "ALTER TABLE app.action_attempt DROP CONSTRAINT action_attempt_tenant_attempt_key,"
    " DROP CONSTRAINT action_attempt_tenant_action_fkey,"
    " ADD CONSTRAINT action_attempt_action_id_fkey FOREIGN KEY (action_id) REFERENCES app.execution_grant (action_id),"
    " DROP COLUMN tenant_id",
    "ALTER TABLE app.execution_grant DROP CONSTRAINT execution_grant_tenant_action_key,"
    " DROP CONSTRAINT execution_grant_tenant_run_fkey, DROP CONSTRAINT execution_grant_tenant_proposal_fkey,"
    " ADD CONSTRAINT execution_grant_run_id_fkey FOREIGN KEY (run_id) REFERENCES app.runs (run_id),"
    " ADD CONSTRAINT execution_grant_proposal_id_fkey FOREIGN KEY (proposal_id) REFERENCES app.proposals (proposal_id),"
    " DROP COLUMN tenant_id",
    "ALTER TABLE app.decisions DROP CONSTRAINT decisions_tenant_proposal_fkey,"
    " ADD CONSTRAINT decisions_proposal_id_fkey FOREIGN KEY (proposal_id) REFERENCES app.proposals (proposal_id),"
    " DROP COLUMN tenant_id, DROP COLUMN idempotency_key",
    "ALTER TABLE app.proposals DROP CONSTRAINT proposals_tenant_proposal_key,"
    " DROP CONSTRAINT proposals_tenant_run_fkey, DROP CONSTRAINT proposals_tenant_draft_fkey,"
    " ADD CONSTRAINT proposals_run_id_fkey FOREIGN KEY (run_id) REFERENCES app.runs (run_id),"
    " ADD CONSTRAINT proposals_draft_id_fkey FOREIGN KEY (draft_id) REFERENCES app.drafts (id)",
    "ALTER TABLE app.drafts DROP CONSTRAINT drafts_tenant_run_fkey, DROP CONSTRAINT drafts_tenant_id_key,"
    " ADD CONSTRAINT drafts_run_id_fkey FOREIGN KEY (run_id) REFERENCES app.runs (run_id), DROP COLUMN tenant_id",
    "DELETE FROM app.jobs WHERE run_id IS NULL",
    "ALTER TABLE app.jobs DROP CONSTRAINT jobs_tenant_run_fkey, DROP CONSTRAINT jobs_tenant_iff_run_check,"
    " ADD CONSTRAINT jobs_run_id_fkey FOREIGN KEY (run_id) REFERENCES app.runs (run_id),"
    " ALTER COLUMN run_id SET NOT NULL, DROP COLUMN tenant_id",
    "ALTER TABLE app.run_state_history DROP CONSTRAINT run_state_history_tenant_run_fkey,"
    " ADD CONSTRAINT run_state_history_run_id_fkey FOREIGN KEY (run_id) REFERENCES app.runs (run_id),"
    " DROP COLUMN tenant_id",
    "ALTER TABLE app.runs DROP CONSTRAINT runs_tenant_message_fkey,"
    " ADD CONSTRAINT runs_message_id_fkey FOREIGN KEY (message_id) REFERENCES app.messages (message_id)",
    "ALTER TABLE app.messages DROP CONSTRAINT messages_tenant_message_key",
    "DROP INDEX app.runs_one_active_per_conversation",
    f"CREATE UNIQUE INDEX runs_one_active_per_conversation ON app.runs (conversation_id) WHERE state IN ({ACTIVE})",
    "ALTER TABLE app.runs DROP COLUMN slot_held, DROP COLUMN next_event_seq, DROP COLUMN cancel_requested_at,"
    " DROP COLUMN checkpoint_id, DROP COLUMN budget_used",
    "ALTER SCHEMA app OWNER TO CURRENT_USER",
    """
    DO $own$
    DECLARE
        r record;
    BEGIN
        FOR r IN SELECT c.oid::regclass AS rel FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                 WHERE n.nspname = 'app' AND c.relkind IN ('r', 'S', 'v')
        LOOP
            EXECUTE format('ALTER TABLE %s OWNER TO CURRENT_USER', r.rel);
        END LOOP;
    END
    $own$
    """,
)


def downgrade() -> None:
    for statement in DOWNGRADE:
        op.execute(statement)
```

Notes for the implementer: write every multi-line element of `SCHEMA_CHANGES`, `OWNERSHIP` and `DOWNGRADE` inside its own parentheses (ruff ISC004 is not auto-fixed); the composite-key downgrade exists for R006's up/down proof on a test database; a dev database is never downgraded. The constraint names dropped here are the ones PostgreSQL generated for revision 1 (verified against `pg_constraint` in the round-1 review): `runs_message_id_fkey`, `run_state_history_run_id_fkey`, `jobs_run_id_fkey`, `drafts_run_id_fkey`, `proposals_run_id_fkey`, `proposals_draft_id_fkey`, `decisions_proposal_id_fkey`, `execution_grant_run_id_fkey`, `execution_grant_proposal_id_fkey`, `action_attempt_action_id_fkey`, `action_attempt_state_action_id_attempt_no_fkey`, `events_run_id_fkey`.

- [ ] **Step 5: Write the `testclock` branch**

Create `migrations/app/versions/tc_0001_test_clock.py`:

```python
"""The test clock (AM-20.6, R126): exists only where this branch is applied, which `scripts/skeleton.py migrate`
does for the test profile alone (`heads`); dev and demo stop at `app@head` and refuse to start if the table exists.

Revision ID: tc_0001_test_clock
Revises: (own root; depends on 0002_roles_grants_rls)
Branch label: testclock

A single-row table (the `one` column admits exactly one row) so `test_harness` can UPDATE without a WHERE clause and
needs no SELECT grant (AM-20.2 gives it ins, upd, del only; spike §3). app.current_time() reads it as app_definer.
"""

from alembic import op
from ops_core import privileges

revision = "tc_0001_test_clock"
down_revision = None
branch_labels = ("testclock",)
depends_on = "0002_roles_grants_rls"

DDL = (
    "CREATE TABLE app.test_clock ("
    " one boolean NOT NULL DEFAULT true PRIMARY KEY CHECK (one),"
    " clock_offset interval NOT NULL DEFAULT interval '0')",
    "ALTER TABLE app.test_clock OWNER TO migrator",
    "INSERT INTO app.test_clock (clock_offset) VALUES (interval '0')",
)


def upgrade() -> None:
    for statement in DDL:
        op.execute(statement)
    # The test-only role gets its schema access and its clock EXECUTE here, never on the main line (SA:403).
    for statement in privileges.schema_usage_statements(privileges.TEST_ONLY_ROLES):
        op.execute(statement)
    for statement in privileges.function_grant_statements("current_time", roles=privileges.TEST_ONLY_ROLES):
        op.execute(statement)
    for statement in privileges.grant_statements(["test_clock"]):
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE app.test_clock")
    op.execute(f"REVOKE ALL ON FUNCTION app.current_time() FROM {', '.join(privileges.TEST_ONLY_ROLES)}")
    op.execute(f"REVOKE USAGE ON SCHEMA app FROM {', '.join(privileges.TEST_ONLY_ROLES)}")
```

- [ ] **Step 6: Rewrite the e2e fixtures for per-session databases**

Replace `tests/e2e/conftest.py` from the module docstring through the `app_conn` fixture with:

```python
"""Live fixtures: only with OPS_LIVE=1 and the dev profile up. Secrets are read from files, never printed.

Every live test runs against two per-session databases, `ops_test` and `incident_test`, dropped and recreated here and
migrated under the test profile (so `app.test_clock` exists in them and never in the dev `ops` database, SA:529);
the skeleton processes the R105 module starts inherit the same environment. Seeding and clean-up use the superuser
connection (`app_conn`); assertions about what a role may do use `role_conn`.
"""

import asyncio
import os
import sys
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path

import psycopg
import pytest
import pytest_asyncio
from ops_core import persistence, settings
from ops_core.settings import Profile, Role
from psycopg import sql

if sys.platform == "win32":
    # psycopg async refuses the Proactor loop, and Python's default policy on Windows (and uvicorn.run) picks it
    # (measured in the Plan D spike and its round-1 review). pytest-asyncio builds its loops from the policy, so the
    # selector policy is installed once, here, for every live test on the Windows dev machine.
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

ROOT = Path(__file__).resolve().parent.parent.parent
TEST_DATABASES = {"OPS_PG_DB": "ops_test", "OPS_INCIDENT_PG_DB": "incident_test"}


@pytest.fixture(scope="session")
def live() -> None:
    if os.environ.get("OPS_LIVE") != "1":
        pytest.skip("live walking-skeleton tests run only with OPS_LIVE=1")


@pytest.fixture(scope="session")
def env(live: None) -> dict[str, str]:
    sys.path.insert(0, str(ROOT))
    from scripts.skeleton import export_environment, load_dotenv

    # Before anything reads settings: the per-session databases and the test profile, inherited by child processes.
    os.environ.update(TEST_DATABASES)
    os.environ["PROFILE"] = Profile.TEST.value
    dotenv = load_dotenv(ROOT / ".env")
    export_environment(dotenv)
    return dotenv


@pytest.fixture(scope="session")
def secret(env: dict[str, str]) -> Callable[[str], str]:
    return lambda name: settings.read_secret(name)


def recreate_databases() -> None:
    """Drop and create both test databases from the maintenance database; FORCE ends any leftover session."""
    admin = settings.superuser_postgres()
    maintenance = settings.Postgres(admin.host, admin.port, admin.user, "postgres", admin.password)
    with psycopg.connect(maintenance.conninfo(), autocommit=True) as conn:
        for name in TEST_DATABASES.values():
            conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))
            conn.execute(sql.SQL("CREATE DATABASE {} OWNER {}").format(sql.Identifier(name), sql.Identifier(admin.user)))


@pytest.fixture(scope="session")
def migrated(env: dict[str, str]) -> None:
    from scripts.skeleton import migrate

    recreate_databases()
    assert migrate(Profile.TEST) == 0


@pytest_asyncio.fixture
async def app_conn(migrated: None) -> AsyncIterator[persistence.Conn]:
    """The superuser on ops_test (bypasses RLS and grants): seeding, purging and catalog assertions. A test that must
    leave nothing behind wraps itself in `async with app_conn.transaction(force_rollback=True)`."""
    conn = await persistence.connect(settings.superuser_postgres())
    try:
        yield conn
    finally:
        await conn.close()


@pytest_asyncio.fixture
async def role_conn(migrated: None) -> AsyncIterator[Callable[[Role], Awaitable[persistence.Conn]]]:
    """A factory of autocommit connections as a runtime role; every connection it opened is closed afterwards."""
    opened: list[persistence.Conn] = []

    async def open_as(role: Role) -> persistence.Conn:
        conn = await persistence.connect(settings.app_postgres(role))
        opened.append(conn)
        return conn

    try:
        yield open_as
    finally:
        for conn in opened:
            await conn.close()


@pytest_asyncio.fixture
async def incident_conn(migrated: None) -> AsyncIterator[persistence.Conn]:
    """Role `incident` on incident_test, the destination's own credentials."""
    conn = await persistence.connect(settings.incident_postgres())
    try:
        yield conn
    finally:
        await conn.close()
```

Keep `PURGE_ORDER`, `purge_run`, `SEEDED_TENANTS` and `purge_tenant` as they are, but change `purge_run`'s docstring last sentence to: "This runs as the superuser on the per-session test database, so the grants do not apply; the database is dropped at the next session anyway." Add `"DELETE FROM app.run_directory WHERE run_id = %s"` as the last entry of `PURGE_ORDER` (the directory references `runs`).

Update `tests/e2e/test_migrations_and_persistence.py::test_migrate_is_idempotent_and_seeds_are_present` to call `migrate(Profile.TEST)` (import `Profile`) and add, in the same file:

```python
async def test_r006_fresh_database_upgrades_downgrades_and_upgrades_again(migrated: None, app_conn: persistence.Conn):
    """R006: both heads apply to an empty database, 0002 and the testclock branch come off cleanly, and come back."""
    from scripts.skeleton import downgrade, migrate

    superuser = settings.superuser_postgres()
    cur = await app_conn.execute("SELECT version_num FROM public.alembic_version ORDER BY 1")
    versions = {r["version_num"] for r in await cur.fetchall()}
    # With `depends_on` pointing at the main head, Alembic stores one row until a later main revision exists (round 1).
    assert "tc_0001_test_clock" in versions, versions
    downgrade("app", superuser, "testclock@base")
    downgrade("app", superuser, "0001_walking_skeleton")
    for relation in ("app.test_clock", "app.run_directory", "app.transitions"):
        cur = await app_conn.execute("SELECT to_regclass(%s) IS NULL AS gone", (relation,))
        assert (await cur.fetchone())["gone"], relation
    cur = await app_conn.execute("SELECT count(*) AS n FROM pg_policies WHERE schemaname = 'app'")
    assert (await cur.fetchone())["n"] == 0
    assert migrate(Profile.TEST) == 0
    cur = await app_conn.execute("SELECT version_num FROM public.alembic_version ORDER BY 1")
    assert {r["version_num"] for r in await cur.fetchall()} == versions
```

(`settings` is already imported there? If not, add `from ops_core import settings`.)

- [ ] **Step 7: Write the live role tests (R124, R084, R128 direct writes, R007, R008, R009, R106 policy text)**

Create `tests/e2e/test_roles_live.py`:

```python
"""Roles, grants and RLS against the per-session test database (OPS_LIVE=1): the catalogs enumerated against
ops_core.privileges (R124), function-only roles denied every SELECT (R084), direct writes to audit and state denied
(R128), tenant isolation through the policy for a runtime role (R007), no residual context on a reused connection
(R008), composite keys refusing cross-tenant children (R009), and the policy text per table (R106).

Catches: a grant the matrix does not list (or one it lists that the migration forgot), a policy with the bare
`::uuid` cast (spike §2), an owner that is not migrator, a definer role that owns a table, a table-level UPDATE
where only columns were meant, and a FOR UPDATE lock that a function-only role could take.
"""

from collections.abc import Awaitable, Callable
from uuid import UUID, uuid4

import psycopg
import pytest
from ops_core import persistence, privileges as p
from ops_core.settings import Role

from tests.e2e.conftest import purge_run

pytestmark = pytest.mark.asyncio

RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
ALPHA = UUID("3ea79c95-914c-52cb-9d10-c4e19dda8ff7")
BETA = UUID("5ab45c2c-1e12-5a0c-a2b9-66cd2ff05201")
ALEX = UUID("2fc05986-c7ec-544c-b628-fdb112bbf18a")


async def seed_run(app_conn: persistence.Conn, tenant: UUID) -> UUID:
    """A QUEUED run written by the superuser with plain INSERTs (revision 0002 shape): conversation, message, run,
    directory row and first history row. No persistence call: this module tests the schema, not the functions."""
    conv, msg, run = uuid4(), uuid4(), uuid4()
    await app_conn.execute(
        "INSERT INTO app.conversations (conversation_id, tenant_id, created_by) VALUES (%s, %s, %s)", (conv, tenant, ALEX)
    )
    await app_conn.execute(
        "INSERT INTO app.messages (message_id, tenant_id, conversation_id, kind, text, author)"
        " VALUES (%s, %s, %s, 'investigate', 'x', %s)",
        (msg, tenant, conv, ALEX),
    )
    await app_conn.execute(
        "INSERT INTO app.runs (run_id, tenant_id, conversation_id, message_id, requester, intent, asset_id, start_at,"
        " end_at, state, state_version, slot_held) VALUES (%s, %s, %s, %s, %s, 'investigate', 'A17',"
        " now() - interval '1 day', now(), 'QUEUED', 1, true)",
        (run, tenant, conv, msg, ALEX),
    )
    await app_conn.execute("INSERT INTO app.run_directory (run_id, tenant_id) VALUES (%s, %s)", (run, tenant))
    await app_conn.execute(
        "INSERT INTO app.run_state_history (tenant_id, run_id, seq, to_state, performer) VALUES (%s, %s, 1, 'QUEUED', 'seed')",
        (tenant, run),
    )
    return run


async def actual_privileges(conn: persistence.Conn) -> dict[tuple[str, str], set[tuple[str, str | None]]]:
    """What the catalogs say each grantee holds on each app table, in the matrix's (privilege, column) shape."""
    out: dict[tuple[str, str], set[tuple[str, str | None]]] = {}
    cur = await conn.execute(
        "SELECT grantee, table_name, privilege_type FROM information_schema.role_table_grants"
        " WHERE table_schema = 'app' AND grantee <> %s",
        (p.OWNER_ROLE,),
    )
    for row in await cur.fetchall():
        out.setdefault((row["grantee"], row["table_name"]), set()).add((row["privilege_type"], None))
    cur = await conn.execute(
        "SELECT grantee, table_name, column_name, privilege_type FROM information_schema.column_privileges"
        " WHERE table_schema = 'app' AND grantee <> %s AND privilege_type = 'UPDATE'",
        (p.OWNER_ROLE,),
    )
    for row in await cur.fetchall():
        key = (row["grantee"], row["table_name"])
        if ("UPDATE", None) not in out.get(key, set()):  # a table-level UPDATE already covers every column
            out.setdefault(key, set()).add(("UPDATE", row["column_name"]))
    return out


async def test_r124_every_grantee_holds_exactly_its_matrix_privileges(app_conn: persistence.Conn) -> None:
    actual = await actual_privileges(app_conn)
    expected = {(role, table): grant.privileges() for table, grants in p.GRANTS.items() for role, grant in grants.items()}
    assert actual == expected, {k: (actual.get(k), expected.get(k)) for k in set(actual) ^ set(expected) or actual}
    for privs in actual.values():
        assert {priv for priv, _ in privs} <= {"SELECT", "INSERT", "UPDATE", "DELETE"}
    cur = await app_conn.execute(
        "SELECT grantee, table_name FROM information_schema.role_table_grants WHERE table_schema = 'app' AND grantee = 'PUBLIC'"
    )
    assert await cur.fetchall() == []


async def test_owners_and_role_attributes(app_conn: persistence.Conn) -> None:
    cur = await app_conn.execute("SELECT tablename, tableowner FROM pg_tables WHERE schemaname = 'app'")
    owners = {r["tablename"]: r["tableowner"] for r in await cur.fetchall()}
    assert set(owners) == set(p.GRANTS) and set(owners.values()) == {p.OWNER_ROLE}, owners
    cur = await app_conn.execute(
        "SELECT rolname, rolsuper, rolbypassrls, rolcanlogin FROM pg_roles WHERE rolname = ANY(%s)",
        (list(p.GRANTEES) + [p.OWNER_ROLE, "incident", "incident_owner"],),
    )
    roles = {r["rolname"]: r for r in await cur.fetchall()}
    assert len(roles) == len(p.GRANTEES) + 3  # the test profile has every role, test_harness included
    assert roles[p.OWNER_ROLE]["rolbypassrls"] and not roles[p.OWNER_ROLE]["rolcanlogin"]
    for name, row in roles.items():
        assert not row["rolsuper"], name
        if name != p.OWNER_ROLE:
            assert not row["rolbypassrls"], name
        assert row["rolcanlogin"] == (name in p.RUNTIME_ROLES or name == "incident"), name
    cur = await app_conn.execute("SELECT nspowner::regrole::text AS owner FROM pg_namespace WHERE nspname = 'app'")
    assert (await cur.fetchone())["owner"] == p.OWNER_ROLE


async def test_r084_function_only_roles_cannot_read_or_lock_any_table(role_conn: RoleConn) -> None:
    for role in (Role.MCP_READ, Role.MCP_EXEC, Role.OPERATOR):
        conn = await role_conn(role)
        for table in p.GRANTS:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                await conn.execute(f"SELECT 1 FROM app.{table} LIMIT 1")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            await conn.execute("SELECT run_id FROM app.runs FOR UPDATE")
        cur = await conn.execute("SELECT app.current_time() IS NOT NULL AS ok")
        assert (await cur.fetchone())["ok"]  # the clock is the one thing a function-only role may call directly


async def test_r128_runtime_roles_cannot_write_state_or_audit_rows_directly(role_conn: RoleConn) -> None:
    denied = {
        "events": "INSERT INTO app.events (event_id, tenant_id, conversation_id, run_id, sequence, type, occurred_at,"
        " source, payload) VALUES (gen_random_uuid(), %s, %s, %s, 1, 'x', now(), 'application', '{}')",
        "decisions": "INSERT INTO app.decisions (decision_id, tenant_id, proposal_id, reviewer, decision,"
        " expected_payload_sha256) VALUES (gen_random_uuid(), %s, %s, %s, 'approve', 'h')",
        "proposals": "INSERT INTO app.proposals (proposal_id, tenant_id, run_id, revision, draft_id, payload,"
        " payload_canonical, payload_sha256, canonicalization_version, authored_by, expires_at)"
        " VALUES (gen_random_uuid(), %s, %s, 1, %s, '{}', '', 'h', 1, '{}', now())",
        "execution_grant": "INSERT INTO app.execution_grant (action_id, tenant_id, run_id, proposal_id, payload_sha256)"
        " VALUES (gen_random_uuid(), %s, %s, %s, 'h')",
        "action_attempt_state": "INSERT INTO app.action_attempt_state (tenant_id, action_id, attempt_no, seq, state)"
        " VALUES (%s, %s, 1, 1, 'INTENT')",
        "run_state_history": "INSERT INTO app.run_state_history (tenant_id, run_id, seq, from_state, to_state, performer)"
        " VALUES (%s, %s, 9, 'a', 'b', 'x')",
    }
    for role in (Role.API, Role.WORKER, Role.SWEEPER):
        conn = await role_conn(role)
        for table, statement in denied.items():
            params = (ALPHA, uuid4(), uuid4()) if statement.count("%s") == 3 else (ALPHA, uuid4())
            with pytest.raises(psycopg.errors.InsufficientPrivilege, match="permission denied"):
                await conn.execute(statement, params)
            assert table  # each statement is a distinct denied table
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            await conn.execute("UPDATE app.runs SET state = 'SUCCEEDED' WHERE false")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            await conn.execute("DELETE FROM app.events WHERE false")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):  # ON CONFLICT is still an INSERT
            await conn.execute(
                "INSERT INTO app.events (event_id, tenant_id, conversation_id, run_id, sequence, type, occurred_at,"
                " source, payload) VALUES (gen_random_uuid(), %s, %s, %s, 1, 'x', now(), 'application', '{}')"
                " ON CONFLICT DO NOTHING",
                (ALPHA, uuid4(), uuid4()),
            )
    api = await role_conn(Role.API)
    cur = await api.execute("UPDATE app.runs SET cancel_requested = true WHERE false")  # the one column api may set
    assert cur.rowcount == 0


async def test_r007_r008_rls_isolates_tenants_and_a_reused_connection_keeps_nothing(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    alpha_run = await seed_run(app_conn, ALPHA)
    beta_run = await seed_run(app_conn, BETA)
    try:
        api = await role_conn(Role.API)
        seen: dict[UUID, set[UUID]] = {}
        for tenant in (ALPHA, BETA):
            async with api.transaction():
                await api.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant),))
                cur = await api.execute("SELECT run_id FROM app.runs WHERE run_id = ANY(%s)", ([alpha_run, beta_run],))
                seen[tenant] = {r["run_id"] for r in await cur.fetchall()}
                cur = await api.execute("UPDATE app.runs SET cancel_requested = true WHERE run_id = %s", (beta_run,))
                assert cur.rowcount == (1 if tenant == BETA else 0)
                await api.execute("UPDATE app.runs SET cancel_requested = false WHERE run_id = %s", (beta_run,))
        assert seen == {ALPHA: {alpha_run}, BETA: {beta_run}}
        # WITH CHECK: a row for beta under alpha's context is refused, and the error ends that transaction.
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="row-level security"):
            async with api.transaction():
                await api.execute("SELECT set_config('app.tenant_id', %s, true)", (str(ALPHA),))
                await api.execute(
                    "INSERT INTO app.conversations (conversation_id, tenant_id, created_by)"
                    " VALUES (gen_random_uuid(), %s, gen_random_uuid())",
                    (BETA,),
                )
        # R008: after the units, the same connection's GUC is '' (spike §1): zero rows, no error (spike §2 NULLIF).
        cur = await api.execute("SELECT count(*) AS n FROM app.runs")
        assert (await cur.fetchone())["n"] == 0
        cur = await api.execute("SELECT current_setting('app.tenant_id', true) AS t")
        assert (await cur.fetchone())["t"] in ("", None)
    finally:
        await purge_run(app_conn, alpha_run)
        await purge_run(app_conn, beta_run)


async def test_r009_composite_keys_refuse_cross_tenant_children(app_conn: persistence.Conn) -> None:
    alpha_run = await seed_run(app_conn, ALPHA)
    try:
        # The superuser bypasses RLS and grants, so what refuses these rows is the key itself.
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            await app_conn.execute(
                "INSERT INTO app.run_state_history (tenant_id, run_id, seq, to_state, performer) VALUES (%s, %s, 9, 'X', 'x')",
                (BETA, alpha_run),
            )
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            await app_conn.execute(
                "INSERT INTO app.drafts (id, tenant_id, run_id, draft_sha256, validated, kind)"
                " VALUES (gen_random_uuid(), %s, %s, 'h', true, 'proposal')",
                (BETA, alpha_run),
            )
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            await app_conn.execute(
                "INSERT INTO app.jobs (id, type, tenant_id, run_id, dedup_key) VALUES (gen_random_uuid(), 'x', %s, %s, %s)",
                (BETA, alpha_run, f"r009-{uuid4()}"),
            )
        draft, proposal = uuid4(), uuid4()
        await app_conn.execute(
            "INSERT INTO app.drafts (id, tenant_id, run_id, draft_sha256, validated, kind) VALUES (%s, %s, %s, 'h', true, 'proposal')",
            (draft, ALPHA, alpha_run),
        )
        with pytest.raises(psycopg.errors.ForeignKeyViolation):  # an alpha proposal pointing at the draft as beta's
            await app_conn.execute(
                "INSERT INTO app.proposals (proposal_id, tenant_id, run_id, revision, draft_id, payload, payload_canonical,"
                " payload_sha256, canonicalization_version, authored_by, expires_at)"
                " VALUES (%s, %s, %s, 1, %s, '{}', '', 'h', 1, '{}', now())",
                (proposal, BETA, alpha_run, draft),
            )
        await app_conn.execute(
            "INSERT INTO app.proposals (proposal_id, tenant_id, run_id, revision, draft_id, payload, payload_canonical,"
            " payload_sha256, canonicalization_version, authored_by, expires_at)"
            " VALUES (%s, %s, %s, 1, %s, '{}', '', 'h', 1, '{}', now())",
            (proposal, ALPHA, alpha_run, draft),
        )
        with pytest.raises(psycopg.errors.ForeignKeyViolation):  # a grant naming the proposal under the other tenant
            await app_conn.execute(
                "INSERT INTO app.execution_grant (action_id, tenant_id, run_id, proposal_id, payload_sha256)"
                " VALUES (gen_random_uuid(), %s, %s, %s, 'h')",
                (BETA, alpha_run, proposal),
            )
    finally:
        await purge_run(app_conn, alpha_run)


async def test_r106_policy_text_force_and_no_rls_tables(app_conn: persistence.Conn) -> None:
    cur = await app_conn.execute(
        "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity FROM pg_class c JOIN pg_namespace n"
        " ON n.oid = c.relnamespace WHERE n.nspname = 'app' AND c.relkind = 'r'"
    )
    flags = {r["relname"]: (r["relrowsecurity"], r["relforcerowsecurity"]) for r in await cur.fetchall()}
    for table in p.RLS_TABLES:
        assert flags[table] == (True, True), table
    for table in p.NO_RLS:
        assert flags[table] == (False, False), table
    cur = await app_conn.execute(
        "SELECT tablename, policyname, permissive, roles, cmd, qual, with_check FROM pg_policies WHERE schemaname = 'app'"
    )
    policies = {(r["tablename"], r["policyname"]): r for r in await cur.fetchall()}
    expected = {(t, "tenant_isolation") for t in p.RLS_TABLES} | {(t, "sweeper_all") for t in p.SWEEPER_ALL}
    assert set(policies) == expected
    for (table, name), row in policies.items():
        assert row["permissive"] == "PERMISSIVE" and row["cmd"] == "ALL", (table, name)
        if name == "tenant_isolation":
            assert set(row["roles"]) == set(p.POLICY_ROLES) and row["qual"] == p.POLICY_QUAL == row["with_check"]
        else:
            assert row["roles"] == ["sweeper"] and row["qual"] == "true" and row["with_check"] == "true"
```

Note: this module seeds with plain superuser INSERTs on purpose (`seed_run`): Plan D's `persistence.create_run` no longer fits the schema after revision 0002, and Task 5's rewrite depends on Task 3's functions.

- [ ] **Step 8: Write the live clock test (R126)**

Create `tests/e2e/test_clock_live.py`:

```python
"""app.current_time() and app.test_clock under the test profile (OPS_LIVE=1; AM-20.6, R126).

Catches: a GUC that moves the clock, a runtime role that can write or even read the offset, a harness that cannot,
a clock function that stops working when the table is absent (dev), and a dev skeleton that would start against a
database carrying the table.
"""

from collections.abc import Awaitable, Callable
from datetime import timedelta

import psycopg
import pytest
from ops_core import persistence, settings
from ops_core.settings import Profile, Role

pytestmark = pytest.mark.asyncio

RoleConn = Callable[[Role], Awaitable[persistence.Conn]]


async def clock(conn: persistence.Conn) -> timedelta:
    cur = await conn.execute("SELECT app.current_time() - clock_timestamp() AS delta")
    return (await cur.fetchone())["delta"]


async def test_r126_only_the_harness_moves_the_clock_and_no_guc_does(app_conn: persistence.Conn, role_conn: RoleConn) -> None:
    harness = await role_conn(Role.TEST_HARNESS)
    api = await role_conn(Role.API)
    try:
        assert abs(await clock(api)) < timedelta(seconds=1)
        await api.execute("SELECT set_config('app.clock_offset', '99 days', false)")
        await api.execute("SELECT set_config('app.test_clock', '99 days', false)")
        assert abs(await clock(api)) < timedelta(seconds=1)  # GUCs are never read (SA:530)
        await harness.execute("UPDATE app.test_clock SET clock_offset = interval '3 days'")
        for conn in (api, await role_conn(Role.WORKER), await role_conn(Role.MCP_EXEC)):
            assert abs(await clock(conn) - timedelta(days=3)) < timedelta(seconds=1)
        for conn in (api, await role_conn(Role.WORKER), await role_conn(Role.SWEEPER)):
            for statement in (
                "UPDATE app.test_clock SET clock_offset = interval '0'",
                "DELETE FROM app.test_clock",
                "SELECT clock_offset FROM app.test_clock",
            ):
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    await conn.execute(statement)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):  # ins/upd/del, not sel (AM-20.2)
            await harness.execute("SELECT clock_offset FROM app.test_clock")
        with pytest.raises(psycopg.errors.UniqueViolation):  # one row, ever
            await harness.execute("INSERT INTO app.test_clock (clock_offset) VALUES (interval '1 day')")
    finally:
        await harness.execute("UPDATE app.test_clock SET clock_offset = interval '0'")
    assert abs(await clock(api)) < timedelta(seconds=1)


async def test_dev_profile_refuses_a_database_with_the_test_clock(migrated: None) -> None:
    from scripts.skeleton import clock_guard

    superuser = settings.superuser_postgres()
    clock_guard(superuser, Profile.TEST)  # the test profile may run against it
    with pytest.raises(RuntimeError, match="test_clock"):
        clock_guard(superuser, Profile.DEV)
```

- [ ] **Step 9: Run the live suite**

Run: `OPS_LIVE=1 PYTHONUTF8=1 uv run python -m pytest tests/e2e/test_migrations_and_persistence.py tests/e2e/test_roles_live.py tests/e2e/test_clock_live.py -q -x`
Expected: PASS (the plain `0001_walking_skeleton` downgrade target works with the branch applied; measured in round 1). Expected red until Task 5 (Plan D's persistence code writes rows revision 0002 no longer accepts): the Plan D tests in `tests/e2e/test_migrations_and_persistence.py` other than the two named here, and `test_worker_live.py`, `test_mcp_read_live.py`, `test_mcp_write_live.py`, `test_r105_walking_skeleton.py` (until Task 7); nothing else may fail. Then the full gate: `PYTHONUTF8=1 uv run python scripts/check.py` → GREEN (it runs no live test).

- [ ] **Step 10: Update the runbook and commit**

In `docs/runbooks/walking-skeleton.md`, after the `migrate` step, add one paragraph: `migrate` reads `PROFILE` (dev by default; `test` also applies the `testclock` branch) and `OPS_PG_DB`/`OPS_INCIDENT_PG_DB`; it creates or re-keys the login roles from `postgres_<role>_password` (run `scripts/bootstrap_dev.py secrets` once after pulling this branch to generate the seven new files); `up` refuses outside the test profile when `app.test_clock` exists; `keys` is the destination-vs-grant detective check; the live suite runs against `ops_test`/`incident_test` and never touches the dev databases.

```bash
git add scripts/skeleton.py migrations/app tests/plan_e/test_skeleton_cli.py tests/e2e docs/runbooks/walking-skeleton.md
git commit -m "feat(migrations): roles, ownership, grants, RLS, app.current_time and the testclock branch; per-session test databases (T09)"
```

---
### Task 3: Revision 0003 — the run-path definer functions

**Files:**
- Create: `migrations/app/versions/0003_run_path_functions.py`, `tests/plan_e/test_transitions_table.py`, `tests/e2e/test_definers_run_path_live.py`

**Interfaces:**
- Consumes: `ops_core.privileges.function_grant_statements`, `DEFINER_FUNCTIONS`, `HELPER_FUNCTIONS` (Task 1); `app.transitions`, `app.run_directory`, `app.current_time()`, the roles (Task 2).
- Produces (SQL, schema `app`; every error is `RAISE … USING ERRCODE = 'OCnnn'`, ruling 20):
  - `_authority(p_function text, p_allowed text[])` — raises `OC001` unless `session_user = ANY(p_allowed)`.
  - `_tenant_of_run(p_run_id uuid) RETURNS uuid` — `run_directory` lookup (`OC002` if absent) **and** `set_config('app.tenant_id', …, true)`.
  - `_tenant_of_action(p_action_id uuid) RETURNS uuid` — iterates `tenants`, sets each, returns the tenant whose `execution_grant` holds the action (`OC002` if none); leaves the setting at that tenant.
  - `_append_event(p_tenant_id uuid, p_run_id uuid, p_type text, p_source text, p_payload jsonb) RETURNS TABLE (event_id uuid, sequence integer, occurred_at timestamptz)` — AM-14 rules in SQL (`OC006`), `runs … FOR UPDATE`, `next_event_seq`.
  - `_transition(p_run_id uuid, p_dst text, p_performer text, p_reason text, p_expected_version integer, p_event text, p_event_payload jsonb) RETURNS integer` — `runs … FOR UPDATE`, `OC003` on a stale version, `OC004` unless `app.transitions` has the row (and the reason when the row names reasons), updates `state/state_version/reason/slot_held/updated_at`, inserts `run_state_history`, emits `p_event` when not null; returns the new version.
  - `create_run(p_tenant_id uuid, p_conversation_id uuid, p_request jsonb, p_intent text, p_supersedes_run_id uuid) RETURNS TABLE (run_id uuid, state_version integer)` — callers `api`.
  - `transition_run(p_run_id uuid, p_from text, p_to text, p_reason text, p_expected_version integer, p_detail jsonb) RETURNS integer` — callers `worker`.
  - `append_event(p_run_id uuid, p_type text, p_payload jsonb, p_source text) RETURNS TABLE (event_id uuid, sequence integer, occurred_at timestamptz)` — callers `api`, `worker`, `sweeper`.
  - `resolve_identity(p_issuer text, p_subject uuid) RETURNS TABLE (tenant_id uuid, role text)` — callers `api`.
  - `revoke_handles(p_run_id uuid, p_fence bigint) RETURNS integer` — callers `worker`.
- Produces: `tests/e2e/test_definers_run_path_live.py` helpers `as_role(conn, tenant=None)` (a transaction with an optional preset tenant) used by Task 4's tests.

- [ ] **Step 1: Write the failing unit test for the transition table mirror**

Create `tests/plan_e/test_transitions_table.py`:

```python
"""Revision 0002's `app.transitions` rows are generated from ops_core.states.TRANSITIONS (ruling 10), so the SQL
mirror cannot drift from the T07 table; this pins the generator's output shape and its guard, and scans every
revision's op.execute strings for SQLAlchemy bind parameters."""

import importlib.util
import sys
from pathlib import Path

import pytest
from ops_core import privileges
from ops_core.states import TRANSITIONS

ROOT = Path(__file__).resolve().parents[2]


def load_revision():
    path = ROOT / "migrations" / "app" / "versions" / "0002_roles_grants_rls.py"
    spec = importlib.util.spec_from_file_location("rev0002", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["rev0002"] = module
    spec.loader.exec_module(module)
    return module


def test_one_insert_per_transition_row_with_sorted_reasons() -> None:
    rows = load_revision().transition_rows()
    assert len(rows) == len(TRANSITIONS)
    creation = [r for r in rows if "VALUES ('', 'QUEUED', 'create_run'" in r]
    assert len(creation) == 1 and creation[0].endswith("ARRAY[]::text[])")
    escalate = [r for r in rows if "'ESCALATED', 'escalate_run'" in r]
    assert escalate and all("ARRAY['conflict', 'escalation_deadline']::text[]" in r for r in escalate)
    assert all(" :" not in r for r in rows)  # never a SQLAlchemy bind


def test_revision_0002_lists_are_frozen_literals_within_the_matrix() -> None:
    """0002 names its tables itself (NI5): a later matrix row must not change an applied revision."""
    rev = load_revision()
    assert set(rev.TABLES) <= set(privileges.GRANTS) and set(rev.RLS) <= set(privileges.RLS_TABLES)
    assert "test_clock" not in rev.TABLES


VERSIONS = ROOT / "migrations" / "app" / "versions"
# The revisions that exist at this point of the plan; Tasks 3 and 4 add theirs and the cases appear (no skip, BS:597).
REVISIONS = tuple(
    n
    for n in ("0002_roles_grants_rls", "0003_run_path_functions", "0004_write_path_functions", "tc_0001_test_clock")
    if (VERSIONS / f"{n}.py").exists()
)


def executed_statements(name: str, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every string a revision's upgrade() and downgrade() hand to op.execute, captured without a database."""
    import alembic.op

    path = VERSIONS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"rev_{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    seen: list[str] = []
    monkeypatch.setattr(alembic.op, "execute", lambda statement, *a, **k: seen.append(str(statement)))
    module.upgrade()
    module.downgrade()
    return seen


@pytest.mark.parametrize("name", REVISIONS)
def test_no_op_execute_string_carries_a_sqlalchemy_bind(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """':1' and ':timeout' inside a body were binds in round 1; text() must see none (fact sheet §4.3)."""
    from sqlalchemy import text

    for statement in executed_statements(name, monkeypatch):
        assert text(statement)._bindparams == {}, statement[:120]
```

(The parametrisation covers the revisions present on disk, so the 0003 case appears with this task's Step 3 and the 0004 case with Task 4.)

Run: `uv run python -m pytest tests/plan_e/test_transitions_table.py -q` → PASS already if Task 2's revision is correct (this test guards it; if it fails, fix the revision, not the test). Keep it; the 0003 case appears and must pass after Step 3.

- [ ] **Step 2: Write the failing live tests**

Create `tests/e2e/test_definers_run_path_live.py`:

```python
"""The run-path definer functions as their callers (OPS_LIVE=1; AM-20.3 rows 1–3, 23, R128, R106 part 1).

Catches: a function callable by the wrong role, transition_run accepting a post-grant target or a wrong `from`,
a stale expected_version, a transition that leaves the slot flag wrong, an event that skips a sequence number or
carries a forbidden (type, source), run.* events accepted from append_event, a preset tenant that leaks through
`resolve_identity`, and a plain SET inside any function (the caller's app.tenant_id must be unchanged after a call).
"""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import psycopg
import pytest
from ops_core import persistence
from ops_core.settings import Role
from psycopg.types.json import Jsonb

from tests.e2e.conftest import purge_run

pytestmark = pytest.mark.asyncio

RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
ALPHA = UUID("3ea79c95-914c-52cb-9d10-c4e19dda8ff7")
BETA = UUID("5ab45c2c-1e12-5a0c-a2b9-66cd2ff05201")
ALEX = UUID("2fc05986-c7ec-544c-b628-fdb112bbf18a")
ISSUER_SQL = "SELECT issuer FROM app.memberships LIMIT 1"


@asynccontextmanager
async def as_role(conn: persistence.Conn, preset: UUID | None = None) -> AsyncIterator[persistence.Conn]:
    """A transaction on a role connection, optionally with a preset (hostile) session-level tenant."""
    if preset is not None:
        await conn.execute("SELECT set_config('app.tenant_id', %s, false)", (str(preset),))
    try:
        async with conn.transaction():
            yield conn
    finally:
        if preset is not None:
            await conn.execute("SELECT set_config('app.tenant_id', '', false)")


async def refused(conn: persistence.Conn, statement: str, params: tuple[object, ...]) -> str:
    """The SQLSTATE a call raises, run in its own transaction so the aborted transaction never leaks."""
    try:
        async with conn.transaction():
            await conn.execute(statement, params)
    except psycopg.Error as exc:
        return str(exc.sqlstate)
    raise AssertionError("expected a database error")


async def conversation(app_conn: persistence.Conn, tenant: UUID) -> tuple[UUID, UUID]:
    conv, msg = uuid4(), uuid4()
    await app_conn.execute(
        "INSERT INTO app.conversations (conversation_id, tenant_id, created_by) VALUES (%s, %s, %s)", (conv, tenant, ALEX)
    )
    await app_conn.execute(
        "INSERT INTO app.messages (message_id, tenant_id, conversation_id, kind, text, author)"
        " VALUES (%s, %s, %s, 'investigate', 'x', %s)",
        (msg, tenant, conv, ALEX),
    )
    return conv, msg


def request(msg: UUID) -> Jsonb:
    end = datetime.now(UTC).replace(microsecond=0)
    return Jsonb(
        {
            "message_id": str(msg),
            "requester": str(ALEX),
            "asset_id": "A17",
            "start_at": (end - timedelta(hours=24)).isoformat(),
            "end_at": end.isoformat(),
        }
    )


async def create(api: persistence.Conn, tenant: UUID, conv: UUID, msg: UUID) -> UUID:
    cur = await api.execute(
        "SELECT * FROM app.create_run(%s, %s, %s, 'investigate', NULL)", (tenant, conv, request(msg))
    )
    row = await cur.fetchone()
    assert row is not None and row["state_version"] == 1
    return row["run_id"]


async def test_create_run_is_the_only_door_and_sets_everything_up(app_conn: persistence.Conn, role_conn: RoleConn) -> None:
    api, worker = await role_conn(Role.API), await role_conn(Role.WORKER)
    conv, msg = await conversation(app_conn, ALPHA)
    conv_b, msg_b = await conversation(app_conn, BETA)
    run = None
    try:
        async with as_role(api):
            run = await create(api, ALPHA, conv, msg)
        cur = await app_conn.execute("SELECT * FROM app.runs WHERE run_id = %s", (run,))
        row = await cur.fetchone()
        assert row["state"] == "QUEUED" and row["slot_held"] and row["next_event_seq"] == 1 and row["intent"] == "investigate"
        cur = await app_conn.execute("SELECT tenant_id FROM app.run_directory WHERE run_id = %s", (run,))
        assert (await cur.fetchone())["tenant_id"] == ALPHA
        cur = await app_conn.execute("SELECT type, dedup_key FROM app.jobs WHERE run_id = %s", (run,))
        assert [(r["type"], r["dedup_key"]) for r in await cur.fetchall()] == [("investigate", f"{run}:1")]
        cur = await app_conn.execute("SELECT type, source, sequence FROM app.events WHERE run_id = %s", (run,))
        assert [(r["type"], r["source"], r["sequence"]) for r in await cur.fetchall()] == [("run.accepted", "application", 1)]
        cur = await app_conn.execute("SELECT seq, from_state, to_state, performer FROM app.run_state_history WHERE run_id = %s", (run,))
        assert [tuple(r.values()) for r in await cur.fetchall()] == [(1, None, "QUEUED", "create_run")]
        # The slot rule is the function's refusal, not a bare unique violation.
        assert await refused(api, "SELECT * FROM app.create_run(%s, %s, %s, 'investigate', NULL)", (ALPHA, conv, request(msg))) == "OC005"
        # Wrong caller, wrong tenant, wrong intent.
        assert await refused(worker, "SELECT * FROM app.create_run(%s, %s, %s, 'investigate', NULL)", (ALPHA, conv, request(msg))) == "42501"  # no EXECUTE
        assert await refused(app_conn, "SELECT * FROM app.create_run(%s, %s, %s, 'investigate', NULL)", (ALPHA, conv, request(msg))) == "OC001"  # _authority, past the ACL
        assert await refused(api, "SELECT * FROM app.create_run(%s, %s, %s, 'investigate', NULL)", (ALPHA, conv_b, request(msg_b))) == "OC002"
        assert await refused(api, "SELECT * FROM app.create_run(%s, %s, %s, 'guess', NULL)", (BETA, conv_b, request(msg_b))) == "OC005"
        assert await refused(api, "SELECT * FROM app.create_run(%s, %s, %s, 'investigate', %s)", (BETA, conv_b, request(msg_b), run)) == "OC002"
    finally:
        if run is not None:
            await purge_run(app_conn, run)
        await app_conn.execute("DELETE FROM app.messages WHERE conversation_id IN (%s, %s)", (conv, conv_b))
        await app_conn.execute("DELETE FROM app.conversations WHERE conversation_id IN (%s, %s)", (conv, conv_b))


async def test_transition_run_is_worker_only_pre_grant_only_and_versioned(app_conn: persistence.Conn, role_conn: RoleConn) -> None:
    api, worker = await role_conn(Role.API), await role_conn(Role.WORKER)
    conv, msg = await conversation(app_conn, ALPHA)
    async with as_role(api):
        run = await create(api, ALPHA, conv, msg)
    try:
        assert await refused(api, "SELECT app.transition_run(%s, 'QUEUED', 'RETRIEVING', NULL, 1, '{}')", (run,)) == "42501"  # R128: the ACL refuses any role but worker
        assert await refused(app_conn, "SELECT app.transition_run(%s, 'QUEUED', 'RETRIEVING', NULL, 1, '{}')", (run,)) == "OC001"  # the superuser passes the ACL and _authority refuses
        assert await refused(worker, "SELECT app.transition_run(%s, 'QUEUED', 'EXECUTING', NULL, 1, '{}')", (run,)) == "OC005"  # a post-grant target, never
        assert await refused(worker, "SELECT app.transition_run(%s, 'QUEUED', 'DRAFTING', NULL, 1, '{}')", (run,)) == "OC004"  # not a row of the table
        assert await refused(worker, "SELECT app.transition_run(%s, 'RETRIEVING', 'DRAFTING', NULL, 1, '{}')", (run,)) == "OC003"  # stale from-state / version
        assert await refused(worker, "SELECT app.transition_run(%s, 'QUEUED', 'RETRIEVING', NULL, 7, '{}')", (run,)) == "OC003"
        cur = await app_conn.execute("SELECT state, state_version FROM app.runs WHERE run_id = %s", (run,))
        assert dict(await cur.fetchone()) == {"state": "QUEUED", "state_version": 1}  # every refusal left the row alone
        async with as_role(worker):
            cur = await worker.execute("SELECT app.transition_run(%s, 'QUEUED', 'RETRIEVING', NULL, 1, '{}') AS v", (run,))
            assert (await cur.fetchone())["v"] == 2
            cur = await worker.execute(
                "SELECT app.transition_run(%s, 'RETRIEVING', 'FAILED', NULL, 2, %s) AS v", (run, Jsonb({"message": "retrieval failed"}))
            )
            assert (await cur.fetchone())["v"] == 3
        cur = await app_conn.execute("SELECT state, state_version, slot_held, reason FROM app.runs WHERE run_id = %s", (run,))
        assert dict(await cur.fetchone()) == {"state": "FAILED", "state_version": 3, "slot_held": False, "reason": None}
        cur = await app_conn.execute("SELECT type, sequence, payload FROM app.events WHERE run_id = %s ORDER BY sequence", (run,))
        rows = await cur.fetchall()
        assert [(r["type"], r["sequence"]) for r in rows] == [("run.accepted", 1), ("run.failed", 2)]
        assert rows[1]["payload"] == {"message": "retrieval failed"}
        cur = await app_conn.execute("SELECT seq, to_state, performer FROM app.run_state_history WHERE run_id = %s ORDER BY seq", (run,))
        assert [tuple(r.values()) for r in await cur.fetchall()] == [(1, "QUEUED", "create_run"), (2, "RETRIEVING", "transition_run"), (3, "FAILED", "transition_run")]
    finally:
        await purge_run(app_conn, run)


async def test_append_event_rules_and_sequence(app_conn: persistence.Conn, role_conn: RoleConn) -> None:
    api, worker, sweeper = await role_conn(Role.API), await role_conn(Role.WORKER), await role_conn(Role.SWEEPER)
    conv, msg = await conversation(app_conn, ALPHA)
    async with as_role(api):
        run = await create(api, ALPHA, conv, msg)
    try:
        async with as_role(worker):
            cur = await worker.execute("SELECT * FROM app.append_event(%s, 'tool.started', %s, 'application')", (run, Jsonb({"message": "search_procedures"})))
            assert (await cur.fetchone())["sequence"] == 2
            cur = await worker.execute("SELECT * FROM app.append_event(%s, 'explanation.ready', %s, 'model_summary')", (run, Jsonb({"message": "m", "evidence_refs": ["a:v1:s"]})))
            assert (await cur.fetchone())["sequence"] == 3
        for conn, event_type, source, payload in (
            (worker, "run.failed", "application", {}),  # run.* only from the transition functions (SA:452)
            (worker, "action.granted", "application", {}),
            (worker, "review.blocked", "application", {}),
            (api, "explanation.ready", "model_summary", {"message": "m"}),  # only the worker may say model_summary
            (worker, "tool.started", "model_summary", {"message": "m"}),
            (worker, "tool.started", "destination", {}),
            (worker, "tool.completed", "application", {"receipt": {}}),  # evidence keys on a non-outcome type
            (worker, "explanation.ready", "model_summary", {"message": "m", "evidence_refs": [1, ""]}),  # refs must be non-empty strings
            (sweeper, "tool.started", "application", []),
        ):
            assert await refused(conn, "SELECT * FROM app.append_event(%s, %s, %s, %s)", (run, event_type, Jsonb(payload), source)) == "OC006", event_type
        async with as_role(sweeper):
            cur = await sweeper.execute("SELECT * FROM app.append_event(%s, 'tool.completed', '{}', 'application')", (run,))
            assert (await cur.fetchone())["sequence"] == 4
        cur = await app_conn.execute("SELECT next_event_seq FROM app.runs WHERE run_id = %s", (run,))
        assert (await cur.fetchone())["next_event_seq"] == 4
        cur = await app_conn.execute("SELECT sequence, type, source FROM app.events WHERE run_id = %s ORDER BY sequence", (run,))
        assert [tuple(r.values()) for r in await cur.fetchall()] == [
            (1, "run.accepted", "application"), (2, "tool.started", "application"), (3, "explanation.ready", "model_summary"), (4, "tool.completed", "application")
        ]
        assert await refused(worker, "SELECT * FROM app.append_event(%s, 'tool.started', '{}', 'application')", (uuid4(),)) == "OC002"  # a run of another tenant, by id: not found, never a leak
    finally:
        await purge_run(app_conn, run)


async def test_resolve_identity_ignores_a_preset_tenant_and_restores_it(app_conn: persistence.Conn, role_conn: RoleConn) -> None:
    api = await role_conn(Role.API)
    issuer = (await (await app_conn.execute(ISSUER_SQL)).fetchone())["issuer"]
    async with as_role(api, preset=BETA):  # a hostile preset: alex is alpha's requester, beta must not hide him
        cur = await api.execute("SELECT * FROM app.resolve_identity(%s, %s)", (issuer, ALEX))
        assert [(r["tenant_id"], r["role"]) for r in await cur.fetchall()] == [(ALPHA, "requester")]
        cur = await api.execute("SELECT current_setting('app.tenant_id', true) AS t")
        assert (await cur.fetchone())["t"] == str(BETA)  # restored by the function attribute (spike §1 D)
    async with as_role(api):
        cur = await api.execute("SELECT * FROM app.resolve_identity(%s, %s)", (issuer, uuid4()))
        assert await cur.fetchall() == []
    worker = await role_conn(Role.WORKER)
    assert await refused(worker, "SELECT * FROM app.resolve_identity(%s, %s)", (issuer, ALEX)) == "42501"


async def test_every_run_path_function_leaves_the_callers_tenant_unchanged(app_conn: persistence.Conn, role_conn: RoleConn) -> None:
    """T09 DoD 5: a plain SET inside a body would survive the call; the attribute plus set_config(..., true) does not."""
    api, worker = await role_conn(Role.API), await role_conn(Role.WORKER)
    conv, msg = await conversation(app_conn, ALPHA)
    async with as_role(api, preset=BETA):
        run = await create(api, ALPHA, conv, msg)
        cur = await api.execute("SELECT current_setting('app.tenant_id', true) AS t")
        assert (await cur.fetchone())["t"] == str(BETA)
    try:
        calls = (
            (worker, "SELECT app.transition_run(%s, 'QUEUED', 'RETRIEVING', NULL, 1, '{}')", (run,)),
            (worker, "SELECT * FROM app.append_event(%s, 'tool.started', '{}', 'application')", (run,)),
            (worker, "SELECT app.revoke_handles(%s, 1)", (run,)),
        )
        for conn, statement, params in calls:
            async with as_role(conn, preset=BETA):
                await conn.execute(statement, params)
                cur = await conn.execute("SELECT current_setting('app.tenant_id', true) AS t")
                assert (await cur.fetchone())["t"] == str(BETA), statement
    finally:
        await purge_run(app_conn, run)


async def test_revoke_handles_marks_the_runs_live_handles(app_conn: persistence.Conn, role_conn: RoleConn) -> None:
    api, worker = await role_conn(Role.API), await role_conn(Role.WORKER)
    conv, msg = await conversation(app_conn, ALPHA)
    async with as_role(api):
        run = await create(api, ALPHA, conv, msg)
    try:
        job = (await (await app_conn.execute("SELECT id FROM app.jobs WHERE run_id = %s", (run,))).fetchone())["id"]
        for digest in ("a" * 64, "b" * 64):
            await app_conn.execute(
                "INSERT INTO app.invocation_context (handle_sha256, run_id, job_id, server, azp, expires_at)"
                " VALUES (%s, %s, %s, 'read', 'ops-worker', now() + interval '1 minute')",
                (digest, run, job),
            )
        async with as_role(worker):
            cur = await worker.execute("SELECT app.revoke_handles(%s, 1) AS n", (run,))
            assert (await cur.fetchone())["n"] == 2
            cur = await worker.execute("SELECT app.revoke_handles(%s, 1) AS n", (run,))
            assert (await cur.fetchone())["n"] == 0
        cur = await app_conn.execute("SELECT count(*) AS n FROM app.invocation_context WHERE run_id = %s AND revoked_at IS NULL", (run,))
        assert (await cur.fetchone())["n"] == 0
        assert await refused(api, "SELECT app.revoke_handles(%s, 1)", (run,)) == "42501"
    finally:
        await purge_run(app_conn, run)


async def test_function_catalog_shape(app_conn: persistence.Conn) -> None:
    """R106: owner app_definer, SECURITY DEFINER, search_path pinned, the tenant attribute on every granted function,
    PUBLIC revoked everywhere, helpers granted to nobody and carrying no tenant attribute."""
    from ops_core import privileges as p

    cur = await app_conn.execute(
        "SELECT p.proname, p.proowner::regrole::text AS owner, p.prosecdef, p.proconfig, p.proacl::text AS acl"
        " FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = 'app'"
    )
    rows = {r["proname"]: r for r in await cur.fetchall()}
    for name in list(p.DEFINER_FUNCTIONS) + list(p.HELPER_FUNCTIONS):
        if name not in rows:
            continue  # Task 4's functions arrive with revision 0004; this test is re-run there with every name present
        row = rows[name]
        assert row["owner"] == "app_definer", name
        assert "search_path=app, pg_temp" in row["proconfig"], name
        entries = row["acl"].strip("{}").split(",")
        assert not any(entry.startswith("=") for entry in entries), (name, row["acl"])  # no PUBLIC entry
        grantees = {entry.split("=")[0] for entry in entries} - {"app_definer"}
        if name.startswith("_"):
            assert grantees == set() and "app.tenant_id=" not in row["proconfig"], name
        else:
            assert row["prosecdef"] and "app.tenant_id=" in row["proconfig"], name
            assert grantees == set(p.DEFINER_FUNCTIONS[name][1]), (name, grantees)
    assert set(rows) <= set(p.DEFINER_FUNCTIONS) | set(p.HELPER_FUNCTIONS), sorted(rows)  # no stray function in app
```

Run: `OPS_LIVE=1 PYTHONUTF8=1 uv run python -m pytest tests/e2e/test_definers_run_path_live.py -q -x` → FAIL (the `create` helper raises `UndefinedFunction`; a `refused` call reports `42883`).

- [ ] **Step 3: Write revision 0003**

Create `migrations/app/versions/0003_run_path_functions.py`. Every function is one string in `FUNCTIONS` (in dependency order), each followed by `ALTER FUNCTION … OWNER TO app_definer` inside the same string; the grants come from `ops_core.privileges`.

```python
"""The run-path definer functions (T09; AM-20.3 rows 1–3 and 23, the 24th `resolve_identity`, the internal helpers):
the only writers of runs.state, run_state_history, events and the run's jobs.

Revision ID: 0003_run_path_functions
Revises: 0002_roles_grants_rls

Every granted function is SECURITY DEFINER, owned by app_definer, pins search_path, carries `SET app.tenant_id = ''`
so a caller's preset is invisible and its own transaction-local setting is undone on exit (spike §1 D), checks
session_user first (SA:389) and resolves the tenant through run_directory before touching a tenant row (SA:446).
Helpers carry no tenant attribute: they run inside the tenant the outer function set. Errors are SQLSTATE class OC
(ruling 20): OC001 authority, OC002 not found, OC003 version, OC004 illegal transition, OC005 refused (DETAIL = code),
OC006 event rule. Each CREATE … GRANT block is one op.execute string (spike §4).
"""

from alembic import op
from ops_core import privileges

revision = "0003_run_path_functions"
down_revision = "0002_roles_grants_rls"
branch_labels = None
depends_on = None

HEADER = "LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, pg_temp SET app.tenant_id = ''"
HELPER_HEADER = "LANGUAGE plpgsql SET search_path = app, pg_temp"

AUTHORITY = f"""
CREATE OR REPLACE FUNCTION app._authority(p_function text, p_allowed text[]) RETURNS void
{HELPER_HEADER} AS $fn$
BEGIN
    -- session_user is the login role even inside SECURITY DEFINER; SET ROLE does not change it (spike §1, §3).
    IF NOT (session_user::text = ANY (p_allowed)) THEN
        RAISE EXCEPTION 'authority_violation' USING ERRCODE = 'OC001',
            DETAIL = format('%s may not call %s', session_user, p_function);
    END IF;
END
$fn$;
ALTER FUNCTION app._authority(text, text[]) OWNER TO app_definer;
"""

TENANT_OF_RUN = f"""
CREATE OR REPLACE FUNCTION app._tenant_of_run(p_run_id uuid) RETURNS uuid
{HELPER_HEADER} AS $fn$
DECLARE
    v_tenant uuid;
BEGIN
    -- run_directory has no RLS (SA:523): it is the bootstrap that lets a function find the tenant it must set.
    SELECT tenant_id INTO v_tenant FROM run_directory WHERE run_id = p_run_id;
    IF v_tenant IS NULL THEN
        RAISE EXCEPTION 'not_found' USING ERRCODE = 'OC002', DETAIL = 'run';
    END IF;
    PERFORM set_config('app.tenant_id', v_tenant::text, true);
    RETURN v_tenant;
END
$fn$;
ALTER FUNCTION app._tenant_of_run(uuid) OWNER TO app_definer;
"""

APPEND_EVENT_HELPER = f"""
CREATE OR REPLACE FUNCTION app._append_event(p_tenant_id uuid, p_run_id uuid, p_type text, p_source text, p_payload jsonb)
RETURNS TABLE (event_id uuid, sequence integer, occurred_at timestamptz)
{HELPER_HEADER} AS $fn$
DECLARE
    v_run runs%ROWTYPE;
    v_outcome_types text[] := ARRAY['action.confirmed', 'action.failed', 'action.late_evidence'];
    v_destination_types text[] := ARRAY['action.confirmed', 'action.failed', 'action.conflict', 'action.late_evidence'];
    v_failed_reasons text[] := ARRAY['aborted_no_commit', 'cancelled_before_send', 'rejected', 'expired'];
BEGIN
    -- AM-14 mirrored (ops_core.outcomes.event_rules_ok is the Python twin): who may assert what.
    IF p_payload IS NULL OR jsonb_typeof(p_payload) <> 'object' THEN
        RAISE EXCEPTION 'event_rule_violation' USING ERRCODE = 'OC006', DETAIL = 'payload must be an object';
    END IF;
    IF p_source = 'model_summary' THEN
        IF p_type <> 'explanation.ready' OR NOT (p_payload ? 'message') OR jsonb_typeof(p_payload->'message') <> 'string'
           OR length(p_payload->>'message') = 0
           OR EXISTS (SELECT 1 FROM jsonb_object_keys(p_payload) k WHERE k NOT IN ('message', 'evidence_refs'))
           OR (p_payload ? 'evidence_refs' AND (jsonb_typeof(p_payload->'evidence_refs') <> 'array'
               OR EXISTS (SELECT 1 FROM jsonb_array_elements(p_payload->'evidence_refs') e
                          WHERE jsonb_typeof(e) <> 'string' OR length(e #>> '{{}}') = 0))) THEN
            RAISE EXCEPTION 'event_rule_violation' USING ERRCODE = 'OC006', DETAIL = 'model_summary';
        END IF;
    ELSIF p_source = 'destination' THEN
        IF NOT (p_type = ANY (v_destination_types)) THEN
            RAISE EXCEPTION 'event_rule_violation' USING ERRCODE = 'OC006', DETAIL = 'destination source';
        END IF;
    ELSIF p_source = 'application' THEN
        IF p_type = ANY (v_destination_types) THEN
            RAISE EXCEPTION 'event_rule_violation' USING ERRCODE = 'OC006', DETAIL = 'destination evidence from application';
        END IF;
    ELSE
        RAISE EXCEPTION 'event_rule_violation' USING ERRCODE = 'OC006', DETAIL = 'source';
    END IF;
    IF NOT (p_type = ANY (v_outcome_types)) AND (p_payload ?| ARRAY['outcome', 'receipt', 'tombstone']) THEN
        RAISE EXCEPTION 'event_rule_violation' USING ERRCODE = 'OC006', DETAIL = 'evidence keys';
    END IF;
    IF p_type = 'action.confirmed' AND (p_payload->>'status' IS DISTINCT FROM 'SUCCEEDED' OR p_payload ? 'tombstone'
                                        OR jsonb_typeof(p_payload->'receipt') IS DISTINCT FROM 'object'
                                        OR NOT (p_payload->'receipt' ?& ARRAY['receipt_id', 'incident_id', 'committed_at'])) THEN
        RAISE EXCEPTION 'event_rule_violation' USING ERRCODE = 'OC006', DETAIL = 'action.confirmed';
    END IF;
    IF p_type = 'action.late_evidence' AND NOT (
        (p_payload->>'outcome' = 'SUCCEEDED' AND jsonb_typeof(p_payload->'receipt') = 'object' AND NOT (p_payload ? 'tombstone'))
        OR (p_payload->>'outcome' = 'FAILED_NO_COMMIT' AND jsonb_typeof(p_payload->'tombstone') = 'object'
            AND NOT (p_payload ? 'receipt'))) THEN
        RAISE EXCEPTION 'event_rule_violation' USING ERRCODE = 'OC006', DETAIL = 'action.late_evidence';
    END IF;
    IF p_type = 'action.failed' AND (coalesce(p_payload->>'reason', '') <> ALL (v_failed_reasons) OR p_payload ? 'receipt') THEN
        RAISE EXCEPTION 'event_rule_violation' USING ERRCODE = 'OC006', DETAIL = 'action.failed';
    END IF;
    -- The runs row lock serialises the counter (SA:303, R089); the tenant is already set, so RLS admits the row.
    SELECT * INTO v_run FROM runs WHERE runs.run_id = p_run_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'not_found' USING ERRCODE = 'OC002', DETAIL = 'run';
    END IF;
    UPDATE runs SET next_event_seq = v_run.next_event_seq + 1 WHERE runs.run_id = p_run_id;
    event_id := gen_random_uuid();
    sequence := v_run.next_event_seq + 1;
    occurred_at := date_trunc('second', app.current_time());
    INSERT INTO events (event_id, tenant_id, conversation_id, run_id, sequence, type, occurred_at, source, payload)
    VALUES (event_id, p_tenant_id, v_run.conversation_id, p_run_id, sequence, p_type, occurred_at, p_source, p_payload);
    RETURN NEXT;
END
$fn$;
ALTER FUNCTION app._append_event(uuid, uuid, text, text, jsonb) OWNER TO app_definer;
"""

TRANSITION_HELPER = f"""
CREATE OR REPLACE FUNCTION app._transition(p_run_id uuid, p_dst text, p_performer text, p_reason text,
                                           p_expected_version integer, p_event text, p_event_payload jsonb)
RETURNS integer
{HELPER_HEADER} AS $fn$
DECLARE
    v_run runs%ROWTYPE;
    v_row transitions%ROWTYPE;
    v_version integer;
    v_active text[] := ARRAY['QUEUED', 'AWAITING_INPUT', 'RETRIEVING', 'DRAFTING', 'AWAITING_APPROVAL', 'APPROVED',
                             'EXECUTING', 'OUTCOME_UNKNOWN'];
BEGIN
    SELECT * INTO v_run FROM runs WHERE runs.run_id = p_run_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'not_found' USING ERRCODE = 'OC002', DETAIL = 'run';
    END IF;
    IF p_expected_version IS NOT NULL AND v_run.state_version <> p_expected_version THEN
        RAISE EXCEPTION 'version_conflict' USING ERRCODE = 'OC003',
            DETAIL = format('run %s is at version %s', p_run_id, v_run.state_version);
    END IF;
    -- The T07 table as data (ruling 10): no row, no transition; a row with reasons needs one of them.
    SELECT * INTO v_row FROM transitions WHERE src = v_run.state AND dst = p_dst AND performer = p_performer;
    IF NOT FOUND OR (cardinality(v_row.reasons) > 0 AND NOT (coalesce(p_reason, '') = ANY (v_row.reasons)))
       OR (cardinality(v_row.reasons) = 0 AND p_reason IS NOT NULL) THEN
        -- R082's logged half: this ERROR reaches the server log, and the caller logs it before re-raising.
        RAISE EXCEPTION 'illegal_transition' USING ERRCODE = 'OC004',
            DETAIL = format('run %s: %s -> %s by %s (reason %s) is not a row', p_run_id, v_run.state, p_dst, p_performer,
                            coalesce(p_reason, 'none'));
    END IF;
    v_version := v_run.state_version + 1;
    UPDATE runs SET state = p_dst, state_version = v_version, reason = p_reason, slot_held = (p_dst = ANY (v_active)),
                    updated_at = app.current_time()
    WHERE runs.run_id = p_run_id;
    INSERT INTO run_state_history (tenant_id, run_id, seq, from_state, to_state, performer, reason, at)
    VALUES (v_run.tenant_id, p_run_id, v_version, v_run.state, p_dst, p_performer, p_reason, app.current_time());
    IF p_event IS NOT NULL THEN
        PERFORM app._append_event(v_run.tenant_id, p_run_id, p_event, 'application',
                                  coalesce(p_event_payload, '{{}}'::jsonb));
    END IF;
    RETURN v_version;
END
$fn$;
ALTER FUNCTION app._transition(uuid, text, text, text, integer, text, jsonb) OWNER TO app_definer;
"""

CREATE_RUN = f"""
CREATE OR REPLACE FUNCTION app.create_run(p_tenant_id uuid, p_conversation_id uuid, p_request jsonb, p_intent text,
                                          p_supersedes_run_id uuid)
RETURNS TABLE (run_id uuid, state_version integer)
{HEADER} AS $fn$
DECLARE
    v_message_id uuid := (p_request->>'message_id')::uuid;
    v_requester uuid := (p_request->>'requester')::uuid;
    v_run_id uuid := gen_random_uuid();
BEGIN
    PERFORM app._authority('create_run', ARRAY['api']);
    -- The API is the identity trust anchor (SA:450): the tenant is an argument, set here, never read from the caller.
    PERFORM set_config('app.tenant_id', p_tenant_id::text, true);
    IF p_intent NOT IN ('investigate', 'answer_only') THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'INVALID_ARGUMENT';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM conversations c WHERE c.conversation_id = p_conversation_id AND c.tenant_id = p_tenant_id) THEN
        RAISE EXCEPTION 'not_found' USING ERRCODE = 'OC002', DETAIL = 'conversation';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM messages m WHERE m.message_id = v_message_id AND m.conversation_id = p_conversation_id
                                                  AND m.tenant_id = p_tenant_id) THEN
        RAISE EXCEPTION 'not_found' USING ERRCODE = 'OC002', DETAIL = 'message';
    END IF;
    IF p_supersedes_run_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM runs r WHERE r.run_id = p_supersedes_run_id AND r.tenant_id = p_tenant_id
                               AND r.conversation_id = p_conversation_id) THEN
        RAISE EXCEPTION 'not_found' USING ERRCODE = 'OC002', DETAIL = 'supersedes_run_id';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM transitions t WHERE t.src = '' AND t.dst = 'QUEUED' AND t.performer = 'create_run') THEN
        RAISE EXCEPTION 'illegal_transition' USING ERRCODE = 'OC004', DETAIL = 'creation row missing';
    END IF;
    BEGIN
        INSERT INTO runs (run_id, tenant_id, conversation_id, message_id, requester, intent, supersedes_run_id, asset_id,
                          start_at, end_at, state, state_version, slot_held, next_event_seq)
        VALUES (v_run_id, p_tenant_id, p_conversation_id, v_message_id, v_requester, p_intent, p_supersedes_run_id,
                p_request->>'asset_id', (p_request->>'start_at')::timestamptz, (p_request->>'end_at')::timestamptz,
                'QUEUED', 1, true, 0);
    EXCEPTION WHEN unique_violation THEN
        -- The partial unique index on (conversation_id) WHERE slot_held is the slot rule (BUILD_SPEC §7).
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'SLOT_OCCUPIED';
    END;
    INSERT INTO run_directory (run_id, tenant_id) VALUES (v_run_id, p_tenant_id);
    INSERT INTO run_state_history (tenant_id, run_id, seq, from_state, to_state, performer, at)
    VALUES (p_tenant_id, v_run_id, 1, NULL, 'QUEUED', 'create_run', app.current_time());
    -- format('%s:1', ...), never a quote-colon-digit literal: SQLAlchemy reads a colon after a quote as a bind
    -- (round-1 B2); the plan's unit test scans every revision string, comments included.
    INSERT INTO jobs (id, type, tenant_id, run_id, dedup_key)
    VALUES (gen_random_uuid(), 'investigate', p_tenant_id, v_run_id, format('%s:1', v_run_id));
    PERFORM app._append_event(p_tenant_id, v_run_id, 'run.accepted', 'application', '{{}}'::jsonb);
    run_id := v_run_id;
    state_version := 1;
    RETURN NEXT;
END
$fn$;
ALTER FUNCTION app.create_run(uuid, uuid, jsonb, text, uuid) OWNER TO app_definer;
"""

TRANSITION_RUN = f"""
CREATE OR REPLACE FUNCTION app.transition_run(p_run_id uuid, p_from text, p_to text, p_reason text,
                                              p_expected_version integer, p_detail jsonb)
RETURNS integer
{HEADER} AS $fn$
DECLARE
    v_tenant uuid;
    v_state text;
    v_event text;
BEGIN
    PERFORM app._authority('transition_run', ARRAY['worker']);
    v_tenant := app._tenant_of_run(p_run_id);
    -- Never a post-grant state and never SUCCEEDED (SA:451); the table decides the rest.
    IF p_to NOT IN ('RETRIEVING', 'DRAFTING', 'AWAITING_INPUT', 'ANSWERED', 'INSUFFICIENT_EVIDENCE', 'FAILED', 'QUEUED') THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'POST_GRANT_TARGET';
    END IF;
    SELECT state INTO v_state FROM runs WHERE run_id = p_run_id FOR UPDATE;
    IF v_state IS DISTINCT FROM p_from THEN
        RAISE EXCEPTION 'version_conflict' USING ERRCODE = 'OC003', DETAIL = format('run %s is %s', p_run_id, v_state);
    END IF;
    v_event := CASE p_to
        WHEN 'FAILED' THEN 'run.failed'
        WHEN 'INSUFFICIENT_EVIDENCE' THEN 'run.insufficient_evidence'
        WHEN 'ANSWERED' THEN 'run.answered'
        WHEN 'AWAITING_INPUT' THEN 'clarification.requested'
        ELSE NULL END;
    RETURN app._transition(p_run_id, p_to, 'transition_run', p_reason, p_expected_version, v_event,
                           coalesce(p_detail, '{{}}'::jsonb));
END
$fn$;
ALTER FUNCTION app.transition_run(uuid, text, text, text, integer, jsonb) OWNER TO app_definer;
"""

APPEND_EVENT = f"""
CREATE OR REPLACE FUNCTION app.append_event(p_run_id uuid, p_type text, p_payload jsonb, p_source text)
RETURNS TABLE (event_id uuid, sequence integer, occurred_at timestamptz)
{HEADER} AS $fn$
DECLARE
    v_tenant uuid;
    v_source text := coalesce(p_source, 'application');
BEGIN
    PERFORM app._authority('append_event', ARRAY['api', 'worker', 'sweeper']);
    v_tenant := app._tenant_of_run(p_run_id);
    -- Only the definer functions emit run.*, action.*, review.*, proposal.*, approval.* and clarification.requested
    -- (SA:452 names the first three; ruling 5 closes the rest); the source is the caller's identity,
    -- except that the worker may relay the model's summary (SA:321).
    IF p_type LIKE 'run.%' OR p_type LIKE 'action.%' OR p_type LIKE 'review.%' OR p_type LIKE 'proposal.%'
       OR p_type LIKE 'approval.%' OR p_type = 'clarification.requested' THEN
        RAISE EXCEPTION 'event_rule_violation' USING ERRCODE = 'OC006', DETAIL = 'reserved type';
    END IF;
    IF v_source <> 'application' AND NOT (v_source = 'model_summary' AND session_user::text = 'worker') THEN
        RAISE EXCEPTION 'event_rule_violation' USING ERRCODE = 'OC006', DETAIL = 'source';
    END IF;
    RETURN QUERY SELECT * FROM app._append_event(v_tenant, p_run_id, p_type, v_source, p_payload);
END
$fn$;
ALTER FUNCTION app.append_event(uuid, text, jsonb, text) OWNER TO app_definer;
"""

RESOLVE_IDENTITY = f"""
CREATE OR REPLACE FUNCTION app.resolve_identity(p_issuer text, p_subject uuid)
RETURNS TABLE (tenant_id uuid, role text)
{HEADER} AS $fn$
DECLARE
    v_tenant uuid;
BEGIN
    PERFORM app._authority('resolve_identity', ARRAY['api']);
    -- No policy admits a tenant-less read of memberships (SA:520), so the function walks the RLS-free tenants
    -- table and sets each tenant in turn, the pattern SA:520 prescribes for the sweeper (Plan E ruling 4).
    FOR v_tenant IN SELECT t.tenant_id FROM tenants t ORDER BY t.tenant_id LOOP
        PERFORM set_config('app.tenant_id', v_tenant::text, true);
        RETURN QUERY SELECT m.tenant_id, m.role FROM memberships m
                     WHERE m.issuer = p_issuer AND m.subject = p_subject AND m.active ORDER BY m.role;
    END LOOP;
END
$fn$;
ALTER FUNCTION app.resolve_identity(text, uuid) OWNER TO app_definer;
"""

REVOKE_HANDLES = f"""
CREATE OR REPLACE FUNCTION app.revoke_handles(p_run_id uuid, p_fence bigint) RETURNS integer
{HEADER} AS $fn$
DECLARE
    v_count integer;
BEGIN
    PERFORM app._authority('revoke_handles', ARRAY['worker']);
    PERFORM app._tenant_of_run(p_run_id);
    -- TODO(T13): compare p_fence with run_lease.fence once leases exist; until then every live handle of the run goes.
    UPDATE invocation_context SET revoked_at = app.current_time() WHERE run_id = p_run_id AND revoked_at IS NULL;
    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END
$fn$;
ALTER FUNCTION app.revoke_handles(uuid, bigint) OWNER TO app_definer;
"""

FUNCTIONS = (
    ("_authority", AUTHORITY),
    ("_tenant_of_run", TENANT_OF_RUN),
    ("_append_event", APPEND_EVENT_HELPER),
    ("_transition", TRANSITION_HELPER),
    ("create_run", CREATE_RUN),
    ("transition_run", TRANSITION_RUN),
    ("append_event", APPEND_EVENT),
    ("resolve_identity", RESOLVE_IDENTITY),
    ("revoke_handles", REVOKE_HANDLES),
)


def upgrade() -> None:
    for name, body in FUNCTIONS:
        op.execute(body)
        for statement in privileges.function_grant_statements(name):
            op.execute(statement)


def downgrade() -> None:
    for name, _ in reversed(FUNCTIONS):
        args = privileges.HELPER_FUNCTIONS.get(name) or privileges.DEFINER_FUNCTIONS[name][0]
        op.execute(f"DROP FUNCTION app.{name}({args})")
```

Notes for the implementer:
- The f-strings double every literal brace: `'{{}}'::jsonb` renders as `'{}'::jsonb`. The `%` characters in `format(...)` and `LIKE 'run.%'` are fine: SQLAlchemy's `text()` doubles them and psycopg un-doubles them when no parameters are bound (fact sheet §4.3, measured in round 1). A colon followed by a word is a bind unless it follows a word character or another colon: write `format('%s:1', …)`, never `|| ':1'`.
- `RETURN NEXT` with `RETURNS TABLE` assigns the output columns by name; the local variable names (`v_*`) never shadow them, and `runs.run_id` is qualified wherever an output column has the same name.
- `_transition` emits application-sourced events only; Task 4's `record_outcome` passes its destination-sourced events through `_append_event` directly and calls `_transition` with `p_event = NULL`.

- [ ] **Step 4: Format, then run the live tests**

Run: `uv run ruff format migrations/app/versions/0003_run_path_functions.py tests/plan_e/test_transitions_table.py tests/e2e/test_definers_run_path_live.py && uv run ruff check --fix migrations tests/plan_e tests/e2e && uv run python -m pytest tests/plan_e/test_transitions_table.py -q`, then `OPS_LIVE=1 PYTHONUTF8=1 uv run python -m pytest tests/e2e/test_definers_run_path_live.py tests/e2e/test_roles_live.py -q -x` and, from the persistence module, only its two Task 2 tests: `OPS_LIVE=1 PYTHONUTF8=1 uv run python -m pytest tests/e2e/test_migrations_and_persistence.py -q -k "idempotent or r006"`.
Expected: PASS (the Plan D tests in `test_migrations_and_persistence.py` stay red until Task 5, as declared). The R124 test still passes: functions carry no table grants. If `test_function_catalog_shape` shows an ACL with a `=X/app_definer` entry for PUBLIC, the `REVOKE … FROM PUBLIC` ran before the `CREATE OR REPLACE` recreated the function; the order in `upgrade()` (body first, then grants) is what makes it correct.

- [ ] **Step 5: Gate and commit**

`PYTHONUTF8=1 uv run python scripts/check.py` → GREEN.

```bash
git add migrations/app/versions/0003_run_path_functions.py tests/plan_e/test_transitions_table.py tests/e2e/test_definers_run_path_live.py
git commit -m "feat(migrations): the run-path definer functions (create_run, transition_run, append_event, resolve_identity, revoke_handles) (T09)"
```

---
### Task 4: Revision 0004 — the approval and write-path definer functions

**Files:**
- Create: `migrations/app/versions/0004_write_path_functions.py`, `tests/e2e/test_definers_write_path_live.py`

**Interfaces:**
- Consumes: revision 0003's helpers (`_authority`, `_tenant_of_run`, `_append_event`, `_transition`), `app.current_time()`, `ops_core.privileges`.
- Produces (SQL, schema `app`):
  - `_tenant_of_action(p_action_id uuid) RETURNS uuid` — iterates `tenants` and sets the one whose `execution_grant` holds the action (`OC002` if none).
  - `_latest_attempt(p_action_id uuid) RETURNS TABLE (attempt_no integer, seq integer, state text, outcome text, detail jsonb)` — the newest `action_attempt_state` row (by `attempt_no DESC, seq DESC`), or no row.
  - `_resolve_handle(p_raw_handle text, p_client_azp text, p_server text) RETURNS TABLE (run_id uuid, job_id uuid, job_type text, tenant_id uuid, conversation_id uuid, run_state text, attempt_state text)` — hashes the handle, checks revocation, expiry (`app.current_time()`), `azp`, the job type's server against `p_server` and the stored column (`OC008` for every refusal, same message), sets the tenant.
  - `freeze_proposal(p_run_id uuid, p_draft_id uuid, p_payload_canonical bytea, p_expires_at timestamptz) RETURNS TABLE (proposal_id uuid, revision integer, state_version integer)` — callers `worker`.
  - `record_decision(p_tenant_id uuid, p_proposal_id uuid, p_reviewer uuid, p_expected_payload_sha256 text, p_decision text, p_reason text, p_idempotency_key text) RETURNS TABLE (run_id uuid, state text, state_version integer)` — callers `api`.
  - `resolve_invocation(p_raw_handle text, p_client_azp text) RETURNS TABLE (…as `_resolve_handle`…)` — callers `mcp_read` (read handles), `mcp_exec` (write handles).
  - `grant_execution(p_raw_handle text, p_proposal_id uuid) RETURNS TABLE (action_id uuid, run_id uuid, proposal_id uuid, tenant_id uuid, conversation_id uuid, payload_sha256 text, payload_canonical bytea, attempt_state text, detail jsonb)` — callers `mcp_exec`.
  - `lookup_action(p_raw_handle text) RETURNS TABLE (…same as grant_execution…)` — callers `mcp_exec`; `OC002` when the run has no grant.
  - `mark_sent(p_action_id uuid) RETURNS text` (`sent` | `already_sent` | `resolved` | `cancelled`) — callers `mcp_exec`.
  - `record_outcome(p_action_id uuid, p_outcome text, p_document jsonb) RETURNS text` (the outcome that stands) — callers `mcp_exec`.
  - `mark_unknown(p_run_id uuid, p_fence bigint) RETURNS text` (the run's state afterwards) — callers `worker`.

- [ ] **Step 1: Write the failing live tests**

Create `tests/e2e/test_definers_write_path_live.py`:

```python
"""The approval and write-path definer functions as their callers (OPS_LIVE=1; AM-20.3 rows 4, 5, 10, 13–15, 17, 18;
R106 cross-tenant; R128 for mcp_exec).

Catches: a frozen proposal whose bytes differ from the validated draft (hash), a self-review or a non-reviewer
approving, a second decision, a handle resolved at the wrong server or after expiry, a grant for another tenant's
proposal through a handle, a second grant for one run, SENT written twice, an outcome recorded twice or with a
foreign hash, UNKNOWN recorded by anyone but the worker, and a preset tenant leaking through any of them.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import psycopg
import pytest
from ops_core import persistence
from ops_core.canonical import canonical_json, sha256_hex
from ops_core.outcomes import EventSource, EventType, event_rules_ok
from ops_core.settings import Role
from psycopg.types.json import Jsonb

from tests.e2e.conftest import purge_run
from tests.e2e.test_definers_run_path_live import ALEX, ALPHA, BETA, as_role, conversation, create, refused

pytestmark = pytest.mark.asyncio

RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
SAM = UUID("03f7eb09-e18d-5f33-bf75-12c57d5aaa54")
JORDAN = UUID("cb551e64-83ec-582b-9047-8dadf20e151a")
LEE = UUID("abcc1200-6791-57ab-87b5-9392d356b512")


def payload_for(tenant: UUID, run: UUID, proposal: UUID, now: datetime) -> bytes:
    """A canonical proposal document with the fields the functions read (the full contract is Plan C's)."""
    return canonical_json(
        {
            "tenant_id": str(tenant),
            "run_id": str(run),
            "proposal_id": str(proposal),
            "revision": 1,
            "action": "create_incident",
            "destination": "synthetic-incidents",
            "asset_id": "A17",
            "title": "t",
            "summary": "s",
            "supersedes_run_id": None,
            "expires_at": (now + timedelta(minutes=15)).isoformat().replace("+00:00", "Z"),
        }
    )


async def drafting_run(app_conn: persistence.Conn, api: persistence.Conn, worker: persistence.Conn, tenant: UUID = ALPHA) -> UUID:
    conv, msg = await conversation(app_conn, tenant)
    async with as_role(api):
        run = await create(api, tenant, conv, msg)
    async with as_role(worker):
        await worker.execute("SELECT app.transition_run(%s, 'QUEUED', 'RETRIEVING', NULL, 1, '{}')", (run,))
        await worker.execute("SELECT app.transition_run(%s, 'RETRIEVING', 'DRAFTING', NULL, 2, '{}')", (run,))
    return run


async def freeze(app_conn: persistence.Conn, worker: persistence.Conn, run: UUID, tenant: UUID = ALPHA) -> tuple[UUID, bytes, str]:
    now = datetime.now(UTC).replace(microsecond=0)
    proposal, draft = uuid4(), uuid4()
    body = payload_for(tenant, run, proposal, now)
    digest = sha256_hex(body)
    async with as_role(worker):  # the worker's own INSERT on drafts (AM-20.2) under its tenant, then the function
        await worker.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant),))
        await worker.execute(
            "INSERT INTO app.drafts (id, tenant_id, run_id, draft_sha256, validated, kind) VALUES (%s, %s, %s, %s, true, 'proposal')",
            (draft, tenant, run, digest),
        )
        cur = await worker.execute("SELECT * FROM app.freeze_proposal(%s, %s, %s, %s)", (run, draft, body, now + timedelta(minutes=15)))
        row = await cur.fetchone()
        assert row is not None and row["proposal_id"] == proposal and row["revision"] == 1 and row["state_version"] == 4
    return proposal, body, digest


async def approve(api: persistence.Conn, proposal: UUID, digest: str, reviewer: UUID = SAM, tenant: UUID = ALPHA) -> dict:
    async with as_role(api):
        cur = await api.execute(
            "SELECT * FROM app.record_decision(%s, %s, %s, %s, 'approve', NULL, NULL)", (tenant, proposal, reviewer, digest)
        )
        return dict(await cur.fetchone())


async def handle_for(app_conn: persistence.Conn, run: UUID, job_type: str, *, expires_in: int = 60) -> str:
    """A raw handle whose hash the superuser inserts (the worker's INSERT is proved in Task 6's live test)."""
    raw = f"handle-{uuid4().hex}"
    job = (await (await app_conn.execute("SELECT id FROM app.jobs WHERE run_id = %s AND type = %s", (run, job_type))).fetchone())["id"]
    await app_conn.execute(
        "INSERT INTO app.invocation_context (handle_sha256, run_id, job_id, server, azp, expires_at)"
        " VALUES (%s, %s, %s, %s, 'ops-worker', now() + make_interval(secs => %s))",
        (sha256_hex(raw.encode()), run, job, "write" if job_type in ("execute", "recover") else "read", expires_in),
    )
    return raw


async def test_freeze_proposal_binds_bytes_to_the_draft_and_refuses_the_rest(app_conn: persistence.Conn, role_conn: RoleConn) -> None:
    api, worker = await role_conn(Role.API), await role_conn(Role.WORKER)
    run = await drafting_run(app_conn, api, worker)
    try:
        now = datetime.now(UTC).replace(microsecond=0)
        proposal, draft = uuid4(), uuid4()
        body = payload_for(ALPHA, run, proposal, now)
        await app_conn.execute(
            "INSERT INTO app.drafts (id, tenant_id, run_id, draft_sha256, validated, kind) VALUES (%s, %s, %s, %s, true, 'proposal')",
            (draft, ALPHA, run, "0" * 64),  # a draft whose hash is not the bytes'
        )
        assert await refused(worker, "SELECT * FROM app.freeze_proposal(%s, %s, %s, %s)", (run, draft, body, now)) == "OC007"
        await app_conn.execute("UPDATE app.drafts SET draft_sha256 = %s WHERE id = %s", (sha256_hex(body), draft))
        foreign = payload_for(ALPHA, uuid4(), proposal, now)  # the payload names another run, hashed correctly
        foreign_draft = uuid4()
        await app_conn.execute(
            "INSERT INTO app.drafts (id, tenant_id, run_id, draft_sha256, validated, kind) VALUES (%s, %s, %s, %s, true, 'proposal')",
            (foreign_draft, ALPHA, run, sha256_hex(foreign)),
        )
        assert await refused(worker, "SELECT * FROM app.freeze_proposal(%s, %s, %s, %s)", (run, foreign_draft, foreign, now)) == "OC005"  # PAYLOAD_RUN_MISMATCH
        assert await refused(api, "SELECT * FROM app.freeze_proposal(%s, %s, %s, %s)", (run, draft, body, now)) == "42501"
        assert await refused(app_conn, "SELECT * FROM app.freeze_proposal(%s, %s, %s, %s)", (run, draft, body, now)) == "OC001"
        async with as_role(worker):
            cur = await worker.execute("SELECT * FROM app.freeze_proposal(%s, %s, %s, %s)", (run, draft, body, now + timedelta(minutes=15)))
            assert (await cur.fetchone())["revision"] == 1
        row = await (await app_conn.execute("SELECT state, active_proposal_id, slot_held FROM app.runs WHERE run_id = %s", (run,))).fetchone()
        assert dict(row) == {"state": "AWAITING_APPROVAL", "active_proposal_id": proposal, "slot_held": True}
        stored = await (await app_conn.execute("SELECT payload_canonical, payload_sha256, authored_by, canonicalization_version FROM app.proposals WHERE proposal_id = %s", (proposal,))).fetchone()
        assert bytes(stored["payload_canonical"]) == body and stored["payload_sha256"] == sha256_hex(body)
        assert stored["authored_by"] == [ALEX] and stored["canonicalization_version"] == 1
        events = await (await app_conn.execute("SELECT type FROM app.events WHERE run_id = %s ORDER BY sequence", (run,))).fetchall()
        assert [e["type"] for e in events] == ["run.accepted", "proposal.ready"]
        assert await refused(worker, "SELECT * FROM app.freeze_proposal(%s, %s, %s, %s)", (run, draft, body, now)) == "OC003"  # not DRAFTING any more
    finally:
        await purge_run(app_conn, run)


async def test_record_decision_independence_hash_and_first_wins(app_conn: persistence.Conn, role_conn: RoleConn) -> None:
    api, worker = await role_conn(Role.API), await role_conn(Role.WORKER)
    run = await drafting_run(app_conn, api, worker)
    try:
        proposal, _, digest = await freeze(app_conn, worker, run)
        call = "SELECT * FROM app.record_decision(%s, %s, %s, %s, 'approve', NULL, NULL)"
        assert await refused(api, call, (ALPHA, proposal, ALEX, digest)) == "OC005"  # the requester (SELF_REVIEW)
        assert await refused(api, call, (ALPHA, proposal, LEE, digest)) == "OC005"  # a reader (NOT_REVIEWER)
        assert await refused(api, call, (ALPHA, proposal, JORDAN, digest)) == "OC005"  # beta's reviewer (NOT_REVIEWER)
        assert await refused(api, call, (BETA, proposal, JORDAN, digest)) == "OC002"  # through beta: not found, no leak
        assert await refused(api, call, (ALPHA, proposal, SAM, "0" * 64)) == "OC003"  # a stale hash
        assert await refused(worker, call, (ALPHA, proposal, SAM, digest)) == "42501"
        decided = await approve(api, proposal, digest)
        assert decided == {"run_id": run, "state": "APPROVED", "state_version": 5}
        assert await refused(api, call, (ALPHA, proposal, SAM, digest)) == "OC003"  # the first decision won
        jobs = await (await app_conn.execute("SELECT type, dedup_key FROM app.jobs WHERE run_id = %s ORDER BY created_at", (run,))).fetchall()
        assert [(j["type"], j["dedup_key"]) for j in jobs] == [("investigate", f"{run}:1"), ("execute", str(proposal))]
        events = await (await app_conn.execute("SELECT type FROM app.events WHERE run_id = %s ORDER BY sequence", (run,))).fetchall()
        assert [e["type"] for e in events] == ["run.accepted", "proposal.ready", "approval.recorded"]
        decision = await (await app_conn.execute("SELECT tenant_id, reviewer, decision, expected_payload_sha256 FROM app.decisions WHERE proposal_id = %s", (proposal,))).fetchone()
        assert dict(decision) == {"tenant_id": ALPHA, "reviewer": SAM, "decision": "approve", "expected_payload_sha256": digest}
    finally:
        await purge_run(app_conn, run)


async def test_rejection_frees_the_slot(app_conn: persistence.Conn, role_conn: RoleConn) -> None:
    api, worker = await role_conn(Role.API), await role_conn(Role.WORKER)
    run = await drafting_run(app_conn, api, worker)
    try:
        proposal, _, digest = await freeze(app_conn, worker, run)
        async with as_role(api):
            cur = await api.execute("SELECT * FROM app.record_decision(%s, %s, %s, %s, 'reject', 'rejected', NULL)", (ALPHA, proposal, SAM, digest))
            assert dict(await cur.fetchone()) == {"run_id": run, "state": "REJECTED", "state_version": 5}
        row = await (await app_conn.execute("SELECT slot_held, reason FROM app.runs WHERE run_id = %s", (run,))).fetchone()
        assert dict(row) == {"slot_held": False, "reason": "rejected"}
        events = await (await app_conn.execute("SELECT type FROM app.events WHERE run_id = %s ORDER BY sequence", (run,))).fetchall()
        assert [e["type"] for e in events][-1] == "run.rejected"
    finally:
        await purge_run(app_conn, run)


async def test_resolve_invocation_binds_server_azp_expiry_and_revocation(app_conn: persistence.Conn, role_conn: RoleConn) -> None:
    api, worker, mcp_read, mcp_exec = [await role_conn(r) for r in (Role.API, Role.WORKER, Role.MCP_READ, Role.MCP_EXEC)]
    run = await drafting_run(app_conn, api, worker)
    try:
        read_handle = await handle_for(app_conn, run, "investigate")
        async with as_role(mcp_read, preset=BETA):
            cur = await mcp_read.execute("SELECT * FROM app.resolve_invocation(%s, 'ops-worker')", (read_handle,))
            row = dict(await cur.fetchone())
            assert (row["run_id"], row["job_type"], row["tenant_id"], row["run_state"], row["attempt_state"]) == (run, "investigate", ALPHA, "DRAFTING", None)
            assert (await (await mcp_read.execute("SELECT current_setting('app.tenant_id', true) AS t")).fetchone())["t"] == str(BETA)
        assert await refused(mcp_exec, "SELECT * FROM app.resolve_invocation(%s, 'ops-worker')", (read_handle,)) == "OC008"  # a read handle at the write server
        assert await refused(mcp_read, "SELECT * FROM app.resolve_invocation(%s, 'ops-web')", (read_handle,)) == "OC008"  # another workload
        assert await refused(mcp_read, "SELECT * FROM app.resolve_invocation(%s, 'ops-worker')", ("not-a-handle",)) == "OC008"
        assert await refused(api, "SELECT * FROM app.resolve_invocation(%s, 'ops-worker')", (read_handle,)) == "42501"
        expired = await handle_for(app_conn, run, "investigate", expires_in=-1)
        assert await refused(mcp_read, "SELECT * FROM app.resolve_invocation(%s, 'ops-worker')", (expired,)) == "OC008"
        async with as_role(worker):
            await worker.execute("SELECT app.revoke_handles(%s, 1)", (run,))
        assert await refused(mcp_read, "SELECT * FROM app.resolve_invocation(%s, 'ops-worker')", (read_handle,)) == "OC008"
    finally:
        await purge_run(app_conn, run)


async def test_write_path_grant_sent_outcome_once_and_only_once(app_conn: persistence.Conn, role_conn: RoleConn) -> None:
    api, worker, mcp_exec = [await role_conn(r) for r in (Role.API, Role.WORKER, Role.MCP_EXEC)]
    run = await drafting_run(app_conn, api, worker)
    try:
        proposal, body, digest = await freeze(app_conn, worker, run)
        await approve(api, proposal, digest)
        handle = await handle_for(app_conn, run, "execute")
        # Gate refusals leave no grant: another proposal id, then the real one.
        assert await refused(mcp_exec, "SELECT * FROM app.grant_execution(%s, %s)", (handle, uuid4())) == "OC005"
        assert (await (await app_conn.execute("SELECT count(*) AS n FROM app.execution_grant WHERE run_id = %s", (run,))).fetchone())["n"] == 0
        async with as_role(mcp_exec, preset=BETA):
            cur = await mcp_exec.execute("SELECT * FROM app.grant_execution(%s, %s)", (handle, proposal))
            grant = dict(await cur.fetchone())
            assert grant["tenant_id"] == ALPHA and grant["attempt_state"] == "INTENT" and bytes(grant["payload_canonical"]) == body
            assert grant["payload_sha256"] == digest and grant["detail"] is None
            cur = await mcp_exec.execute("SELECT * FROM app.grant_execution(%s, %s)", (handle, proposal))  # replay: the same grant
            assert dict(await cur.fetchone())["action_id"] == grant["action_id"]
            assert (await (await mcp_exec.execute("SELECT current_setting('app.tenant_id', true) AS t")).fetchone())["t"] == str(BETA)
        assert await refused(mcp_exec, "SELECT * FROM app.grant_execution(%s, %s)", (handle, uuid4())) == "OC005"  # OTHER_PROPOSAL
        assert await refused(worker, "SELECT * FROM app.grant_execution(%s, %s)", (handle, proposal)) == "42501"
        row = await (await app_conn.execute("SELECT state, state_version FROM app.runs WHERE run_id = %s", (run,))).fetchone()
        assert dict(row) == {"state": "EXECUTING", "state_version": 6}
        action = grant["action_id"]
        async with as_role(mcp_exec, preset=BETA):  # a hostile preset: ignored by mark_sent/lookup_action and restored
            assert (await (await mcp_exec.execute("SELECT app.mark_sent(%s) AS r", (action,))).fetchone())["r"] == "sent"
            assert (await (await mcp_exec.execute("SELECT app.mark_sent(%s) AS r", (action,))).fetchone())["r"] == "already_sent"
            cur = await mcp_exec.execute("SELECT * FROM app.lookup_action(%s)", (handle,))
            assert dict(await cur.fetchone())["attempt_state"] == "SENT"
            assert (await (await mcp_exec.execute("SELECT current_setting('app.tenant_id', true) AS t")).fetchone())["t"] == str(BETA)
        states = await (await app_conn.execute("SELECT seq, state FROM app.action_attempt_state WHERE action_id = %s ORDER BY seq", (action,))).fetchall()
        assert [(s["seq"], s["state"]) for s in states] == [(1, "INTENT"), (2, "SENT")]
        assert await refused(mcp_exec, "SELECT app.record_outcome(%s, 'SUCCEEDED', %s)", (action, Jsonb({"status": "SUCCEEDED", "action_id": str(action), "payload_sha256": "0" * 64, "receipt": {"receipt_id": str(uuid4()), "incident_id": "INC-1", "committed_at": "2026-10-08T12:00:00Z"}}))) == "OC007"
        receipt = {"receipt_id": str(uuid4()), "incident_id": "INC-000009", "committed_at": "2026-10-08T12:00:00Z"}
        document = {"status": "SUCCEEDED", "action_id": str(action), "payload_sha256": digest, "receipt": receipt, "tombstone": None, "reason": None}
        async with as_role(mcp_exec, preset=BETA):
            assert (await (await mcp_exec.execute("SELECT app.record_outcome(%s, 'SUCCEEDED', %s) AS r", (action, Jsonb(document)))).fetchone())["r"] == "SUCCEEDED"
            assert (await (await mcp_exec.execute("SELECT current_setting('app.tenant_id', true) AS t")).fetchone())["t"] == str(BETA)
            # Idempotent: a second record (even a different one) returns what stands.
            assert (await (await mcp_exec.execute("SELECT app.record_outcome(%s, 'CONFLICT', %s) AS r", (action, Jsonb({"status": "CONFLICT", "action_id": str(action), "payload_sha256": digest})))).fetchone())["r"] == "SUCCEEDED"
            assert (await (await mcp_exec.execute("SELECT app.mark_sent(%s) AS r", (action,))).fetchone())["r"] == "resolved"
            cur = await mcp_exec.execute("SELECT * FROM app.lookup_action(%s)", (handle,))
            final = dict(await cur.fetchone())
            assert final["attempt_state"] == "RESOLVED" and final["detail"]["receipt"] == receipt
        row = await (await app_conn.execute("SELECT state, slot_held FROM app.runs WHERE run_id = %s", (run,))).fetchone()
        assert dict(row) == {"state": "SUCCEEDED", "slot_held": False}
        events = await (await app_conn.execute("SELECT type, source FROM app.events WHERE run_id = %s ORDER BY sequence", (run,))).fetchall()
        assert [(e["type"], e["source"]) for e in events] == [
            ("run.accepted", "application"), ("proposal.ready", "application"), ("approval.recorded", "application"),
            ("action.granted", "application"), ("action.dispatched", "application"), ("action.confirmed", "destination"),
        ]
        assert await refused(worker, "SELECT app.mark_unknown(%s, 1)", (run,)) == "OC003"  # a terminal run is not EXECUTING
        # The SQL rules and their Python twin agree on every row the functions wrote (round-1 finding I5).
        rows = await (await app_conn.execute("SELECT type, source, payload FROM app.events WHERE run_id = %s", (run,))).fetchall()
        for e in rows:
            event_rules_ok(EventType(e["type"]), EventSource(e["source"]), e["payload"])
    finally:
        await purge_run(app_conn, run)


async def test_mark_unknown_is_worker_only_revokes_handles_and_enqueues_recover(app_conn: persistence.Conn, role_conn: RoleConn) -> None:
    api, worker, mcp_exec = [await role_conn(r) for r in (Role.API, Role.WORKER, Role.MCP_EXEC)]
    run = await drafting_run(app_conn, api, worker)
    try:
        proposal, _, digest = await freeze(app_conn, worker, run)
        await approve(api, proposal, digest)
        handle = await handle_for(app_conn, run, "execute")
        async with as_role(mcp_exec):
            grant = dict(await (await mcp_exec.execute("SELECT * FROM app.grant_execution(%s, %s)", (handle, proposal))).fetchone())
            await mcp_exec.execute("SELECT app.mark_sent(%s)", (grant["action_id"],))
        assert await refused(mcp_exec, "SELECT app.mark_unknown(%s, 1)", (run,)) == "42501"  # SA:467: the worker's call
        async with as_role(worker, preset=BETA):
            assert (await (await worker.execute("SELECT app.mark_unknown(%s, 1) AS s", (run,))).fetchone())["s"] == "OUTCOME_UNKNOWN"
            assert (await (await worker.execute("SELECT app.mark_unknown(%s, 1) AS s", (run,))).fetchone())["s"] == "OUTCOME_UNKNOWN"  # idempotent
            assert (await (await worker.execute("SELECT current_setting('app.tenant_id', true) AS t")).fetchone())["t"] == str(BETA)
        assert await refused(mcp_exec, "SELECT * FROM app.lookup_action(%s)", (handle,)) == "OC008"  # the handle was revoked
        jobs = await (await app_conn.execute("SELECT type, dedup_key FROM app.jobs WHERE run_id = %s ORDER BY created_at", (run,))).fetchall()
        assert jobs[-1]["type"] == "recover" and jobs[-1]["dedup_key"] == f"{grant['action_id']}:timeout"
        events = await (await app_conn.execute("SELECT type FROM app.events WHERE run_id = %s ORDER BY sequence", (run,))).fetchall()
        assert [e["type"] for e in events][-2:] == ["action.dispatched", "action.uncertain"]
        # A late outcome still resolves the attempt and the run (SA:464): OUTCOME_UNKNOWN → SUCCEEDED.
        new_handle = await handle_for(app_conn, run, "recover")
        async with as_role(mcp_exec):
            cur = await mcp_exec.execute("SELECT * FROM app.lookup_action(%s)", (new_handle,))
            assert dict(await cur.fetchone())["attempt_state"] == "SENT"
            document = {"status": "SUCCEEDED", "action_id": str(grant["action_id"]), "payload_sha256": digest, "receipt": {"receipt_id": str(uuid4()), "incident_id": "INC-000010", "committed_at": "2026-10-08T12:00:00Z"}, "tombstone": None, "reason": None}
            assert (await (await mcp_exec.execute("SELECT app.record_outcome(%s, 'SUCCEEDED', %s) AS r", (grant["action_id"], Jsonb(document)))).fetchone())["r"] == "SUCCEEDED"
        assert (await (await app_conn.execute("SELECT state FROM app.runs WHERE run_id = %s", (run,))).fetchone())["state"] == "SUCCEEDED"
    finally:
        await purge_run(app_conn, run)


async def test_late_evidence_on_a_terminal_run_records_without_a_transition(app_conn: persistence.Conn, role_conn: RoleConn) -> None:
    """SA:464: an outcome arriving after the run gave up is action.late_evidence, no transition, and its payload is
    one the Python rule mirror accepts (round-2 finding NI4). The terminal state is forced by the superuser because
    no Plan E function produces a terminal run with an unresolved attempt (T22's escalation path does)."""
    api, worker, mcp_exec = [await role_conn(r) for r in (Role.API, Role.WORKER, Role.MCP_EXEC)]
    run = await drafting_run(app_conn, api, worker)
    try:
        proposal, _, digest = await freeze(app_conn, worker, run)
        await approve(api, proposal, digest)
        handle = await handle_for(app_conn, run, "execute")
        async with as_role(mcp_exec):
            grant = dict(await (await mcp_exec.execute("SELECT * FROM app.grant_execution(%s, %s)", (handle, proposal))).fetchone())
            await mcp_exec.execute("SELECT app.mark_sent(%s)", (grant["action_id"],))
        await app_conn.execute("UPDATE app.runs SET state = 'FAILED', slot_held = false WHERE run_id = %s", (run,))
        document = {"status": "SUCCEEDED", "action_id": str(grant["action_id"]), "payload_sha256": digest, "receipt": {"receipt_id": str(uuid4()), "incident_id": "INC-000011", "committed_at": "2026-10-08T12:00:00Z"}, "tombstone": None, "reason": None}
        async with as_role(mcp_exec):
            assert (await (await mcp_exec.execute("SELECT app.record_outcome(%s, 'SUCCEEDED', %s) AS r", (grant["action_id"], Jsonb(document)))).fetchone())["r"] == "SUCCEEDED"
        row = await (await app_conn.execute("SELECT state FROM app.runs WHERE run_id = %s", (run,))).fetchone()
        assert row["state"] == "FAILED"  # no transition on a terminal run
        events = await (await app_conn.execute("SELECT type, source, payload FROM app.events WHERE run_id = %s ORDER BY sequence", (run,))).fetchall()
        assert (events[-1]["type"], events[-1]["source"]) == ("action.late_evidence", "destination")
        assert events[-1]["payload"]["outcome"] == "SUCCEEDED" and "tombstone" not in events[-1]["payload"]
        for e in events:
            event_rules_ok(EventType(e["type"]), EventSource(e["source"]), e["payload"])
    finally:
        await purge_run(app_conn, run)


async def test_r106_the_definer_path_cannot_cross_tenants(app_conn: persistence.Conn, role_conn: RoleConn) -> None:
    """Beta's handle and beta's reviewer against alpha's run and proposal: not found or refused, never a row."""
    api, worker, mcp_exec = [await role_conn(r) for r in (Role.API, Role.WORKER, Role.MCP_EXEC)]
    alpha_run = await drafting_run(app_conn, api, worker, ALPHA)
    beta_run = await drafting_run(app_conn, api, worker, BETA)
    try:
        alpha_proposal, _, alpha_digest = await freeze(app_conn, worker, alpha_run, ALPHA)
        await approve(api, alpha_proposal, alpha_digest)
        beta_proposal, _, beta_digest = await freeze(app_conn, worker, beta_run, BETA)
        await approve(api, beta_proposal, beta_digest, reviewer=JORDAN, tenant=BETA)
        beta_handle = await handle_for(app_conn, beta_run, "execute")
        assert await refused(mcp_exec, "SELECT * FROM app.grant_execution(%s, %s)", (beta_handle, alpha_proposal)) == "OC005"  # PROPOSAL_NOT_IN_RUN
        assert (await (await app_conn.execute("SELECT count(*) AS n FROM app.execution_grant WHERE run_id IN (%s, %s)", (alpha_run, beta_run))).fetchone())["n"] == 0
        assert await refused(api, "SELECT * FROM app.record_decision(%s, %s, %s, %s, 'approve', NULL, NULL)", (BETA, alpha_proposal, JORDAN, alpha_digest)) == "OC002"
        assert await refused(worker, "SELECT app.transition_run(%s, 'DRAFTING', 'FAILED', NULL, 3, '{}')", (uuid4(),)) == "OC002"
    finally:
        await purge_run(app_conn, alpha_run)
        await purge_run(app_conn, beta_run)


async def test_mcp_exec_cannot_reach_the_tables_the_functions_touched(role_conn: RoleConn) -> None:
    mcp_exec = await role_conn(Role.MCP_EXEC)
    for table in ("execution_grant", "action_attempt_state", "proposals", "runs", "invocation_context"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            await mcp_exec.execute(f"SELECT 1 FROM app.{table} LIMIT 1")
```

`refused`, `as_role`, `conversation` and `create` are imported from Task 3's module, which already defines them.

Run: `OPS_LIVE=1 PYTHONUTF8=1 uv run python -m pytest tests/e2e/test_definers_write_path_live.py -q -x` → FAIL (the first `refused` call answers `42883`, an undefined function, instead of the code the test expects).

- [ ] **Step 2: Write revision 0004**

Create `migrations/app/versions/0004_write_path_functions.py`:

```python
"""The approval and write-path definer functions (T09; AM-20.3 rows 4, 5, 10, 13–15, 17, 18): proposals are
inserted frozen, decisions are first-wins by an independent current reviewer, handles resolve to a run and a tenant,
and the attempt protocol INTENT → SENT → RESOLVED is append-only under the runs row lock.

Revision ID: 0004_write_path_functions
Revises: 0003_run_path_functions

Same shape as revision 0003 (owner app_definer, search_path, the tenant attribute, session_user first). Functions
that receive an action_id find the tenant by walking `tenants` (SA:520's sweeper pattern): execution_grant is under
RLS and the caller holds no tenant. The one row lock is `runs FOR UPDATE`, taken first (AM-12): proposals, decisions,
memberships and execution_grant are read without a lock because app_definer holds no UPDATE on them and a row lock
needs one (Plan E ruling 23; proposed erratum). Asset guard, lease fence, expiry and freshness are T13/T21.
"""

from alembic import op
from ops_core import privileges

revision = "0004_write_path_functions"
down_revision = "0003_run_path_functions"
branch_labels = None
depends_on = None

HEADER = "LANGUAGE plpgsql SECURITY DEFINER SET search_path = app, pg_temp SET app.tenant_id = ''"
HELPER_HEADER = "LANGUAGE plpgsql SET search_path = app, pg_temp"
GRANT_COLUMNS = (
    "action_id uuid, run_id uuid, proposal_id uuid, tenant_id uuid, conversation_id uuid, payload_sha256 text,"
    " payload_canonical bytea, attempt_state text, detail jsonb"
)
HANDLE_COLUMNS = (
    "run_id uuid, job_id uuid, job_type text, tenant_id uuid, conversation_id uuid, run_state text, attempt_state text"
)

TENANT_OF_ACTION = f"""
CREATE OR REPLACE FUNCTION app._tenant_of_action(p_action_id uuid) RETURNS uuid
{HELPER_HEADER} AS $fn$
DECLARE
    v_tenant uuid;
BEGIN
    FOR v_tenant IN SELECT t.tenant_id FROM tenants t ORDER BY t.tenant_id LOOP
        PERFORM set_config('app.tenant_id', v_tenant::text, true);
        IF EXISTS (SELECT 1 FROM execution_grant g WHERE g.action_id = p_action_id) THEN
            RETURN v_tenant;
        END IF;
    END LOOP;
    RAISE EXCEPTION 'not_found' USING ERRCODE = 'OC002', DETAIL = 'action';
END
$fn$;
ALTER FUNCTION app._tenant_of_action(uuid) OWNER TO app_definer;
"""

LATEST_ATTEMPT = f"""
CREATE OR REPLACE FUNCTION app._latest_attempt(p_action_id uuid)
RETURNS TABLE (attempt_no integer, seq integer, state text, outcome text, detail jsonb)
{HELPER_HEADER} AS $fn$
BEGIN
    -- "Latest" is the highest seq, never a timestamp (AM-20 principle 2).
    RETURN QUERY SELECT s.attempt_no, s.seq, s.state, s.outcome, s.detail FROM action_attempt_state s
                 WHERE s.action_id = p_action_id ORDER BY s.attempt_no DESC, s.seq DESC LIMIT 1;
END
$fn$;
ALTER FUNCTION app._latest_attempt(uuid) OWNER TO app_definer;
"""

RESOLVE_HANDLE = f"""
CREATE OR REPLACE FUNCTION app._resolve_handle(p_raw_handle text, p_client_azp text, p_server text)
RETURNS TABLE ({HANDLE_COLUMNS})
{HELPER_HEADER} AS $fn$
DECLARE
    v_ctx invocation_context%ROWTYPE;
    v_job_type text;
    v_job_server text;
    v_tenant uuid;
    v_run runs%ROWTYPE;
    v_attempt text;
BEGIN
    -- The raw handle never touches a table: only its hash is looked up (BS:360). Every refusal is the same error
    -- and the same message, so a probe learns nothing (SA:357).
    SELECT * INTO v_ctx FROM invocation_context ic
    WHERE ic.handle_sha256 = encode(sha256(convert_to(p_raw_handle, 'UTF8')), 'hex');
    IF NOT FOUND OR v_ctx.revoked_at IS NOT NULL OR v_ctx.expires_at <= app.current_time() OR v_ctx.azp <> p_client_azp THEN
        RAISE EXCEPTION 'handle_rejected' USING ERRCODE = 'OC008';
    END IF;
    v_tenant := app._tenant_of_run(v_ctx.run_id);
    SELECT j.type INTO v_job_type FROM jobs j WHERE j.id = v_ctx.job_id;
    -- The server is derived from the job type (SA:496), and the stored column must agree; a read handle at the
    -- write server (or the reverse) is refused whichever column a compromised worker wrote.
    v_job_server := CASE v_job_type WHEN 'investigate' THEN 'read' WHEN 'resume_input' THEN 'read'
                                    WHEN 'execute' THEN 'write' WHEN 'recover' THEN 'write' ELSE NULL END;
    IF v_job_server IS NULL OR v_job_server <> p_server OR v_ctx.server <> p_server THEN
        RAISE EXCEPTION 'handle_rejected' USING ERRCODE = 'OC008';
    END IF;
    SELECT * INTO v_run FROM runs r WHERE r.run_id = v_ctx.run_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'handle_rejected' USING ERRCODE = 'OC008';
    END IF;
    SELECT la.state INTO v_attempt FROM execution_grant g, LATERAL app._latest_attempt(g.action_id) la
    WHERE g.run_id = v_ctx.run_id;
    run_id := v_ctx.run_id; job_id := v_ctx.job_id; job_type := v_job_type; tenant_id := v_tenant;
    conversation_id := v_run.conversation_id; run_state := v_run.state; attempt_state := v_attempt;
    RETURN NEXT;
END
$fn$;
ALTER FUNCTION app._resolve_handle(text, text, text) OWNER TO app_definer;
"""

FREEZE_PROPOSAL = f"""
CREATE OR REPLACE FUNCTION app.freeze_proposal(p_run_id uuid, p_draft_id uuid, p_payload_canonical bytea,
                                               p_expires_at timestamptz)
RETURNS TABLE (proposal_id uuid, revision integer, state_version integer)
{HEADER} AS $fn$
DECLARE
    v_tenant uuid;
    v_run runs%ROWTYPE;
    v_draft drafts%ROWTYPE;
    v_sha text := encode(sha256(p_payload_canonical), 'hex');
    v_payload jsonb;
    v_proposal_id uuid;
    v_revision integer;
BEGIN
    PERFORM app._authority('freeze_proposal', ARRAY['worker']);
    v_tenant := app._tenant_of_run(p_run_id);
    SELECT * INTO v_run FROM runs r WHERE r.run_id = p_run_id FOR UPDATE;
    IF v_run.state <> 'DRAFTING' THEN
        RAISE EXCEPTION 'version_conflict' USING ERRCODE = 'OC003', DETAIL = format('run %s is %s', p_run_id, v_run.state);
    END IF;
    IF v_run.intent = 'answer_only' THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'ANSWER_ONLY';
    END IF;
    SELECT * INTO v_draft FROM drafts d WHERE d.id = p_draft_id AND d.run_id = p_run_id AND d.validated;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'not_found' USING ERRCODE = 'OC002', DETAIL = 'draft';
    END IF;
    -- The bytes stored are the bytes validated (SA:453): the hash is recomputed here over what arrived.
    IF v_draft.draft_sha256 <> v_sha THEN
        RAISE EXCEPTION 'hash_mismatch' USING ERRCODE = 'OC007', DETAIL = 'draft';
    END IF;
    v_payload := convert_from(p_payload_canonical, 'UTF8')::jsonb;
    IF (v_payload->>'run_id') IS DISTINCT FROM p_run_id::text OR (v_payload->>'tenant_id') IS DISTINCT FROM v_tenant::text THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'PAYLOAD_RUN_MISMATCH';
    END IF;
    -- supersedes_run_id is a run field written by create_run (SA:154); the frozen document must carry that value.
    IF (v_payload->>'supersedes_run_id') IS DISTINCT FROM v_run.supersedes_run_id::text THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'SUPERSEDES_MISMATCH';
    END IF;
    v_proposal_id := (v_payload->>'proposal_id')::uuid;
    SELECT coalesce(max(p.revision), 0) + 1 INTO v_revision FROM proposals p WHERE p.run_id = p_run_id;
    IF (v_payload->>'revision')::integer IS DISTINCT FROM v_revision THEN
        RAISE EXCEPTION 'version_conflict' USING ERRCODE = 'OC003', DETAIL = 'revision';
    END IF;
    INSERT INTO proposals (proposal_id, tenant_id, run_id, revision, draft_id, payload, payload_canonical, payload_sha256,
                           canonicalization_version, authored_by, expires_at, frozen_at)
    VALUES (v_proposal_id, v_tenant, p_run_id, v_revision, p_draft_id, v_payload, p_payload_canonical, v_sha, 1,
            ARRAY[v_run.requester], p_expires_at, app.current_time());
    UPDATE runs SET active_proposal_id = v_proposal_id WHERE runs.run_id = p_run_id;
    -- TODO(T21): the asset guard (advisory lock, AM-13) and BLOCKED_REVIEW on refusal.
    state_version := app._transition(p_run_id, 'AWAITING_APPROVAL', 'freeze_proposal', NULL, NULL, 'proposal.ready',
                                     jsonb_build_object('proposal_id', v_proposal_id));
    proposal_id := v_proposal_id;
    revision := v_revision;
    RETURN NEXT;
END
$fn$;
ALTER FUNCTION app.freeze_proposal(uuid, uuid, bytea, timestamptz) OWNER TO app_definer;
"""

RECORD_DECISION = f"""
CREATE OR REPLACE FUNCTION app.record_decision(p_tenant_id uuid, p_proposal_id uuid, p_reviewer uuid,
                                               p_expected_payload_sha256 text, p_decision text, p_reason text,
                                               p_idempotency_key text)
RETURNS TABLE (run_id uuid, state text, state_version integer)
{HEADER} AS $fn$
DECLARE
    v_proposal proposals%ROWTYPE;
    v_run runs%ROWTYPE;
BEGIN
    PERFORM app._authority('record_decision', ARRAY['api']);
    -- The API is the identity trust anchor (SA:454): tenant and reviewer are arguments it has authenticated.
    PERFORM set_config('app.tenant_id', p_tenant_id::text, true);
    IF p_decision NOT IN ('approve', 'reject') THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'INVALID_ARGUMENT';
    END IF;
    SELECT * INTO v_proposal FROM proposals p WHERE p.proposal_id = p_proposal_id AND p.tenant_id = p_tenant_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'not_found' USING ERRCODE = 'OC002', DETAIL = 'proposal';
    END IF;
    -- runs FOR UPDATE is the only lock: proposals and decisions are insert-only and app_definer may not lock them
    -- (ruling 23).
    SELECT * INTO v_run FROM runs r WHERE r.run_id = v_proposal.run_id FOR UPDATE;
    IF v_run.state <> 'AWAITING_APPROVAL' OR v_run.active_proposal_id IS DISTINCT FROM p_proposal_id
       OR v_proposal.payload_sha256 <> p_expected_payload_sha256 THEN
        RAISE EXCEPTION 'version_conflict' USING ERRCODE = 'OC003', DETAIL = 'not the active undecided revision';
    END IF;
    -- Independence (BS:466, SA:539): a current reviewer of this tenant who is neither requester nor author.
    IF NOT EXISTS (SELECT 1 FROM memberships m WHERE m.tenant_id = p_tenant_id AND m.subject = p_reviewer
                                                     AND m.role = 'reviewer' AND m.active) THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'NOT_REVIEWER';
    END IF;
    IF p_reviewer = v_run.requester OR p_reviewer = ANY (v_proposal.authored_by) THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'SELF_REVIEW';
    END IF;
    -- TODO(T21): lazy expiry (expires_at < app.current_time() → BLOCKED_REVIEW(expired)).
    BEGIN
        INSERT INTO decisions (decision_id, tenant_id, proposal_id, reviewer, decision, reason, expected_payload_sha256,
                               idempotency_key, decided_at)
        VALUES (gen_random_uuid(), p_tenant_id, p_proposal_id, p_reviewer, p_decision, p_reason,
                p_expected_payload_sha256, p_idempotency_key, app.current_time());
    EXCEPTION WHEN unique_violation THEN
        RAISE EXCEPTION 'version_conflict' USING ERRCODE = 'OC003', DETAIL = 'first decision wins';
    END;
    run_id := v_run.run_id;
    IF p_decision = 'approve' THEN
        INSERT INTO jobs (id, type, tenant_id, run_id, dedup_key)
        VALUES (gen_random_uuid(), 'execute', p_tenant_id, v_run.run_id, p_proposal_id::text)
        ON CONFLICT (dedup_key) DO NOTHING;
        state := 'APPROVED';
        state_version := app._transition(v_run.run_id, 'APPROVED', 'record_decision', NULL, NULL, 'approval.recorded',
                                         jsonb_build_object('proposal_id', p_proposal_id));
    ELSE
        state := 'REJECTED';
        state_version := app._transition(v_run.run_id, 'REJECTED', 'record_decision', 'rejected', NULL, 'run.rejected',
                                         jsonb_build_object('proposal_id', p_proposal_id));
    END IF;
    RETURN NEXT;
END
$fn$;
ALTER FUNCTION app.record_decision(uuid, uuid, uuid, text, text, text, text) OWNER TO app_definer;
"""

RESOLVE_INVOCATION = f"""
CREATE OR REPLACE FUNCTION app.resolve_invocation(p_raw_handle text, p_client_azp text)
RETURNS TABLE ({HANDLE_COLUMNS})
{HEADER} AS $fn$
BEGIN
    PERFORM app._authority('resolve_invocation', ARRAY['mcp_read', 'mcp_exec']);
    -- The calling role picks the server (SA:459): mcp_read sees read handles only, mcp_exec write handles only.
    RETURN QUERY SELECT * FROM app._resolve_handle(p_raw_handle, p_client_azp,
                                                   CASE WHEN session_user::text = 'mcp_read' THEN 'read' ELSE 'write' END);
END
$fn$;
ALTER FUNCTION app.resolve_invocation(text, text) OWNER TO app_definer;
"""

GRANT_EXECUTION = f"""
CREATE OR REPLACE FUNCTION app.grant_execution(p_raw_handle text, p_proposal_id uuid)
RETURNS TABLE ({GRANT_COLUMNS})
{HEADER} AS $fn$
DECLARE
    v_handle record;
    v_run runs%ROWTYPE;
    v_proposal proposals%ROWTYPE;
    v_grant execution_grant%ROWTYPE;
    v_action_id uuid;
BEGIN
    PERFORM app._authority('grant_execution', ARRAY['mcp_exec']);
    SELECT * INTO v_handle FROM app._resolve_handle(p_raw_handle, 'ops-worker', 'write');
    SELECT * INTO v_run FROM runs r WHERE r.run_id = v_handle.run_id FOR UPDATE;
    SELECT * INTO v_grant FROM execution_grant g WHERE g.run_id = v_handle.run_id;
    IF FOUND THEN
        -- UNIQUE (run_id): one grant per run, ever (SA:167); a replay finds the grant it already has.
        IF v_grant.proposal_id <> p_proposal_id THEN
            RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'OTHER_PROPOSAL';
        END IF;
        RETURN QUERY SELECT * FROM app._grant_row(v_grant.action_id);
        RETURN;
    END IF;
    SELECT * INTO v_proposal FROM proposals p WHERE p.proposal_id = p_proposal_id AND p.run_id = v_handle.run_id
                                                AND p.tenant_id = v_handle.tenant_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'PROPOSAL_NOT_IN_RUN';
    END IF;
    IF v_run.state <> 'APPROVED' OR v_run.active_proposal_id IS DISTINCT FROM p_proposal_id THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'NOT_ACTIVE_APPROVED';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM decisions d WHERE d.proposal_id = p_proposal_id AND d.decision = 'approve') THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'NO_APPROVAL';
    END IF;
    IF v_run.cancel_requested THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'CANCELLED';
    END IF;
    -- The §13 gate re-reads current membership (BS:472): requester and reviewer must still be active members.
    IF NOT EXISTS (SELECT 1 FROM memberships m WHERE m.tenant_id = v_handle.tenant_id AND m.subject = v_run.requester AND m.active)
       OR NOT EXISTS (SELECT 1 FROM decisions d JOIN memberships m ON m.tenant_id = v_handle.tenant_id AND m.subject = d.reviewer
                      AND m.role = 'reviewer' AND m.active WHERE d.proposal_id = p_proposal_id) THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'MEMBERSHIP_INACTIVE';
    END IF;
    -- TODO(T21): asset freshness (5 min) and the asset guard; TODO(T13): the lease fence.
    v_action_id := gen_random_uuid();  -- random inside the gate (SA:168), never derived from the proposal
    INSERT INTO execution_grant (action_id, tenant_id, run_id, proposal_id, payload_sha256, granted_at)
    VALUES (v_action_id, v_handle.tenant_id, v_handle.run_id, p_proposal_id, v_proposal.payload_sha256, app.current_time());
    INSERT INTO action_attempt (tenant_id, action_id, attempt_no, created_at)
    VALUES (v_handle.tenant_id, v_action_id, 1, app.current_time());
    INSERT INTO action_attempt_state (tenant_id, action_id, attempt_no, seq, state, at)
    VALUES (v_handle.tenant_id, v_action_id, 1, 1, 'INTENT', app.current_time());
    PERFORM app._transition(v_handle.run_id, 'EXECUTING', 'grant_execution', NULL, NULL, 'action.granted',
                            jsonb_build_object('action_id', v_action_id, 'proposal_id', p_proposal_id));
    RETURN QUERY SELECT * FROM app._grant_row(v_action_id);
END
$fn$;
ALTER FUNCTION app.grant_execution(text, uuid) OWNER TO app_definer;
"""

GRANT_ROW = f"""
CREATE OR REPLACE FUNCTION app._grant_row(p_action_id uuid)
RETURNS TABLE ({GRANT_COLUMNS})
{HELPER_HEADER} AS $fn$
BEGIN
    RETURN QUERY
    SELECT g.action_id, g.run_id, g.proposal_id, g.tenant_id, r.conversation_id, g.payload_sha256, p.payload_canonical,
           la.state, la.detail
    FROM execution_grant g JOIN runs r ON r.run_id = g.run_id JOIN proposals p ON p.proposal_id = g.proposal_id
         LEFT JOIN LATERAL app._latest_attempt(g.action_id) la ON true
    WHERE g.action_id = p_action_id;
END
$fn$;
ALTER FUNCTION app._grant_row(uuid) OWNER TO app_definer;
"""

LOOKUP_ACTION = f"""
CREATE OR REPLACE FUNCTION app.lookup_action(p_raw_handle text)
RETURNS TABLE ({GRANT_COLUMNS})
{HEADER} AS $fn$
DECLARE
    v_handle record;
    v_action_id uuid;
BEGIN
    PERFORM app._authority('lookup_action', ARRAY['mcp_exec']);
    SELECT * INTO v_handle FROM app._resolve_handle(p_raw_handle, 'ops-worker', 'write');
    SELECT g.action_id INTO v_action_id FROM execution_grant g WHERE g.run_id = v_handle.run_id;
    IF v_action_id IS NULL THEN
        RAISE EXCEPTION 'not_found' USING ERRCODE = 'OC002', DETAIL = 'grant';
    END IF;
    RETURN QUERY SELECT * FROM app._grant_row(v_action_id);
END
$fn$;
ALTER FUNCTION app.lookup_action(text) OWNER TO app_definer;
"""

MARK_SENT = f"""
CREATE OR REPLACE FUNCTION app.mark_sent(p_action_id uuid) RETURNS text
{HEADER} AS $fn$
DECLARE
    v_tenant uuid;
    v_grant execution_grant%ROWTYPE;
    v_run runs%ROWTYPE;
    v_latest record;
BEGIN
    PERFORM app._authority('mark_sent', ARRAY['mcp_exec']);
    v_tenant := app._tenant_of_action(p_action_id);
    SELECT * INTO v_grant FROM execution_grant g WHERE g.action_id = p_action_id;
    SELECT * INTO v_run FROM runs r WHERE r.run_id = v_grant.run_id FOR UPDATE;  -- serialises the seq (SA:462)
    SELECT * INTO v_latest FROM app._latest_attempt(p_action_id);
    IF v_latest.state = 'RESOLVED' THEN
        RETURN 'resolved';
    ELSIF v_latest.state = 'SENT' THEN
        RETURN 'already_sent';
    END IF;
    -- SA:463: cancellation is re-checked before SENT; nothing is written. TODO(T22): the dispatch deadline.
    IF v_run.cancel_requested THEN
        RETURN 'cancelled';
    END IF;
    INSERT INTO action_attempt_state (tenant_id, action_id, attempt_no, seq, state, at)
    VALUES (v_tenant, p_action_id, v_latest.attempt_no, v_latest.seq + 1, 'SENT', app.current_time());
    PERFORM app._append_event(v_tenant, v_grant.run_id,
                              CASE WHEN v_latest.attempt_no > 1 THEN 'action.redispatched' ELSE 'action.dispatched' END,
                              'application', jsonb_build_object('action_id', p_action_id));
    RETURN 'sent';
END
$fn$;
ALTER FUNCTION app.mark_sent(uuid) OWNER TO app_definer;
"""

RECORD_OUTCOME = f"""
CREATE OR REPLACE FUNCTION app.record_outcome(p_action_id uuid, p_outcome text, p_document jsonb) RETURNS text
{HEADER} AS $fn$
DECLARE
    v_tenant uuid;
    v_grant execution_grant%ROWTYPE;
    v_run runs%ROWTYPE;
    v_latest record;
    v_implied text;
    v_reason text;
BEGIN
    PERFORM app._authority('record_outcome', ARRAY['mcp_exec']);
    v_tenant := app._tenant_of_action(p_action_id);
    SELECT * INTO v_grant FROM execution_grant g WHERE g.action_id = p_action_id;
    SELECT * INTO v_run FROM runs r WHERE r.run_id = v_grant.run_id FOR UPDATE;
    SELECT * INTO v_latest FROM app._latest_attempt(p_action_id);
    IF v_latest.state = 'RESOLVED' THEN
        RETURN v_latest.outcome;  -- idempotent (SA:464): the first record stands
    END IF;
    IF p_outcome NOT IN ('SUCCEEDED', 'FAILED_NO_COMMIT', 'CONFLICT') THEN
        RAISE EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'INVALID_ARGUMENT';
    END IF;
    -- The document's hash must be the grant's (SA:464); a CONFLICT is precisely the case where it is not.
    IF p_outcome <> 'CONFLICT' AND (p_document->>'payload_sha256') IS DISTINCT FROM v_grant.payload_sha256 THEN
        RAISE EXCEPTION 'hash_mismatch' USING ERRCODE = 'OC007', DETAIL = 'outcome';
    END IF;
    IF (p_document->>'action_id') IS DISTINCT FROM p_action_id::text THEN
        RAISE EXCEPTION 'hash_mismatch' USING ERRCODE = 'OC007', DETAIL = 'action_id';
    END IF;
    INSERT INTO action_attempt_state (tenant_id, action_id, attempt_no, seq, state, outcome, detail, at)
    VALUES (v_tenant, p_action_id, v_latest.attempt_no, v_latest.seq + 1, 'RESOLVED', p_outcome, p_document, app.current_time());
    v_implied := CASE p_outcome WHEN 'SUCCEEDED' THEN 'SUCCEEDED' WHEN 'FAILED_NO_COMMIT' THEN 'FAILED' ELSE 'ESCALATED' END;
    IF v_run.state IN ('EXECUTING', 'OUTCOME_UNKNOWN', 'ESCALATED') AND v_run.state <> v_implied THEN
        v_reason := CASE p_outcome WHEN 'FAILED_NO_COMMIT' THEN p_document->>'reason' WHEN 'CONFLICT' THEN 'conflict' ELSE NULL END;
        PERFORM app._transition(v_grant.run_id, v_implied, 'record_outcome', v_reason, NULL, NULL, NULL);
    END IF;
    -- The event is the destination's assertion (AM-14); on a terminal run a SUCCEEDED or FAILED outcome is late
    -- evidence (payload `outcome` + its proof, the shape ops_core.outcomes.event_rules_ok accepts) and a CONFLICT is
    -- always action.conflict; no transition either way.
    IF v_run.state IN ('SUCCEEDED', 'FAILED', 'ABANDONED_UNVERIFIED') AND p_outcome <> 'CONFLICT' THEN
        PERFORM app._append_event(v_tenant, v_grant.run_id, 'action.late_evidence', 'destination',
            CASE WHEN p_outcome = 'SUCCEEDED'
                 THEN jsonb_build_object('outcome', 'SUCCEEDED', 'action_id', p_action_id, 'receipt', p_document->'receipt')
                 ELSE jsonb_build_object('outcome', 'FAILED_NO_COMMIT', 'action_id', p_action_id, 'reason', p_document->>'reason',
                                         'tombstone', p_document->'tombstone') END);
    ELSE
        PERFORM app._append_event(v_tenant, v_grant.run_id,
            CASE WHEN p_outcome = 'SUCCEEDED' THEN 'action.confirmed'
                 WHEN p_outcome = 'FAILED_NO_COMMIT' THEN 'action.failed' ELSE 'action.conflict' END,
            'destination',
            CASE WHEN p_outcome = 'SUCCEEDED' THEN jsonb_build_object('status', 'SUCCEEDED', 'action_id', p_action_id, 'receipt', p_document->'receipt')
                 WHEN p_outcome = 'FAILED_NO_COMMIT' THEN jsonb_build_object('action_id', p_action_id, 'reason', p_document->>'reason', 'tombstone', p_document->'tombstone')
                 ELSE jsonb_build_object('action_id', p_action_id) END);
    END IF;
    RETURN p_outcome;
END
$fn$;
ALTER FUNCTION app.record_outcome(uuid, text, jsonb) OWNER TO app_definer;
"""

MARK_UNKNOWN = f"""
CREATE OR REPLACE FUNCTION app.mark_unknown(p_run_id uuid, p_fence bigint) RETURNS text
{HEADER} AS $fn$
DECLARE
    v_tenant uuid;
    v_run runs%ROWTYPE;
    v_grant execution_grant%ROWTYPE;
BEGIN
    PERFORM app._authority('mark_unknown', ARRAY['worker']);
    v_tenant := app._tenant_of_run(p_run_id);
    SELECT * INTO v_run FROM runs r WHERE r.run_id = p_run_id FOR UPDATE;
    -- TODO(T13): bump run_lease.fence (p_fence) here; until leases exist the handles are revoked directly.
    UPDATE invocation_context SET revoked_at = app.current_time() WHERE run_id = p_run_id AND revoked_at IS NULL;
    IF v_run.state = 'OUTCOME_UNKNOWN' THEN
        RETURN v_run.state;  -- a second UNKNOWN changes nothing
    END IF;
    IF v_run.state <> 'EXECUTING' THEN
        RAISE EXCEPTION 'version_conflict' USING ERRCODE = 'OC003', DETAIL = format('run %s is %s', p_run_id, v_run.state);
    END IF;
    SELECT * INTO v_grant FROM execution_grant g WHERE g.run_id = p_run_id;
    IF NOT FOUND THEN
        RETURN v_run.state;  -- EXECUTING without a grant cannot happen; nothing to mark
    END IF;
    PERFORM app._transition(p_run_id, 'OUTCOME_UNKNOWN', 'mark_unknown', NULL, NULL, 'action.uncertain',
                            jsonb_build_object('action_id', v_grant.action_id));
    INSERT INTO jobs (id, type, tenant_id, run_id, dedup_key)
    VALUES (gen_random_uuid(), 'recover', v_tenant, p_run_id, format('%s:timeout', v_grant.action_id))
    ON CONFLICT (dedup_key) DO NOTHING;
    RETURN 'OUTCOME_UNKNOWN';
END
$fn$;
ALTER FUNCTION app.mark_unknown(uuid, bigint) OWNER TO app_definer;
"""

FUNCTIONS = (
    ("_tenant_of_action", TENANT_OF_ACTION),
    ("_latest_attempt", LATEST_ATTEMPT),
    ("_resolve_handle", RESOLVE_HANDLE),
    ("_grant_row", GRANT_ROW),
    ("freeze_proposal", FREEZE_PROPOSAL),
    ("record_decision", RECORD_DECISION),
    ("resolve_invocation", RESOLVE_INVOCATION),
    ("grant_execution", GRANT_EXECUTION),
    ("lookup_action", LOOKUP_ACTION),
    ("mark_sent", MARK_SENT),
    ("record_outcome", RECORD_OUTCOME),
    ("mark_unknown", MARK_UNKNOWN),
)


def upgrade() -> None:
    for name, body in FUNCTIONS:
        op.execute(body)
        for statement in privileges.function_grant_statements(name):
            op.execute(statement)


def downgrade() -> None:
    for name, _ in reversed(FUNCTIONS):
        args = privileges.HELPER_FUNCTIONS.get(name) or privileges.DEFINER_FUNCTIONS[name][0]
        op.execute(f"DROP FUNCTION app.{name}({args})")
```

Add `"_grant_row": "uuid"` to `ops_core.privileges.HELPER_FUNCTIONS` (Task 1's module; the privilege test's helper assertion still holds).

Notes for the implementer:
- `_grant_row` is created before `grant_execution` references it? PL/pgSQL resolves function references at run time, so the order inside `FUNCTIONS` only matters for the helper's grant statement; keep it as listed.
- `v_handle record` holds `_resolve_handle`'s row; `SELECT * INTO v_handle FROM app._resolve_handle(...)` raises `OC008` from inside the helper before anything else runs, which is the behaviour the tests pin.
- `record_outcome` on a run that is already terminal inserts the RESOLVED row and `action.late_evidence` with `outcome` plus the matching proof (`receipt` or `tombstone`), which is what `ops_core.outcomes.event_rules_ok` requires for that type; the live tests replay every event row the functions wrote (the success path and the forced late-evidence case) through `event_rules_ok`, which is the drift check the SQL mirror has.

- [ ] **Step 3: Format, then run the live tests**

Run: `uv run ruff format migrations/app/versions/0004_write_path_functions.py tests/e2e/test_definers_write_path_live.py && uv run ruff check --fix migrations tests/e2e && uv run python -m pytest tests/plan_e/test_transitions_table.py -q`, then `OPS_LIVE=1 PYTHONUTF8=1 uv run python -m pytest tests/e2e/test_definers_write_path_live.py tests/e2e/test_definers_run_path_live.py tests/e2e/test_roles_live.py -q -x`
Expected: PASS, including `test_function_catalog_shape` with every function present.

- [ ] **Step 4: Gate and commit**

`PYTHONUTF8=1 uv run python scripts/check.py` → GREEN.

```bash
git add migrations/app/versions/0004_write_path_functions.py core/src/ops_core/privileges.py tests/e2e/test_definers_write_path_live.py tests/e2e/test_definers_run_path_live.py
git commit -m "feat(migrations): the approval and write-path definer functions (freeze, decide, resolve, grant, sent, outcome, lookup, unknown) (T09)"
```

---
### Task 5: `ops_core.persistence` on the definer functions

**Files:**
- Modify: `core/src/ops_core/persistence.py` (rewrite), `tests/plan_d/test_persistence_pure.py` (the handle rules moved: only the tool allowlist stays in Python), `tests/e2e/test_migrations_and_persistence.py` (`new_run` and the transition/event/job tests on the wrappers), `tests/e2e/test_definers_run_path_live.py` (nothing; it keeps calling SQL directly)
- Create: `tests/plan_e/test_persistence_errors.py`

**Interfaces:**
- Consumes: the SQL functions of Tasks 3–4; `ops_core.settings.Profile`; `ops_core.canonical.sha256_hex`; `ops_core.jobs.JOB_RULES`, `JobType`, `Server`, `Tool`, `server_for`; `ops_core.states.IllegalTransition`, `RunState`, `Reason`, `Intent`; `ops_core.outcomes.EventRuleViolation`, `EventSource`, `EventType`, `ActionOutcome`, `ToolOutcome`.
- Produces (`ops_core.persistence`):
  - exceptions: `PersistenceError`, `NotFound`, `VersionConflict`, `HandleRejected`, `AuthorityViolation`, `HashMismatch`, `Refused(code: str)` (`.code` is the SQL `DETAIL`); `translate(exc: psycopg.Error) -> Exception | None` (the SQLSTATE map; `None` for anything outside class `OC`); `OC_CODES`.
  - `connect(pg)` (unchanged); `Session(conn)` with `unit(tenant_id: UUID | None = None)` (sets the tenant as the unit's first statement) and `ping()`; `set_tenant(conn, tenant_id)`.
  - `assert_clock_profile(conn, profile: Profile)` — raises `PersistenceError` when `app.test_clock` exists and the profile is not test (SA:528).
  - `tenants(conn) -> list[UUID]`; `run_row(conn, run_id, *, lock=False)` (unchanged SQL; the caller's unit has set the tenant).
  - `resolve_identity(conn, *, issuer, subject) -> list[tuple[UUID, str]]`.
  - `create_run(conn, *, tenant_id, conversation_id, message_id, requester, intent, asset_id, start_at, end_at, supersedes_run_id=None) -> tuple[UUID, int]`.
  - `transition_run(conn, *, run_id, src, dst, reason=None, expected_version=None, detail=None) -> int` (logs a refused transition at WARNING, R082).
  - `append_event(conn, *, run_id, type, payload, source=EventSource.APPLICATION) -> Appended(event_id, sequence, occurred_at)`.
  - `revoke_handles(conn, run_id) -> int`; `mark_unknown(conn, run_id) -> RunState`.
  - `freeze_proposal(conn, *, run_id, draft_id, payload_canonical: bytes, expires_at) -> Frozen(proposal_id, revision, state_version)`.
  - `record_decision(conn, *, tenant_id, proposal_id, reviewer, expected_payload_sha256, decision, reason: str | None = None, idempotency_key=None) -> Decided(run_id, state, state_version)` (`reason` is the reviewer's free text; the rejection's transition reason is fixed inside the function).
  - `Invocation` (dataclass: `run_id, job_id, job_type, tenant_id, conversation_id, run_state, attempt_state`); `allowed_tool(job_type, tool)` (pure; raises `HandleRejected`); `resolve_invocation(conn, *, handle, azp, tool) -> Invocation`.
  - `Grant` (dataclass: `action_id, run_id, proposal_id, tenant_id, conversation_id, payload_sha256, payload_canonical: bytes, attempt_state: str | None, detail: dict | None`); `grant_execution(conn, *, handle, proposal_id) -> Grant`; `lookup_action(conn, *, handle) -> Grant`; `mark_sent(conn, action_id) -> str`; `record_outcome(conn, *, action_id, outcome: ActionOutcome) -> ToolOutcome`.
  - jobs: `insert_job` (unchanged), `claim_job(conn, *, worker_name, tenant_ids: Sequence[UUID]) -> DictRow | None` (per-tenant `SKIP LOCKED` under `set_config`; the row carries `tenant_id`), `finish_job`, `requeue_job` (unchanged).
  - `mint_handle(conn, *, run_id, job_id, server, azp, ttl_seconds=60) -> str` (stores the hash).

- [ ] **Step 1: Write the failing unit tests**

Create `tests/plan_e/test_persistence_errors.py`:

```python
"""The database-free parts of the rewritten persistence layer: SQLSTATE class OC → typed exceptions (ruling 20), the
tool allowlist that stayed in Python (ruling 21), and the hashed handle.

Catches: a code mapped to the wrong class, a non-OC error swallowed, a DETAIL code lost, a tool allowed for the
wrong job type, and a handle stored raw.
"""

from types import SimpleNamespace

import psycopg
import pytest
from ops_core import persistence as p
from ops_core.canonical import sha256_hex
from ops_core.jobs import JobType, Tool
from ops_core.outcomes import EventRuleViolation
from ops_core.states import IllegalTransition


def error(sqlstate: str, detail: str | None = None) -> psycopg.Error:
    """A server error with a chosen SQLSTATE and DETAIL; psycopg's `diag` is a property, so a subclass overrides it."""
    diag = SimpleNamespace(message_detail=detail, message_primary="x")
    cls = type("FakeError", (psycopg.DatabaseError,), {"diag": property(lambda self: diag)})
    exc = cls("x")
    exc.sqlstate = sqlstate
    return exc


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("OC001", p.AuthorityViolation),
        ("OC002", p.NotFound),
        ("OC003", p.VersionConflict),
        ("OC004", IllegalTransition),
        ("OC005", p.Refused),
        ("OC006", EventRuleViolation),
        ("OC007", p.HashMismatch),
        ("OC008", p.HandleRejected),
    ],
)
def test_oc_codes_map_to_typed_exceptions(code: str, expected: type[Exception]) -> None:
    mapped = p.translate(error(code, "DETAIL"))
    assert isinstance(mapped, expected)
    assert "x" not in str(mapped) or code != "OC008"  # the handle refusal never echoes the server's text


def test_refused_carries_the_detail_code_and_other_errors_pass_through() -> None:
    mapped = p.translate(error("OC005", "SLOT_OCCUPIED"))
    assert isinstance(mapped, p.Refused) and mapped.code == "SLOT_OCCUPIED"
    assert p.translate(error("42501")) is None
    assert p.translate(error("40001")) is None


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


def test_handle_hash_is_the_canonical_sha256_of_the_utf8_bytes() -> None:
    assert p.handle_hash("abc") == sha256_hex(b"abc")
    assert len(p.handle_hash("x" * 43)) == 64
```

Run: `uv run python -m pytest tests/plan_e/test_persistence_errors.py -q` → FAIL (an `AttributeError` on the first missing name, `AuthorityViolation`).

- [ ] **Step 2: Rewrite `core/src/ops_core/persistence.py`**

```python
"""The one door to the application database: a thin Python wrapper per AM-20.3 definer function, plus the few plain
statements a runtime role may run under its own grants (T09; SPEC_AMENDMENTS AM-20.2/20.3).

Every state transition, decision, grant, attempt step and event happens inside a SECURITY DEFINER function
(migrations/app/versions/0003 and 0004); nothing here writes runs.state or an audit table. A function refuses with
SQLSTATE class OC, which `translate` turns into the typed exceptions services already catch. Any unit of work that
touches a tenant table opens as `Session.unit(tenant_id)`, which sets the transaction-local tenant first: RLS admits
nothing otherwise, and a reused connection's setting is '' between units (spike §1, §2). Pools arrive with T13.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import DictRow, dict_row
from psycopg.types.json import Jsonb

from ops_core.canonical import sha256_hex
from ops_core.jobs import JOB_RULES, JobType, Server, Tool, dedup_key
from ops_core.outcomes import ActionOutcome, EventRuleViolation, EventSource, EventType, ToolOutcome
from ops_core.settings import Postgres, Profile
from ops_core.states import IllegalTransition, Intent, Reason, RunState

Conn = psycopg.AsyncConnection[DictRow]
log = logging.getLogger("ops_core.persistence")


class PersistenceError(Exception):
    """Base class; messages are safe for logs and HTTP bodies (no handle, token or secret)."""


class NotFound(PersistenceError):
    """The row is absent or belongs to another tenant; the two cases are indistinguishable on purpose (SA:357)."""


class VersionConflict(PersistenceError):
    """A stale state, version or hash: the caller's view of the run is out of date."""


class HandleRejected(PersistenceError):
    """The invocation handle is unknown, expired, revoked, or bound to another server, workload or tool."""


class AuthorityViolation(PersistenceError):
    """A session that holds EXECUTE through membership is not on the function's caller list (SA:389); a plain wrong
    role never gets this far (42501 from the ACL). A deployment error, never a user error."""


class HashMismatch(PersistenceError):
    """The bytes or the hash presented are not the ones recorded."""


class Refused(PersistenceError):
    """A gate said no; `code` is the function's DETAIL (SLOT_OCCUPIED, NOT_REVIEWER, ...), safe to map to HTTP."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


OC_CODES: dict[str, type[Exception]] = {
    "OC001": AuthorityViolation,
    "OC002": NotFound,
    "OC003": VersionConflict,
    "OC004": IllegalTransition,
    "OC005": Refused,
    "OC006": EventRuleViolation,
    "OC007": HashMismatch,
    "OC008": HandleRejected,
}


def translate(exc: psycopg.Error) -> Exception | None:
    """The typed exception for a class-OC error, or None (the caller re-raises anything else)."""
    cls = OC_CODES.get(exc.sqlstate or "")
    if cls is None:
        return None
    detail = exc.diag.message_detail or ""
    if cls is Refused:
        return Refused(detail or "REFUSED")
    if cls is HandleRejected:
        return HandleRejected("invocation handle rejected")  # one message for every refusal (SA:357)
    return cls(f"{exc.diag.message_primary}: {detail}" if detail else str(exc.diag.message_primary))


async def _call(conn: Conn, query: str, params: tuple[object, ...]) -> DictRow | None:
    """Run one function call and translate its refusal; the first row or None."""
    try:
        cur = await conn.execute(query, params)
        return await cur.fetchone()
    except psycopg.Error as exc:
        mapped = translate(exc)
        if mapped is None:
            raise
        raise mapped from exc


async def _call_all(conn: Conn, query: str, params: tuple[object, ...]) -> list[DictRow]:
    try:
        cur = await conn.execute(query, params)
        return await cur.fetchall()
    except psycopg.Error as exc:
        mapped = translate(exc)
        if mapped is None:
            raise
        raise mapped from exc


async def connect(pg: Postgres) -> Conn:
    """One autocommit connection per process (Plan D ruling 24): a bare statement is its own transaction and
    `async with conn.transaction()` a real BEGIN/COMMIT, never a savepoint inside a transaction a SELECT left open."""
    return await psycopg.AsyncConnection.connect(pg.conninfo(), row_factory=dict_row, autocommit=True)


async def set_tenant(conn: Conn, tenant_id: UUID) -> None:
    """Transaction-local (`is_local = true`): gone at COMMIT or ROLLBACK, so the next unit starts tenant-less."""
    await conn.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant_id),))


class Session:
    """One connection, one unit of work at a time: the lock keeps concurrent requests from interleaving on the
    connection; the transaction makes the unit atomic. Never enter `unit()` while holding it (the lock is not
    re-entrant); callers pass the `conn` a unit yields instead. TODO(T13): a pool."""

    def __init__(self, conn: Conn) -> None:
        self.conn = conn
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def unit(self, tenant_id: UUID | None = None) -> AsyncIterator[Conn]:
        """A transaction; with a tenant, RLS admits that tenant's rows for the unit's duration and no longer."""
        async with self._lock, self.conn.transaction():
            if tenant_id is not None:
                await set_tenant(self.conn, tenant_id)
            yield self.conn

    async def ping(self) -> None:
        """Readiness: one autocommit statement, no transaction left open, no tenant table touched."""
        async with self._lock:
            await self.conn.execute("SELECT 1")


async def assert_clock_profile(conn: Conn, profile: Profile) -> None:
    """Every service, not only the bootstrap, refuses to run outside the test profile when app.test_clock exists
    (SA:528, T09 review note 5); any role may call to_regclass."""
    cur = await conn.execute("SELECT to_regclass('app.test_clock') IS NOT NULL AS present")
    row = await cur.fetchone()
    if row is not None and row["present"] and profile is not Profile.TEST:
        raise PersistenceError(f"app.test_clock exists; the {profile.value} profile refuses to start")


async def tenants(conn: Conn) -> list[UUID]:
    """Every tenant id (no RLS on tenants, SA:523): the worker's claim loop and the sweeper iterate these."""
    cur = await conn.execute("SELECT tenant_id FROM app.tenants ORDER BY tenant_id")
    return [UUID(str(r["tenant_id"])) for r in await cur.fetchall()]


async def run_row(conn: Conn, run_id: UUID, *, lock: bool = False) -> DictRow:
    """The run row under the caller's tenant unit; a foreign or absent run is NotFound (RLS hides it)."""
    suffix = " FOR UPDATE" if lock else ""
    cur = await conn.execute(f"SELECT * FROM app.runs WHERE run_id = %s{suffix}", (run_id,))
    row = await cur.fetchone()
    if row is None:
        raise NotFound("run not found")
    return row


async def resolve_identity(conn: Conn, *, issuer: str, subject: UUID) -> list[tuple[UUID, str]]:
    """(tenant_id, role) for every active membership of the subject (Plan E ruling 4); needs no tenant unit."""
    rows = await _call_all(conn, "SELECT * FROM app.resolve_identity(%s, %s)", (issuer, subject))
    return [(UUID(str(r["tenant_id"])), str(r["role"])) for r in rows]


async def create_run(
    conn: Conn,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    message_id: UUID,
    requester: UUID,
    intent: Intent,
    asset_id: str,
    start_at: datetime,
    end_at: datetime,
    supersedes_run_id: UUID | None = None,
) -> tuple[UUID, int]:
    """∅ → QUEUED inside the function (SA:450): run, directory, history, the investigate job and run.accepted."""
    request = {
        "message_id": str(message_id),
        "requester": str(requester),
        "asset_id": asset_id,
        "start_at": start_at.isoformat(),
        "end_at": end_at.isoformat(),
    }
    row = await _call(
        conn,
        "SELECT * FROM app.create_run(%s, %s, %s, %s, %s)",
        (tenant_id, conversation_id, Jsonb(request), intent.value, supersedes_run_id),
    )
    if row is None:
        raise PersistenceError("create_run returned nothing")
    return UUID(str(row["run_id"])), int(row["state_version"])


async def transition_run(
    conn: Conn,
    *,
    run_id: UUID,
    src: RunState,
    dst: RunState,
    reason: Reason | None = None,
    expected_version: int | None = None,
    detail: dict[str, Any] | None = None,
) -> int:
    """The worker's pre-grant transitions (SA:451); a refusal is logged here too (R082's "logged" half)."""
    try:
        row = await _call(
            conn,
            "SELECT app.transition_run(%s, %s, %s, %s, %s, %s) AS version",
            (run_id, src.value, dst.value, reason.value if reason else None, expected_version, Jsonb(detail or {})),
        )
    except (IllegalTransition, Refused) as exc:
        log.warning("transition refused: run=%s %s -> %s performer=transition_run: %s", run_id, src.value, dst.value, exc)
        raise
    if row is None:
        raise PersistenceError("transition_run returned nothing")
    return int(row["version"])


@dataclass(frozen=True)
class Appended:
    """What append_event wrote: the id, the per-run sequence and the stamped instant."""

    event_id: UUID
    sequence: int
    occurred_at: datetime


async def append_event(
    conn: Conn,
    *,
    run_id: UUID,
    type: EventType,
    payload: dict[str, Any],
    source: EventSource = EventSource.APPLICATION,
) -> Appended:
    """A tool.*, explanation.* or other non-reserved event (SA:452); the function assigns the sequence."""
    row = await _call(
        conn, "SELECT * FROM app.append_event(%s, %s, %s, %s)", (run_id, type.value, Jsonb(payload), source.value)
    )
    if row is None:
        raise PersistenceError("append_event returned nothing")
    return Appended(UUID(str(row["event_id"])), int(row["sequence"]), row["occurred_at"])


async def revoke_handles(conn: Conn, run_id: UUID) -> int:
    """Every live handle of the run is revoked (BS:364); the fence argument is T13's."""
    row = await _call(conn, "SELECT app.revoke_handles(%s, 1) AS n", (run_id,))
    return 0 if row is None else int(row["n"])


async def mark_unknown(conn: Conn, run_id: UUID) -> RunState:
    """EXECUTING → OUTCOME_UNKNOWN with handles revoked and a recover job (SA:467); idempotent."""
    row = await _call(conn, "SELECT app.mark_unknown(%s, 1) AS state", (run_id,))
    if row is None:
        raise PersistenceError("mark_unknown returned nothing")
    return RunState(str(row["state"]))


@dataclass(frozen=True)
class Frozen:
    """What freeze_proposal returned: the proposal's id and revision, and the run's new state_version."""

    proposal_id: UUID
    revision: int
    state_version: int


async def freeze_proposal(
    conn: Conn, *, run_id: UUID, draft_id: UUID, payload_canonical: bytes, expires_at: datetime
) -> Frozen:
    """The frozen bytes are hashed inside and compared with the validated draft's hash (SA:453)."""
    row = await _call(
        conn, "SELECT * FROM app.freeze_proposal(%s, %s, %s, %s)", (run_id, draft_id, payload_canonical, expires_at)
    )
    if row is None:
        raise PersistenceError("freeze_proposal returned nothing")
    return Frozen(UUID(str(row["proposal_id"])), int(row["revision"]), int(row["state_version"]))


@dataclass(frozen=True)
class Decided:
    """What record_decision returned: the run, its new state and state_version."""

    run_id: UUID
    state: RunState
    state_version: int


async def record_decision(
    conn: Conn,
    *,
    tenant_id: UUID,
    proposal_id: UUID,
    reviewer: UUID,
    expected_payload_sha256: str,
    decision: str,
    reason: str | None = None,
    idempotency_key: str | None = None,
) -> Decided:
    """First decision wins on the exact hash by an independent current reviewer (SA:454)."""
    row = await _call(
        conn,
        "SELECT * FROM app.record_decision(%s, %s, %s, %s, %s, %s, %s)",
        (tenant_id, proposal_id, reviewer, expected_payload_sha256, decision, reason, idempotency_key),
    )
    if row is None:
        raise PersistenceError("record_decision returned nothing")
    return Decided(UUID(str(row["run_id"])), RunState(str(row["state"])), int(row["state_version"]))


@dataclass(frozen=True)
class Invocation:
    """A resolved handle: the run, job and tenant it binds, plus the run and attempt state at resolution."""

    run_id: UUID
    job_id: UUID
    job_type: JobType
    tenant_id: UUID
    conversation_id: UUID
    run_state: RunState
    attempt_state: str | None


def allowed_tool(job_type: JobType, tool: Tool) -> None:
    """The AM-15 allowlist stays in Python (ruling 21); the function has already bound server, azp and expiry."""
    if tool not in JOB_RULES[job_type].allowed_tools:
        raise HandleRejected("tool is not allowed for this job type")


def handle_hash(handle: str) -> str:
    """What the table stores and what `_resolve_handle` computes server-side (same bytes, same digest)."""
    return sha256_hex(handle.encode("utf-8"))


async def resolve_invocation(conn: Conn, *, handle: str, azp: str, tool: Tool) -> Invocation:
    """The handle's run, tenant and job type for the calling server (SA:459); the handle never reaches a log."""
    row = await _call(conn, "SELECT * FROM app.resolve_invocation(%s, %s)", (handle, azp))
    if row is None:
        raise HandleRejected("invocation handle rejected")
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


@dataclass(frozen=True)
class Grant:
    """One run's execution grant with its latest attempt state (None before the first attempt row)."""

    action_id: UUID
    run_id: UUID
    proposal_id: UUID
    tenant_id: UUID
    conversation_id: UUID
    payload_sha256: str
    payload_canonical: bytes
    attempt_state: str | None
    detail: dict[str, Any] | None


def _grant(row: DictRow) -> Grant:
    return Grant(
        UUID(str(row["action_id"])),
        UUID(str(row["run_id"])),
        UUID(str(row["proposal_id"])),
        UUID(str(row["tenant_id"])),
        UUID(str(row["conversation_id"])),
        str(row["payload_sha256"]),
        bytes(row["payload_canonical"]),
        None if row["attempt_state"] is None else str(row["attempt_state"]),
        row["detail"],
    )


async def grant_execution(conn: Conn, *, handle: str, proposal_id: UUID) -> Grant:
    """The §13 gate inside the function; a replay returns the grant the run already has (SA:462)."""
    row = await _call(conn, "SELECT * FROM app.grant_execution(%s, %s)", (handle, proposal_id))
    if row is None:
        raise PersistenceError("grant_execution returned nothing")
    return _grant(row)


async def lookup_action(conn: Conn, *, handle: str) -> Grant:
    """The run's grant for a same-key redispatch or a final read-back (SA:466); NotFound before any grant."""
    row = await _call(conn, "SELECT * FROM app.lookup_action(%s)", (handle,))
    if row is None:
        raise NotFound("no grant for this run")
    return _grant(row)


async def mark_sent(conn: Conn, action_id: UUID) -> str:
    """`sent`, `already_sent`, `resolved` or `cancelled` (SA:463); committed by the caller before any I/O."""
    row = await _call(conn, "SELECT app.mark_sent(%s) AS outcome", (action_id,))
    return "sent" if row is None else str(row["outcome"])


async def record_outcome(conn: Conn, *, action_id: UUID, outcome: ActionOutcome) -> ToolOutcome:
    """RESOLVED plus the implied transition and the destination-sourced event (SA:464); returns what stands."""
    if outcome.status is ToolOutcome.UNKNOWN:
        raise ValueError("UNKNOWN is recorded by the worker through mark_unknown, never as an outcome")
    row = await _call(
        conn,
        "SELECT app.record_outcome(%s, %s, %s) AS outcome",
        (action_id, outcome.status.value, Jsonb(outcome.model_dump(mode="json"))),
    )
    if row is None:
        raise PersistenceError("record_outcome returned nothing")
    return ToolOutcome(str(row["outcome"]))


async def insert_job(conn: Conn, *, job_type: JobType, run_id: UUID, **ids: UUID | int | str) -> UUID | None:
    """Insert a wake-up under the caller's tenant unit; a duplicate dedup key is a no-op and returns None."""
    key = dedup_key(job_type, run_id=run_id, **ids) if job_type is not JobType.EXECUTE else dedup_key(job_type, **ids)
    # ON CONFLICT (target) and RETURNING need SELECT (spike §3): this helper serves the tests and the superuser;
    # the API's `resume_input` insert (T12) goes through a definer function or a target-less ON CONFLICT DO NOTHING.
    cur = await conn.execute(
        "INSERT INTO app.jobs (id, type, tenant_id, run_id, dedup_key)"
        " SELECT %s, %s, tenant_id, %s, %s FROM app.run_directory WHERE run_id = %s"
        " ON CONFLICT (dedup_key) DO NOTHING RETURNING id",
        (uuid4(), job_type.value, run_id, key, run_id),
    )
    row = await cur.fetchone()
    return None if row is None else UUID(str(row["id"]))


async def claim_job(conn: Conn, *, worker_name: str, tenant_ids: Sequence[UUID]) -> DictRow | None:
    """Claim the oldest available job of the first tenant that has one (BUILD_SPEC §11: SKIP LOCKED).

    jobs is under tenant_isolation for the worker (only the sweeper has sweeper_all), so the claim runs once per
    tenant with the tenant set (Plan E ruling 18); the caller rotates the order. Runs inside a transaction so the
    settings last exactly as long as the claim. TODO(T13): lease + fence + wake-ups instead of polling.
    """
    for tenant_id in tenant_ids:
        await set_tenant(conn, tenant_id)
        cur = await conn.execute(
            "UPDATE app.jobs SET claimed_by = %s, claimed_at = app.current_time(), attempts = attempts + 1"
            " WHERE id = (SELECT id FROM app.jobs WHERE done_at IS NULL AND claimed_at IS NULL"
            "             AND available_at <= app.current_time()"
            "             ORDER BY available_at, id FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING *",
            (worker_name,),
        )
        row = await cur.fetchone()
        if row is not None:
            return row
    return None


async def finish_job(conn: Conn, job_id: UUID) -> None:
    await conn.execute("UPDATE app.jobs SET done_at = app.current_time() WHERE id = %s", (job_id,))


async def requeue_job(conn: Conn, job_id: UUID, delay_seconds: int) -> None:
    """Release a claimed job and make it claimable again after `delay_seconds`. TODO(T13): bounded retries."""
    await conn.execute(
        "UPDATE app.jobs SET claimed_by = NULL, claimed_at = NULL,"
        " available_at = app.current_time() + make_interval(secs => %s) WHERE id = %s",
        (delay_seconds, job_id),
    )


async def mint_handle(
    conn: Conn, *, run_id: UUID, job_id: UUID, server: Server, azp: str, ttl_seconds: int = 60
) -> str:
    """A 256-bit capability bound to one job and one server (BUILD_SPEC §9); only its hash is stored (BS:360)."""
    handle = secrets.token_urlsafe(32)
    await conn.execute(
        "INSERT INTO app.invocation_context (handle_sha256, run_id, job_id, server, azp, expires_at)"
        " VALUES (%s, %s, %s, %s, %s, app.current_time() + make_interval(secs => %s))",
        (handle_hash(handle), run_id, job_id, server.value, azp, ttl_seconds),
    )
    return handle
```

Notes for the implementer: `insert_job` reads `run_directory` (no RLS) for the tenant so its callers (tests and the superuser today) need no tenant lookup; the worker never calls it, and the API's `resume_input` insert is T12's. `claim_job` requires the caller to be inside a transaction (the settings are transaction-local); `run_forever` already wraps it.

- [ ] **Step 3: Update `tests/plan_d/test_persistence_pure.py`**

The handle checks moved into SQL; keep the pure test for what remains. Replace the file's body with tests of `allowed_tool` (the same parametrisation as the old `test_rejections` reduced to the tool cases) and of `translate` for one code; delete `test_valid_read_handle_resolves_to_its_run_and_job` and `test_rejection_messages_never_echo_the_handle` (now in `tests/plan_e/test_persistence_errors.py` and the live write-path test). Keep the module docstring honest: "the server, azp, expiry and revocation checks live in `app._resolve_handle` (Task 4's live test)".

- [ ] **Step 4: Update the live persistence tests to the wrappers**

In `tests/e2e/test_migrations_and_persistence.py`:
- `new_run(conn, tenant_id=None, *, api)` keeps its superuser INSERTs for tenant, conversation and message (autocommit, so the `api` connection sees them) and creates the run through the function as the `api` role (`create_run` allows `api` only; the superuser gets `OC001`):

```python
async def new_run(conn: persistence.Conn, tenant_id: UUID | None = None, *, api: persistence.Conn) -> tuple:
    """A QUEUED run in a fresh conversation; on a new random tenant unless a seeded one is given. `conn` is the
    superuser (seeding), `api` the role connection that may call create_run."""
    conv, msg = uuid4(), uuid4()
    tenant = tenant_id or uuid4()
    if tenant_id is None:
        await conn.execute("INSERT INTO app.tenants (tenant_id, name) VALUES (%s, %s)", (tenant, f"t-{tenant}"))
    await conn.execute(
        "INSERT INTO app.conversations (conversation_id, tenant_id, created_by) VALUES (%s, %s, %s)", (conv, tenant, ALEX)
    )
    await conn.execute(
        "INSERT INTO app.messages (message_id, tenant_id, conversation_id, kind, text, author)"
        " VALUES (%s, %s, %s, 'investigate', 'x', %s)",
        (msg, tenant, conv, ALEX),
    )
    end = datetime.now(UTC).replace(microsecond=0)
    async with api.transaction():  # the function sets its own tenant
        run, _ = await persistence.create_run(
            api, tenant_id=tenant, conversation_id=conv, message_id=msg, requester=ALEX, intent=Intent.INVESTIGATE,
            asset_id="A17", start_at=end - timedelta(hours=24), end_at=end,
        )
    return tenant, conv, run
```
  The callers in `test_worker_live.py`, `test_mcp_read_live.py` and `test_mcp_write_live.py` are updated in Tasks 6 and 7 (they stay red until then, as declared); never wrap `new_run` in an outer transaction on `conn` (the `api` connection could not see the seeded conversation).
- `test_transition_follows_the_table_and_rolls_back_illegal_moves` → uses a `worker` role connection: `transition_run(worker, run_id=run, src=QUEUED, dst=RETRIEVING)` returns 2; `transition_run(..., src=RETRIEVING, dst=APPROVED)` raises `persistence.Refused` with code `POST_GRANT_TARGET` (the post-grant guard runs before the table); `transition_run(..., src=RETRIEVING, dst=QUEUED)` raises `IllegalTransition` (a pre-grant target with no row); a wrong `src` raises `VersionConflict`; `expected_version=9` raises `VersionConflict`; the run row is unchanged after each refusal. Wrap each call in its own `async with worker.transaction(): await persistence.set_tenant(...)` (or none: the function sets its own tenant) — the function needs no tenant unit.
- the event test → `append_event(worker, run_id=run, type=TOOL_STARTED, payload={...})` sequences 2, 3; `append_event(..., type=RUN_FAILED, ...)` raises `EventRuleViolation`; `append_event(api, ..., source=MODEL_SUMMARY)` raises `EventRuleViolation`.
- the job tests → `insert_job` twice returns an id then `None`; two `claim_job(conn, worker_name=..., tenant_ids=[tenant])` calls on two superuser connections inside transactions claim different jobs (as before, with the tenant list).
- the handle test → `mint_handle` as the worker role under a tenant unit (its INSERT grant), `resolve_invocation(mcp_read, handle=..., azp="ops-worker", tool=Tool.SEARCH_PROCEDURES)` returns the `Invocation`; at `mcp_exec` it raises `HandleRejected`; with `tool=Tool.CREATE_INCIDENT` at `mcp_read` it raises `HandleRejected` (the allowlist).
- Every test that used `force_rollback=True` on the superuser connection for isolation now creates rows through role connections, so it cleans up with `purge_run` in `finally` instead.

- [ ] **Step 5: Run everything**

Also in this task, because `Session.read` is gone and the skeleton's incident-sim must still start in Task 7: in `incident-sim/src/ops_incident_sim/app.py` replace `await st.session.read("SELECT 1", ())` by `await st.session.ping()` (one line; Task 8 rewrites the rest of that file).

Run: `uv run ruff format core/src/ops_core/persistence.py tests/plan_e tests/plan_d/test_persistence_pure.py tests/e2e/test_migrations_and_persistence.py incident-sim/src && uv run ruff check --fix core/src tests incident-sim/src && uv run python -m pytest tests/plan_e tests/plan_d/test_persistence_pure.py -q` → PASS. Then `OPS_LIVE=1 PYTHONUTF8=1 uv run python -m pytest tests/e2e/test_migrations_and_persistence.py tests/e2e/test_roles_live.py tests/e2e/test_definers_run_path_live.py tests/e2e/test_definers_write_path_live.py -q -x` → PASS. The other live modules (`test_mcp_write_live.py`, `test_worker_live.py`, `test_mcp_read_live.py`, `test_r105_walking_skeleton.py`) stay red until Tasks 6–7 rewrite the services (declared in the Global Constraints); do not touch them here. `PYTHONUTF8=1 uv run python scripts/check.py`: ruff, format and pytest GREEN; mypy may fail **only** in `api/`, `worker/`, `mcp-read/` and `mcp-write/` at call sites of the names this task removed or re-signed (`transition`, `check_invocation`, `resolve_handle`, `Session.read`, `create_run`, `append_event`, `claim_job`) — list them in the report; everything else must be clean.

- [ ] **Step 6: Commit**

```bash
git add core/src/ops_core/persistence.py tests/plan_e/test_persistence_errors.py tests/plan_d/test_persistence_pure.py tests/e2e/test_migrations_and_persistence.py incident-sim/src/ops_incident_sim/app.py
git commit -m "feat(core): persistence as thin wrappers over the definer functions, tenant units, hashed handles (T09)"
```

---
### Task 6: api and worker on their own roles and the definer functions

**Files:**
- Modify: `api/src/ops_api/store.py` (rewrite of `DbStore`; `map_refusal`), `api/src/ops_api/app.py` (role `api`, clock-profile assertion, `ping`, `AuthorityViolation` → 503 with a log line), `worker/src/ops_worker/main.py` (role `worker`, tenant rotation, assertion), `worker/src/ops_worker/handlers.py` (functions; UNKNOWN → `mark_unknown`; `revoke_handles` at job end; `supersedes_run_id` into the payload), `worker/src/ops_worker/proposals.py` (`build_proposal(..., supersedes_run_id)`), `tests/plan_d/test_api.py` (FakeStore unchanged in shape; one new test for the mapping), `tests/plan_d/test_worker.py` (`build_proposal` gains the argument), `tests/e2e/test_worker_live.py`
- Create: `tests/plan_e/test_api_store_mapping.py`

**Interfaces:**
- Consumes: `ops_core.persistence` (Task 5), `ops_core.settings.Role`, `Profile`, `profile()`.
- Produces: `ops_api.store.map_refusal(exc: persistence.Refused) -> Exception` (`NOT_REVIEWER`, `SELF_REVIEW`, `MEMBERSHIP_INACTIVE` → `Forbidden`; `SLOT_OCCUPIED` → `Conflict("SLOT_OCCUPIED")`; anything else → `Conflict("VERSION_CONFLICT")`); the `Store` protocol unchanged.
- Produces: `ops_worker.main.rotate(tenants: list[UUID], start: int) -> list[UUID]` (pure); `handlers.execute` returns `True` after recording UNKNOWN through `persistence.mark_unknown`.

- [ ] **Step 1: Write the failing unit test for the API's refusal mapping**

Create `tests/plan_e/test_api_store_mapping.py`:

```python
"""A definer function's DETAIL code becomes the HTTP class BUILD_SPEC §16 names (403 for an independence or
membership refusal, 409 for a lost race or a stale version); nothing else leaks from the database."""

import pytest
from ops_api import store
from ops_core import persistence


@pytest.mark.parametrize(
    ("code", "expected", "http_code"),
    [
        ("NOT_REVIEWER", store.Forbidden, None),
        ("SELF_REVIEW", store.Forbidden, None),
        ("MEMBERSHIP_INACTIVE", store.Forbidden, None),
        ("SLOT_OCCUPIED", store.Conflict, "SLOT_OCCUPIED"),
        ("ANYTHING_ELSE", store.Conflict, "VERSION_CONFLICT"),
    ],
)
def test_map_refusal(code: str, expected: type[Exception], http_code: str | None) -> None:
    mapped = store.map_refusal(persistence.Refused(code))
    assert isinstance(mapped, expected)
    if http_code is not None:
        assert isinstance(mapped, store.Conflict) and mapped.code == http_code
```

Run: `uv run python -m pytest tests/plan_e/test_api_store_mapping.py -q` → FAIL (`AttributeError: map_refusal`).

- [ ] **Step 2: Rewrite `api/src/ops_api/store.py`**

Replace the module docstring, add `map_refusal`, and replace `DbStore`:

```python
"""The API's door to the database as role `api` (T09 shape): identity through `resolve_identity`, admission through
`create_run`, decisions through `record_decision`; reads under the tenant's unit, which RLS scopes.

Admission still commits message, run, job and `run.accepted` together (BUILD_SPEC §7) and a decision commits the
decision row, the transition, the `execute` wake-up and `approval.recorded` together (§12): the functions do the
writing inside the API's transaction. TODO(T12): Idempotency-Key, admission router.
"""
```

```python
def map_refusal(exc: persistence.Refused) -> Exception:
    """A function's DETAIL code → the HTTP class BUILD_SPEC §16 names; the code itself never reaches the client."""
    if exc.code in ("NOT_REVIEWER", "SELF_REVIEW", "MEMBERSHIP_INACTIVE"):
        return Forbidden()
    if exc.code == "SLOT_OCCUPIED":
        return Conflict("SLOT_OCCUPIED")
    return Conflict("VERSION_CONFLICT")
```

```python
class DbStore:
    """The PostgreSQL implementation of `Store` over one autocommit connection as role `api`."""

    def __init__(self, conn: persistence.Conn) -> None:
        self.session = persistence.Session(conn)  # ruling 24: one unit of work at a time, each a real transaction

    async def membership(self, issuer: str, subject: UUID) -> Membership | None:
        """Resolve a verified subject to its active tenant membership, or None."""
        async with self.session.unit() as conn:  # the function walks the tenants itself (Plan E ruling 4)
            rows = await persistence.resolve_identity(conn, issuer=issuer, subject=subject)
        return single_tenant(rows)

    async def create_conversation(self, tenant_id: UUID, created_by: UUID) -> UUID:
        """Create an empty conversation in the tenant."""
        cid = uuid4()
        async with self.session.unit(tenant_id) as conn:
            await conn.execute(
                "INSERT INTO app.conversations (conversation_id, tenant_id, created_by) VALUES (%s, %s, %s)",
                (cid, tenant_id, created_by),
            )
        return cid

    async def admit(
        self,
        *,
        tenant_id: UUID,
        conversation_id: UUID,
        requester: UUID,
        request: MessageRequest,
        start_at: datetime,
        end_at: datetime,
    ) -> Accepted:
        """Commit message, run, job and `run.accepted` together."""
        if request.context is None or request.context.asset_id is None:  # app.py checked the route
            raise ValueError("admit requires an investigate request with asset_id")
        message_id = uuid4()
        try:
            async with self.session.unit(tenant_id) as conn:
                cur = await conn.execute(
                    "SELECT 1 FROM app.conversations WHERE conversation_id = %s AND tenant_id = %s",
                    (conversation_id, tenant_id),
                )
                if await cur.fetchone() is None:
                    raise NotFound
                await conn.execute(
                    "INSERT INTO app.messages (message_id, tenant_id, conversation_id, kind, text, context, author)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (
                        message_id,
                        tenant_id,
                        conversation_id,
                        request.kind.value,
                        request.text,
                        Jsonb(request.context.model_dump(mode="json")),
                        requester,
                    ),
                )
                # The function validates the supersedes target against tenant and conversation (SA:450).
                run_id, version = await persistence.create_run(
                    conn,
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                    message_id=message_id,
                    requester=requester,
                    intent=Intent.INVESTIGATE,
                    asset_id=request.context.asset_id,
                    start_at=start_at,
                    end_at=end_at,
                    supersedes_run_id=request.supersedes_run_id,
                )
        except persistence.NotFound as exc:
            raise NotFound from exc
        except persistence.Refused as exc:
            raise map_refusal(exc) from exc
        return Accepted(conversation_id, message_id, run_id, RunState.QUEUED.value, version)

    async def run(self, tenant_id: UUID, run_id: UUID) -> dict[str, Any] | None:
        """Read one run row in the tenant (RLS scopes the unit; the WHERE is belt and braces)."""
        async with self.session.unit(tenant_id) as conn:
            cur = await conn.execute("SELECT * FROM app.runs WHERE run_id = %s AND tenant_id = %s", (run_id, tenant_id))
            row = await cur.fetchone()
        return None if row is None else dict(row)

    async def proposal(self, tenant_id: UUID, proposal_id: UUID) -> dict[str, Any] | None:
        """Read one proposal with its run's requester and state."""
        async with self.session.unit(tenant_id) as conn:
            cur = await conn.execute(
                "SELECT p.*, r.requester, r.state AS run_state FROM app.proposals p JOIN app.runs r ON r.run_id = p.run_id"
                " WHERE p.proposal_id = %s AND p.tenant_id = %s",
                (proposal_id, tenant_id),
            )
            row = await cur.fetchone()
        return None if row is None else dict(row)

    async def decide(self, *, tenant_id: UUID, proposal_id: UUID, reviewer: UUID, request: DecisionRequest) -> Decided:
        """Record the first decision on the exact revision and hash, or raise Conflict / Forbidden / NotFound."""
        try:
            async with self.session.unit(tenant_id) as conn:
                cur = await conn.execute(
                    "SELECT revision FROM app.proposals WHERE proposal_id = %s AND tenant_id = %s", (proposal_id, tenant_id)
                )
                proposal = await cur.fetchone()
                if proposal is None:
                    raise NotFound
                if proposal["revision"] != request.expected_revision:
                    raise Conflict("VERSION_CONFLICT")  # the hash is the function's check; the revision is ours
                decided = await persistence.record_decision(
                    conn,
                    tenant_id=tenant_id,
                    proposal_id=proposal_id,
                    reviewer=reviewer,
                    expected_payload_sha256=request.expected_payload_sha256,
                    decision=request.decision,
                    reason=request.reason,
                )
        except persistence.NotFound as exc:
            raise NotFound from exc
        except persistence.VersionConflict as exc:
            raise Conflict("VERSION_CONFLICT") from exc
        except persistence.Refused as exc:
            raise map_refusal(exc) from exc
        return Decided(proposal_id, decided.run_id, request.decision, decided.state.value, decided.state_version)

    async def events(self, tenant_id: UUID, run_id: UUID, *, after: int, limit: int) -> list[dict[str, Any]]:
        """List a run's events after a sequence number."""
        async with self.session.unit(tenant_id) as conn:
            cur = await conn.execute(
                "SELECT sequence, type, source, occurred_at, payload FROM app.events"
                " WHERE run_id = %s AND tenant_id = %s AND sequence > %s ORDER BY sequence LIMIT %s",
                (run_id, tenant_id, after, limit),
            )
            rows = await cur.fetchall()
        return [dict(r) for r in rows]
```

Drop the now-unused imports (`psycopg`, `JobType`, `EventSource`, `EventType`, `Performer`, `Reason`) and keep `check_reviewer` and `single_tenant` as they are (the Python pre-check stays as defence in depth: app.py still calls it before `decide`).

In `api/src/ops_api/app.py`: the production store factory becomes `st.DbStore(await persistence.connect(settings.app_postgres(Role.API)))` (import `Role` from `ops_core.settings`); in `create_app`'s lifespan, after the store is installed and before the keys load, add

```python
        if isinstance(app.state.store, st.DbStore):
            await persistence.assert_clock_profile(app.state.store.session.conn, settings.profile())
```

Replace `await store.session.read("SELECT 1", ())` in `ready` with `await store.session.ping()`. Add an exception handler:

```python
    @app.exception_handler(persistence.AuthorityViolation)
    async def _authority(_: Request, exc: persistence.AuthorityViolation) -> Response:
        log.error("deployment error: %s", exc)  # the API is connected as a role a function does not accept
        return safe(503, ErrorCode.UNAVAILABLE, "service misconfigured")
```

(`log = logging.getLogger("ops_api")` at module level if absent.)

- [ ] **Step 3: Run the API unit tests**

Run: `uv run python -m pytest tests/plan_e/test_api_store_mapping.py tests/plan_d/test_api.py -q` → PASS (`FakeStore` implements the unchanged `Store` protocol).

- [ ] **Step 4: Rewrite the worker's handlers and loop**

`worker/src/ops_worker/proposals.py`: `build_proposal` gains the keyword argument `supersedes_run_id: UUID | None` and passes it to `ProposalPayload(...)` (the frozen document must carry the run's value; `freeze_proposal` refuses otherwise). Update `tests/plan_d/test_worker.py::test_build_proposal_binds_hash_to_canonical_bytes` to pass `supersedes_run_id=None`.

`worker/src/ops_worker/handlers.py` — replace `_event`, `_fail`, `investigate`, `_draft_and_freeze`, `execute` and `handle`:

```python
async def _event(
    deps: Deps,
    run: dict[str, Any],
    type: EventType,
    payload: dict[str, Any],
    source: EventSource = EventSource.APPLICATION,
) -> None:
    async with deps.conn.transaction():  # the function finds the tenant itself (run_directory)
        await persistence.append_event(deps.conn, run_id=run["run_id"], type=type, payload=payload, source=source)


async def _fail(deps: Deps, run: dict[str, Any], src: RunState, dst: RunState, message: str) -> None:
    """A pre-grant failure state through transition_run, which emits the matching run.* event itself (SA:451)."""
    async with deps.conn.transaction():
        await persistence.transition_run(
            deps.conn, run_id=run["run_id"], src=src, dst=dst, detail={"message": message}
        )


async def investigate(deps: Deps, job: dict[str, Any]) -> None:
    """Retrieve evidence, draft with the model route, freeze the proposal and await approval."""
    tenant_id: UUID = job["tenant_id"]
    async with deps.conn.transaction():
        await persistence.set_tenant(deps.conn, tenant_id)  # the worker's own reads and inserts are RLS-scoped
        run = dict(await persistence.run_row(deps.conn, job["run_id"], lock=True))
        if run["state"] != RunState.QUEUED.value:
            log.info("investigate job %s: run already %s", job["id"], run["state"])
            return
        cur = await deps.conn.execute("SELECT text FROM app.messages WHERE message_id = %s", (run["message_id"],))
        message = await cur.fetchone()
        if message is None:
            raise persistence.NotFound("message not found")
        text = str(message["text"])
        await persistence.transition_run(deps.conn, run_id=run["run_id"], src=RunState.QUEUED, dst=RunState.RETRIEVING)
        handle = await persistence.mint_handle(
            deps.conn, run_id=run["run_id"], job_id=job["id"], server=Server.READ, azp="ops-worker"
        )
    await _event(deps, run, EventType.TOOL_STARTED, {"message": "search_procedures"})
    try:
        # The tool input caps `query` at 500 characters (schemas/tools); the message itself may be 4,000.
        doc = await deps.mcp.call(
            deps.urls.mcp_read,
            handle=handle,
            tool="search_procedures",
            arguments={"query": text[:QUERY_CHARS], "limit": 3, "mode": "lexical"},
        )
        evidence = proposals.evidence_from_search(doc)
    except (McpCallFailed, ValueError) as exc:
        log.warning("investigate job %s: retrieval failed: %s", job["id"], exc)
        await _fail(deps, run, RunState.RETRIEVING, RunState.FAILED, "retrieval failed")
        return
    await _event(deps, run, EventType.TOOL_COMPLETED, {"message": "search_procedures"})
    if not evidence:
        await _fail(deps, run, RunState.RETRIEVING, RunState.INSUFFICIENT_EVIDENCE, "no procedure section matched")
        return
    async with deps.conn.transaction():
        await persistence.transition_run(deps.conn, run_id=run["run_id"], src=RunState.RETRIEVING, dst=RunState.DRAFTING)
    try:
        await _draft_and_freeze(deps, run, text, evidence, str(doc["data"]["corpus_version"]))
    except Exception:
        # No reclaim until T13: a run left in DRAFTING would hold its conversation slot with the job claimed forever.
        log.exception("investigate job %s: drafting or freezing failed", job["id"])
        await _fail(deps, run, RunState.DRAFTING, RunState.FAILED, "drafting failed")


async def _draft_and_freeze(
    deps: Deps, run: dict[str, Any], text: str, evidence: list[EvidenceItem], corpus_version: str
) -> None:
    """Draft from the evidence and freeze the proposal; any failure here is the caller's to turn into FAILED."""
    request = DraftRequest(asset_id=run["asset_id"], text=text, start_at=run["start_at"], end_at=run["end_at"])
    draft = await deps.generator.generate(request, evidence)
    freeze_allowed(Intent(run["intent"]))  # an answer_only run never freezes a proposal (SA:453)
    now = datetime.now(UTC).replace(microsecond=0)
    proposal_id, draft_id = uuid4(), uuid4()
    frozen = proposals.build_proposal(
        tenant_id=run["tenant_id"],
        run_id=run["run_id"],
        proposal_id=proposal_id,
        revision=1,
        asset_id=run["asset_id"],
        start_at=run["start_at"],
        end_at=run["end_at"],
        draft=draft,
        evidence=evidence,
        corpus_version=corpus_version,
        now=now,
        supersedes_run_id=run["supersedes_run_id"],
    )
    async with deps.conn.transaction():
        await persistence.set_tenant(deps.conn, run["tenant_id"])
        # The worker's own INSERT (AM-20.2 drafts: ins); draft_sha256 is what freeze_proposal recomputes over the
        # bytes it receives and compares (SA:453). The payload itself is never written here (SA:496).
        await deps.conn.execute(
            "INSERT INTO app.drafts (id, tenant_id, run_id, draft_sha256, validated, kind) VALUES (%s, %s, %s, %s, true, %s)",
            (draft_id, run["tenant_id"], run["run_id"], frozen.sha256, draft.kind),
        )
        await persistence.append_event(
            deps.conn,
            run_id=run["run_id"],
            type=EventType.EXPLANATION_READY,
            payload={
                "message": f"Drafted by model route {frozen.manifest.model_route.value} "
                f"(prompt {frozen.manifest.prompt_version}).",
                "evidence_refs": list(frozen.payload.evidence_refs),
            },
            source=EventSource.MODEL_SUMMARY,
        )
        await persistence.freeze_proposal(
            deps.conn,
            run_id=run["run_id"],
            draft_id=draft_id,
            payload_canonical=frozen.canonical,
            expires_at=frozen.payload.expires_at,
        )


async def execute(deps: Deps, job: dict[str, Any]) -> bool:
    """Call `create_incident` on mcp-write for an approved run; True when the job is finished, False when re-queued."""
    async with deps.conn.transaction():
        await persistence.set_tenant(deps.conn, job["tenant_id"])
        run = dict(await persistence.run_row(deps.conn, job["run_id"], lock=True))
        # APPROVED or EXECUTING (JOB_RULES[EXECUTE].run_states): after a transport failure past the grant, the
        # re-queued job resends under the same action id (grant_execution's replay rule; Plan E ruling 6).
        if RunState(run["state"]) not in JOB_RULES[JobType.EXECUTE].run_states:
            log.info("execute job %s: run is %s, nothing to dispatch", job["id"], run["state"])
            return True
        proposal_id: UUID = run["active_proposal_id"]
        handle = await persistence.mint_handle(
            deps.conn, run_id=run["run_id"], job_id=job["id"], server=Server.WRITE, azp="ops-worker"
        )
    try:
        doc = await deps.mcp.call(
            deps.urls.mcp_write, handle=handle, tool="create_incident", arguments={"proposal_id": str(proposal_id)}
        )
    except McpCallFailed as exc:
        # mcp-write owns the grant and the outcome; the run stays APPROVED and the job retries, which is safe because
        # create_incident is idempotent per run. The worker records nothing it did not observe (BUILD_SPEC §1).
        # TODO(T13): bounded retries; TODO(T22): reconciliation.
        log.warning("execute job %s: %s; re-queued in %s s", job["id"], exc, EXECUTE_RETRY_SECONDS)
        async with deps.conn.transaction():
            await persistence.set_tenant(deps.conn, job["tenant_id"])  # RLS: without it the UPDATE touches no row
            await persistence.requeue_job(deps.conn, job["id"], EXECUTE_RETRY_SECONDS)
        return False
    data = doc.get("data") or {}
    log.info("execute job %s: %s %s", job["id"], doc.get("status"), data.get("status"))
    if data.get("status") == "UNKNOWN":
        # mcp-write reports uncertainty after SENT but may not record it (SA:467: mark_unknown is the worker's).
        async with deps.conn.transaction():
            await persistence.mark_unknown(deps.conn, run["run_id"])
    return True


async def handle(deps: Deps, job: dict[str, Any]) -> None:
    """Dispatch a claimed job by type, then revoke its handles and mark it done unless the handler re-queued it."""
    kind = JobType(job["type"])
    if kind is JobType.INVESTIGATE:
        await investigate(deps, job)
    elif kind is JobType.EXECUTE:
        if not await execute(deps, job):
            return
    else:
        log.info("job %s of type %s is not handled by the walking skeleton", job["id"], kind.value)
    async with deps.conn.transaction():
        if job.get("run_id") is not None:
            await persistence.revoke_handles(deps.conn, job["run_id"])  # BS:364: handles die with the job
        await persistence.set_tenant(deps.conn, job["tenant_id"])
        await persistence.finish_job(deps.conn, job["id"])
```

Remove the `Jsonb` and `Performer` imports from handlers.py and import `JOB_RULES` from `ops_core.jobs`; the module docstring's first sentence becomes "every state change goes through the definer functions as role `worker` (`transition_run`, `freeze_proposal`, `mark_unknown`), …".

`worker/src/ops_worker/main.py`:

```python
def rotate(tenants: list[UUID], start: int) -> list[UUID]:
    """The tenants in claim order for one poll: a different first tenant each time, so none starves (ruling 18)."""
    if not tenants:
        return []
    k = start % len(tenants)
    return tenants[k:] + tenants[:k]


async def run_forever(deps: handlers.Deps, stop: asyncio.Event) -> None:
    """Claim, handle, repeat. A failed handler is logged and its job stays claimed (T13 reclaims); a broken
    connection ends the loop, and readiness follows it (see health_app)."""
    polls = 0
    while not stop.is_set():
        try:
            async with deps.conn.transaction():
                order = rotate(await persistence.tenants(deps.conn), polls)
                job = await persistence.claim_job(deps.conn, worker_name=deps.worker_name, tenant_ids=order)
            polls += 1
            if job is not None:
                await handlers.handle(deps, dict(job))
                continue
        except psycopg.OperationalError:
            ...  # unchanged
```

(keep the two `except` blocks and the sleep exactly as they are). In `_main`, both connections use `settings.app_postgres(Role.WORKER)` (import `Role`), and after `probe` is opened: `await persistence.assert_clock_profile(probe, settings.profile())`.

- [ ] **Step 5: Update the worker's live test**

In `tests/e2e/test_worker_live.py`:
- `ScriptedMcp.__init__(self, read: Conn, write: Conn)` holds a `mcp_read` and a `mcp_exec` role connection; `call` resolves with `persistence.resolve_invocation(self.read if server is Server.READ else self.write, handle=handle, azp="ops-worker", tool=Tool(tool))`.
- A fixture `worker_deps(role_conn)` builds `handlers.Deps(conn=await role_conn(Role.WORKER), ...)`.
- `_investigate_then_execute`: `new_run(app_conn, ALPHA, api=api)` (the seeded tenant: `record_decision` needs SAM's reviewer membership); the direct decision INSERT, `persistence.transition(... APPROVED)` and `insert_job` are replaced by one call `await persistence.record_decision(api, tenant_id=tenant, proposal_id=..., reviewer=SAM, expected_payload_sha256=proposal["payload_sha256"], decision="approve")` on the `api` role connection; the event list assertion gains `("run.accepted", "application")` first and `("approval.recorded", "application")` before the execute step; the history assertion is unchanged.
- `test_drafting_failure_fails_the_run` and `test_unreachable_write_server_requeues_the_execute_job`: no `force_rollback` (rows are written by role connections); `purge_run` in `finally`. The "approve directly" step in the requeue test uses `record_decision` the same way.
- `test_unreachable_write_server_requeues_the_execute_job` additionally proves the re-queued job is dispatched again once its run is `EXECUTING`: after the first failure, a scripted caller that grants and marks SENT then fails leaves the run `EXECUTING`; the next `handlers.handle` on the same job must call `create_incident` again (`mcp.calls` grows), not finish the job unsent.
- New test `test_unknown_envelope_is_recorded_by_the_worker`: a `ScriptedMcp` subclass whose `create_incident` returns `{"status": "outcome", "data": {"status": "UNKNOWN", ...}}` after the handle resolves; the run must end `OUTCOME_UNKNOWN` with `action.uncertain` last and a `recover` job inserted; but `mark_unknown` requires the run to be `EXECUTING` with a grant, which only mcp-write's `grant_execution` produces, so this scripted caller first calls `persistence.grant_execution(self.write, handle=handle, proposal_id=...)` and `persistence.mark_sent(self.write, action_id)` itself, then returns the UNKNOWN envelope.
- `own_job` is unchanged (superuser); it returns `tenant_id` now, which `handlers.handle` reads.

- [ ] **Step 6: Run the gates**

Run: `uv run ruff format api/src worker/src tests/plan_e tests/plan_d/test_api.py tests/plan_d/test_worker.py tests/e2e/test_worker_live.py && uv run ruff check --fix api/src worker/src tests && uv run python -m pytest tests/plan_d/test_api.py tests/plan_d/test_worker.py tests/plan_e -q` → PASS; `OPS_LIVE=1 PYTHONUTF8=1 uv run python -m pytest tests/e2e/test_worker_live.py tests/e2e/test_definers_write_path_live.py -q -x` → PASS; `PYTHONUTF8=1 uv run python scripts/check.py` — mypy residue may remain only in `mcp-read/` and `mcp-write/` (Task 7); everything else GREEN. Record the residue in the report.

- [ ] **Step 7: Commit**

```bash
git add api/src/ops_api worker/src/ops_worker tests/plan_e/test_api_store_mapping.py tests/plan_d/test_api.py tests/plan_d/test_worker.py tests/e2e/test_worker_live.py
git commit -m "feat(api,worker): run as their own roles through the definer functions; the worker records UNKNOWN and revokes handles (T09)"
```

---
### Task 7: mcp-read and mcp-write on their own roles and the definer functions; R105 re-run

**Files:**
- Modify: `mcp-read/src/ops_mcp_read/server.py` (role `mcp_read`, `resolve_invocation`, `ping`, assertion), `mcp-write/src/ops_mcp_write/server.py` (role `mcp_exec`, `resolve_invocation`, refusal mapping, `ping`, assertion), `mcp-write/src/ops_mcp_write/execution.py` (rewrite on the functions; UNKNOWN recorded by nobody here), `tests/plan_d/test_mcp_write.py` (`next_step` unchanged; `GrantRefused` → `persistence.Refused` where referenced), `tests/e2e/test_mcp_read_live.py`, `tests/e2e/test_mcp_write_live.py`, `tests/e2e/test_r105_walking_skeleton.py` (`EXPECTED_EVENTS` unchanged; `mint_handle` as the worker role; `keys` check), `reports/skeleton/r105-walking-skeleton.txt` (re-generated)

**Interfaces:**
- Consumes: `ops_core.persistence` (Task 5): `resolve_invocation`, `grant_execution`, `lookup_action`, `mark_sent`, `record_outcome`, `Grant`, `Invocation`, `Refused`, `HandleRejected`, `NotFound`.
- Produces: `ops_mcp_write.execution.create_incident(deps, *, handle: str, proposal_id: UUID) -> ActionOutcome` (the raw handle replaces the `Invocation` argument: the functions re-resolve it); `next_step` unchanged; `GrantRefused` removed (the server maps `persistence.Refused` to the `GRANT_REFUSED` tool error).

- [ ] **Step 1: Check the unit tests**

`tests/plan_d/test_mcp_write.py` references neither `GrantRefused` nor `create_incident`'s signature; run `uv run python -m pytest tests/plan_d/test_mcp_write.py -q` → PASS before and after Step 2 (the `next_step` and envelope tests are the contract).

- [ ] **Step 2: Rewrite `mcp-write/src/ops_mcp_write/execution.py`**

```python
"""The write path in AM-13 order: grant → INTENT → SENT (committed before I/O) → POST → RESOLVED, as role mcp_exec
through the definer functions grant_execution, mark_sent, record_outcome and lookup_action (T09 shape).

Replay rule (Plan D review focus 1): execution_grant is UNIQUE (run_id), so a second `create_incident` for the same run
finds the existing grant; if its attempt is RESOLVED the stored outcome is returned without touching the destination,
otherwise the same action id and bytes are re-sent and the destination's idempotent key answers. There is never a
second action id for one run. A transport failure after SENT is reported as UNKNOWN and recorded by nobody here: the
worker holds `mark_unknown` (SA:467; Plan E ruling 6).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

import httpx2
from ops_core import persistence
from ops_core.outcomes import ActionOutcome, ToolOutcome
from ops_core.tokens import WorkloadTokenSource

from ops_mcp_write import destination

log = logging.getLogger(__name__)


def next_step(attempt_state: str | None) -> Literal["stored", "send", "resend"]:
    """What a (re)call does for an attempt in this state; states the skeleton cannot handle are refused."""
    if attempt_state == "RESOLVED":
        return "stored"
    if attempt_state == "INTENT":
        return "send"
    if attempt_state == "SENT":
        return "resend"
    raise ValueError(f"attempt state {attempt_state} is not handled by the walking skeleton")


@dataclass
class Deps:
    """What the write path needs: the database session, an HTTP client and the destination's URL and token source."""

    session: persistence.Session
    http: httpx2.AsyncClient
    destination_url: str
    destination_token: WorkloadTokenSource


def _stored(grant: persistence.Grant) -> ActionOutcome:
    if grant.detail is None:
        raise RuntimeError("a resolved attempt has no stored outcome")
    return ActionOutcome.model_validate_json(json.dumps(grant.detail))


async def create_incident(deps: Deps, *, handle: str, proposal_id: UUID) -> ActionOutcome:
    """Four units of work in AM-13 order; the destination call sits between two commits, never inside one."""
    async with deps.session.unit() as conn:  # the functions resolve the handle and set the tenant themselves
        grant = await persistence.grant_execution(conn, handle=handle, proposal_id=proposal_id)
    step = next_step(grant.attempt_state)
    if step == "stored":
        return _stored(grant)
    if step == "send":
        async with deps.session.unit() as conn:
            sent = await persistence.mark_sent(conn, grant.action_id)  # committed here, before any I/O
        if sent == "resolved":  # a concurrent caller finished first
            async with deps.session.unit() as conn:
                return _stored(await persistence.lookup_action(conn, handle=handle))
        if sent == "cancelled":
            # TODO(T22): request_abort + the abort POST; until then the caller sees the grant's INTENT standing.
            return destination.unknown(grant.action_id, grant.payload_sha256)
    try:
        reply = await destination.post_incident(
            deps.http,
            url=deps.destination_url,
            token=await deps.destination_token.token(),
            action_id=grant.action_id,
            payload_sha256=grant.payload_sha256,
            payload_canonical=grant.payload_canonical,
        )
        outcome = destination.classify(reply, action_id=grant.action_id, payload_sha256=grant.payload_sha256)
    except Exception:  # after SENT nothing may escape as "no effect" (SA:356, ruling 21): UNKNOWN, reconciled
        log.exception("destination call for action %s failed after SENT", grant.action_id)
        return destination.unknown(grant.action_id, grant.payload_sha256)
    if outcome.status is ToolOutcome.UNKNOWN:
        # A lost reply, a 503 or a malformed document: nothing is recorded here; the worker holds mark_unknown
        # (SA:467, Plan E ruling 6), and record_outcome refuses UNKNOWN by design.
        return outcome
    # Outside the try on purpose: a database failure here is a 500 and the replay recovers (the attempt is still SENT).
    async with deps.session.unit() as conn:
        standing = await persistence.record_outcome(conn, action_id=grant.action_id, outcome=outcome)
    if standing is outcome.status:
        return outcome
    # A concurrent caller's record stands: read it back in its own unit (lookup_action re-checks the handle's expiry,
    # and a slow destination must not roll the recorded outcome back with a HandleRejected).
    async with deps.session.unit() as conn:
        return _stored(await persistence.lookup_action(conn, handle=handle))
```

In `mcp-write/src/ops_mcp_write/server.py`, the tool body becomes:

```python
        try:
            async with state.deps.session.unit() as conn:
                await persistence.resolve_invocation(
                    conn, handle=handle, azp=token.client_id, tool=ToolName.CREATE_INCIDENT
                )  # binds server, azp, expiry and the tool allowlist before any work (SA:459)
            outcome = await execution.create_incident(state.deps, handle=handle, proposal_id=proposal_id)
        except persistence.HandleRejected as exc:
            return envelope("create_incident", error=tool_error("INVALID_HANDLE", str(exc)))
        except persistence.Refused as exc:
            return envelope("create_incident", error=tool_error("GRANT_REFUSED", f"grant refused: {exc.code}"))
        except persistence.NotFound:
            return envelope("create_incident", error=tool_error("NOT_FOUND", "run not found"))
        return outcome_envelope(outcome)
```

(`Server` import dropped.) The lifespan connects as `settings.app_postgres(Role.MCP_EXEC)` and, after the session exists, `await persistence.assert_clock_profile(state.deps.session.conn, settings.profile())`; `ready` uses `await state.deps.session.ping()`.

In `mcp-read/src/ops_mcp_read/server.py`, the tool body's resolution becomes `invocation = await persistence.resolve_invocation(conn, handle=handle, azp=token.client_id, tool=ToolName.SEARCH_PROCEDURES)` (same `except persistence.HandleRejected`); the lifespan connects as `settings.app_postgres(Role.MCP_READ)` and asserts the clock profile; `ready` uses `ping()`.

- [ ] **Step 3: Update the live tests**

`tests/e2e/test_mcp_read_live.py`: drop the `async with app_conn.transaction():` wrapper (the `api` connection could not see an uncommitted conversation); `new_run(app_conn, ALPHA, api=await role_conn(Role.API))`; the handle is minted by a worker role connection inside `async with worker.transaction(): await persistence.set_tenant(worker, ALPHA); handle = await persistence.mint_handle(worker, ...)`; everything else unchanged.

`tests/e2e/test_mcp_write_live.py`:
- `approved_run(app_conn, *, api, worker)` builds the run through the functions on the seeded tenant ALPHA (SAM is its reviewer, ALEX its requester; no membership seeding and no `purge_tenant` needed): `new_run(app_conn, ALPHA, api=api)` with no outer transaction, `transition_run(worker, …QUEUED→RETRIEVING→DRAFTING)`, then in one transaction on the worker connection (`set_tenant` is transaction-local; on autocommit the INSERT would meet RLS): `async with worker.transaction(): await persistence.set_tenant(worker, ALPHA); <the drafts INSERT>; await persistence.freeze_proposal(worker, run_id=run, draft_id=draft, payload_canonical=canonical, expires_at=…)` (the payload's `tenant_id` is ALPHA and it carries no `supersedes_run_id`), then `record_decision(api, tenant_id=ALPHA, proposal_id=proposal, reviewer=SAM, expected_payload_sha256=sha, decision="approve")`. The handle is minted by the worker role under the tenant.
- The witness connection in `test_write_path_twice` uses `settings.superuser_postgres()`.
- `make_deps(session, …)` builds the session over a `mcp_exec` role connection (`await role_conn(Role.MCP_EXEC)`), and every `execution.create_incident(deps, handle=handle, proposal_id=proposal)` call passes the raw handle.
- `test_exception_after_sent_becomes_outcome_unknown` now asserts the run is still `EXECUTING` with the attempt `SENT` and the events `run.accepted, proposal.ready, approval.recorded, action.granted, action.dispatched` (the worker, not mcp-write, records UNKNOWN: Task 6's live test covers that); its name becomes `test_exception_after_sent_returns_unknown_and_records_nothing`, and it gains a second case in which `destination.post_incident` is monkeypatched to return `None` (a transport failure the client already swallowed) and a third in which it returns a reply with status 503 and an empty document: all three must yield the `UNKNOWN` envelope with the attempt `SENT` and the run `EXECUTING` (round-2 finding NI1: a classified UNKNOWN once reached `record_outcome` and raised).
- The event-list assertions gain `proposal.ready` and `approval.recorded` after `run.accepted` (the functions emit them now).

`tests/e2e/test_r105_walking_skeleton.py`: the destination's answers to the persona and worker tokens become `(403, 403)` once Task 8 lands; in this task keep `(401, 401)` and note it; `EXPECTED_EVENTS` is unchanged (the API's path produced the same nine events; check the list matches what the functions emit: `run.accepted`, `tool.started`, `tool.completed`, `explanation.ready`, `proposal.ready`, `approval.recorded`, `action.granted`, `action.dispatched`, `action.confirmed`); the replay handle is minted by a worker role connection under the alpha tenant; the final step reads `(action_id, payload_sha256)` from `app.execution_grant` (superuser on `ops_test`) and from `incident.action_key` (role `incident` on `incident_test`), asserts `scripts.skeleton.orphan_keys(keys, grants)` does not contain this run's action id, and adds `keys=consistent` to the evidence lines (the exit code of `skeleton.py keys` is not used: another live test plants an orphan on purpose). The skeleton processes inherit `PROFILE=test` and the test database names from the fixture (Task 2).

- [ ] **Step 4: Run the whole live suite and the gate**

Run: `uv run ruff format mcp-read/src mcp-write/src tests/e2e && uv run ruff check --fix mcp-read/src mcp-write/src tests/e2e`, then `OPS_LIVE=1 PYTHONUTF8=1 uv run python -m pytest tests/e2e tests/plan_b/live -q` → PASS (every module; the Plan B live tests rewrite `reports/bootstrap/*.txt` with identical content — `git status` must stay clean of them). Then `PYTHONUTF8=1 uv run python scripts/check.py` → GREEN with no residue.

- [ ] **Step 5: Commit**

```bash
git add mcp-read/src mcp-write/src tests/plan_d/test_mcp_write.py tests/e2e/test_mcp_read_live.py tests/e2e/test_mcp_write_live.py tests/e2e/test_r105_walking_skeleton.py reports/skeleton/r105-walking-skeleton.txt
git commit -m "feat(mcp): mcp-read and mcp-write run as mcp_read and mcp_exec through the definer functions; R105 re-run (T09)"
```

---

### Task 8: T10 — the hardened destination: ownership and grants, abort, permanent rejection, 403, the fault factory, the detective check

**Files:**
- Modify: `core/src/ops_core/tokens.py` (`WrongAudience`), `incident-sim/src/ops_incident_sim/app.py`, `incident-sim/src/ops_incident_sim/keys.py`, `tests/plan_d/test_incident_sim.py` (the `FakeStore` gains first-writer-wins `abort`/`reject`; the hash-mismatch and the `"[1]"` payload cases become 200 with a `REJECTED` tombstone and no commit), `tests/plan_d/test_tokens.py` (one new case), `tests/e2e/test_incident_sim_live.py`, `tests/e2e/test_r105_walking_skeleton.py` (`(403, 403)` at the destination), `docs/runbooks/walking-skeleton.md` (the abort route, faults, `keys`)
- Create: `core/src/ops_core/testing/__init__.py`, `core/src/ops_core/testing/faults.py`, `migrations/incident/versions/0002_destination_hardening.py`, `tests/plan_e/test_tokens_audience.py`, `tests/plan_e/test_faults.py`, `tests/plan_e/test_incident_sim_t10.py`

**Interfaces:**
- Produces: `ops_core.tokens.WrongAudience(TokenRejected)` raised for an `aud` or `azp` mismatch once signature, issuer and expiry passed.
- Produces: `ops_core.testing.faults.FaultKind` (`StrEnum`: `REJECT_NEXT = "reject_next"`, `DROP_BEFORE_COMMIT = "drop_before_commit"`, `LOSE_AFTER_COMMIT = "lose_after_commit"`), `FaultsDisabled(RuntimeError)`, `Faults(profile: Profile)` with `arm(kind, count=1)`, `take(kind) -> bool`, `armed() -> dict[str, int]`.
- Produces: `ops_incident_sim.keys.abort(conn, *, action_id, payload_sha256, reason) -> KeyRow`, `keys.reject(conn, *, action_id, payload_sha256, reason) -> KeyRow`, `keys.REJECTION_REASONS`; `Store` protocol gains `abort` and `reject`; `create_app(verifier, *, store=None, connect=None, profile=Profile.DEV, faults=None)`; routes `POST /internal/actions/{action_id}/abort` (body `{"payload_sha256", "reason"}`, reason ∈ `cancelled_before_send | expired | deadline`) and, under `PROFILE=test` only, `POST /internal/faults/{kind}` (body `{"count": n}`, 200 `{"armed": {...}}`).
- Produces: database role `incident_owner` owning schema `incident`; role `incident` with `USAGE` on the schema and the sequence and `SELECT, INSERT` on both tables; `CHECK` constraints on `action_key`.

- [ ] **Step 1: Write the failing unit tests**

Create `tests/plan_e/test_tokens_audience.py`:

```python
"""A token whose signature, issuer and expiry pass but whose audience or azp is another server's is WrongAudience
(a TokenRejected subclass): every existing 401 handler keeps working, and incident-sim can answer 403 (T10 DoD 2)."""

import pytest
from ops_core.tokens import TokenRejected, TokenVerifier, WrongAudience

from tests.plan_d.test_tokens import ISSUER, JWK1, PEM2, mint  # Plan D's synthetic key pair and token minter


@pytest.fixture
def verifier() -> TokenVerifier:
    v = TokenVerifier(issuer=ISSUER, audience="incident-sim", allowed_azp=frozenset({"ops-mcp-write"}), jwks_url="unused")
    v.install_keys({"keys": [JWK1]})
    return v


def test_wrong_audience_and_wrong_azp_are_their_own_refusal(verifier: TokenVerifier) -> None:
    assert verifier.verify(mint(aud=["incident-sim"], azp="ops-mcp-write")).azp == "ops-mcp-write"
    for aud, azp in (("ops-api", "ops-mcp-write"), ("incident-sim", "ops-worker")):
        with pytest.raises(WrongAudience) as exc:
            verifier.verify(mint(aud=[aud], azp=azp))
        assert isinstance(exc.value, TokenRejected)


def test_a_bad_signature_is_not_wrong_audience(verifier: TokenVerifier) -> None:
    with pytest.raises(TokenRejected) as exc:
        verifier.verify(mint(PEM2, kid="k1", aud=["incident-sim"], azp="ops-mcp-write"))  # k2's key under k1's kid
    assert not isinstance(exc.value, WrongAudience)
```

Create `tests/plan_e/test_faults.py`:

```python
"""The fault factory refuses to exist outside the test profile (R098) and consumes one fault per take."""

import pytest
from ops_core.settings import Profile
from ops_core.testing.faults import FaultKind, Faults, FaultsDisabled


@pytest.mark.parametrize("profile", [Profile.DEV, Profile.DEMO])
def test_refuses_outside_the_test_profile(profile: Profile) -> None:
    with pytest.raises(FaultsDisabled):
        Faults(profile)


def test_arm_and_take() -> None:
    faults = Faults(Profile.TEST)
    assert faults.take(FaultKind.REJECT_NEXT) is False
    faults.arm(FaultKind.REJECT_NEXT, 2)
    assert faults.armed() == {"reject_next": 2}
    assert faults.take(FaultKind.REJECT_NEXT) and faults.take(FaultKind.REJECT_NEXT) and not faults.take(FaultKind.REJECT_NEXT)
    with pytest.raises(ValueError):
        faults.arm(FaultKind.LOSE_AFTER_COMMIT, 0)
```

Create `tests/plan_e/test_incident_sim_t10.py` (the Plan D fake store extended; the `row`, `StubVerifier`, `body_for`, `post` helpers imported from `tests/plan_d/test_incident_sim.py`):

```python
"""incident-sim after T10 without a database: abort tombstones, permanent REJECTED keys for a hash mismatch or a
non-object payload, POST and abort onto any tombstone returning that tombstone, 403 for the wrong audience, and the
fault hooks present only under the test profile (SA:259-269, R096, R098).
"""

from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from ops_core.canonical import sha256_hex
from ops_core.settings import Profile
from ops_core.testing.faults import Faults
from ops_core.tokens import Principal, TokenRejected, WrongAudience
from ops_incident_sim import keys
from ops_incident_sim.app import create_app

from tests.plan_d.test_incident_sim import ACTION, PAYLOAD, SHA, FakeStore as PlanDStore, body_for, row


class FakeStore(PlanDStore):
    async def abort(self, *, action_id: UUID, payload_sha256: str, reason: str) -> keys.KeyRow:
        if action_id not in self.rows:
            self.rows[action_id] = row(action_id=action_id, payload_sha256=payload_sha256, state="ABORTED", incident_id=None, receipt_id=None, reason=reason)
        return self.rows[action_id]

    async def reject(self, *, action_id: UUID, payload_sha256: str, reason: str) -> keys.KeyRow:
        if action_id not in self.rows:
            self.rows[action_id] = row(action_id=action_id, payload_sha256=payload_sha256, state="REJECTED", incident_id=None, receipt_id=None, reason=reason)
        return self.rows[action_id]


class Verifier:
    ready = True

    async def load_keys(self) -> None:
        return None

    async def verify_async(self, token: str) -> Principal:
        if token == "wrong-audience":
            raise WrongAudience("another server's token")
        if token != "good":
            raise TokenRejected("nope")
        return Principal(subject="sa", azp="ops-mcp-write", audiences=("incident-sim",), expires_at=2**31, claims={})


def make(profile: Profile = Profile.DEV):
    store = FakeStore()
    faults = Faults(profile) if profile is Profile.TEST else None
    app = create_app(Verifier(), store=store, profile=profile, faults=faults)
    return TestClient(app), store


def auth(token: str = "good") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_wrong_audience_is_403_without_an_action_id() -> None:
    with make()[0] as c:
        r = c.post("/internal/incidents", json=body_for(PAYLOAD), headers=auth("wrong-audience"))
        assert r.status_code == 403 and r.json()["code"] == "FORBIDDEN" and str(ACTION) not in r.text
        assert c.post("/internal/incidents", json=body_for(PAYLOAD), headers=auth("bad")).status_code == 401


def test_abort_then_post_returns_the_tombstone_whatever_the_hash() -> None:
    c, store = make()
    with c:
        r = c.post(f"/internal/actions/{ACTION}/abort", json={"payload_sha256": SHA, "reason": "expired"}, headers=auth())
        assert r.status_code == 200 and r.json()["state"] == "ABORTED"
        assert r.json()["tombstone"] == {"action_id": str(ACTION), "state": "ABORTED", "payload_sha256": SHA, "reason": "expired", "decided_at": r.json()["tombstone"]["decided_at"]}
        late = c.post("/internal/incidents", json=body_for(PAYLOAD), headers=auth())
        assert late.status_code == 200 and late.json()["state"] == "ABORTED" and "receipt" not in late.json()
        other_hash = c.post("/internal/incidents", json=body_for({"x": 1}, action=ACTION), headers=auth())
        assert other_hash.status_code == 200 and other_hash.json()["state"] == "ABORTED"  # SA:267: never CONFLICT
        again = c.post(f"/internal/actions/{ACTION}/abort", json={"payload_sha256": "0" * 64, "reason": "deadline"}, headers=auth())
        assert again.json()["tombstone"]["reason"] == "expired"  # the first tombstone stands
        assert store.rows[ACTION].state == "ABORTED" and not any(r.state == "COMMITTED" for r in store.rows.values())


def test_abort_after_commit_returns_the_receipt() -> None:
    c, _ = make()
    with c:
        first = c.post("/internal/incidents", json=body_for(PAYLOAD), headers=auth()).json()
        r = c.post(f"/internal/actions/{ACTION}/abort", json={"payload_sha256": SHA, "reason": "cancelled_before_send"}, headers=auth())
        assert r.status_code == 200 and r.json()["state"] == "COMMITTED" and r.json()["receipt"] == first["receipt"]
        conflict = c.post(f"/internal/actions/{ACTION}/abort", json={"payload_sha256": "0" * 64, "reason": "expired"}, headers=auth())
        assert conflict.status_code == 409 and conflict.json()["state"] == "CONFLICT"


def test_bad_reason_is_422_and_no_key() -> None:
    c, store = make()
    with c:
        r = c.post(f"/internal/actions/{ACTION}/abort", json={"payload_sha256": SHA, "reason": "because"}, headers=auth())
        assert r.status_code == 422 and store.rows == {}


def test_hash_mismatch_and_non_object_payload_write_permanent_rejections() -> None:
    c, store = make()
    with c:
        r = c.post("/internal/incidents", json=body_for(PAYLOAD, sha="0" * 64), headers=auth())
        assert r.status_code == 200 and r.json()["state"] == "REJECTED" and r.json()["tombstone"]["reason"] == "hash_mismatch"
        assert store.rows[ACTION].state == "REJECTED" and store.commits == []
        good = c.post("/internal/incidents", json=body_for(PAYLOAD), headers=auth())
        assert good.json()["state"] == "REJECTED"  # permanent: the right bytes later still get the tombstone
        other = uuid4()
        body = body_for(PAYLOAD, action=other)
        body["payload_canonical"] = "[1, 2]"
        body["payload_sha256"] = sha256_hex(b"[1, 2]")
        r = c.post("/internal/incidents", json=body, headers=auth())
        assert r.status_code == 200 and r.json()["tombstone"]["reason"] == "invalid_payload"
        abort = c.post(f"/internal/actions/{other}/abort", json={"payload_sha256": "0" * 64, "reason": "expired"}, headers=auth())
        assert abort.json()["state"] == "REJECTED"  # abort onto REJECTED returns the REJECTED tombstone (SA:267)
        assert c.post("/internal/incidents", content=b"not json", headers=auth()).status_code == 422  # no envelope, no key


def test_fault_hooks_exist_only_in_the_test_profile() -> None:
    with make(Profile.DEV)[0] as c:
        assert c.post("/internal/faults/reject_next", json={"count": 1}, headers=auth()).status_code == 404
    c, store = make(Profile.TEST)
    with c:
        assert c.post("/internal/faults/reject_next", json={"count": 1}, headers=auth("bad")).status_code == 401
        assert c.post("/internal/faults/nope", json={"count": 1}, headers=auth()).status_code == 422
        assert c.post("/internal/faults/reject_next", json={"count": 1}, headers=auth()).json() == {"armed": {"reject_next": 1}}
        r = c.post("/internal/incidents", json=body_for(PAYLOAD), headers=auth())
        assert r.json()["state"] == "REJECTED" and r.json()["tombstone"]["reason"] == "policy"
        assert c.post("/internal/incidents", json=body_for(PAYLOAD, action=uuid4()), headers=auth()).json()["state"] == "COMMITTED"
        c.post("/internal/faults/drop_before_commit", json={"count": 1}, headers=auth())
        dropped = uuid4()
        assert c.post("/internal/incidents", json=body_for(PAYLOAD, action=dropped), headers=auth()).status_code == 503
        assert dropped not in store.rows
        c.post("/internal/faults/lose_after_commit", json={"count": 1}, headers=auth())
        lost = uuid4()
        assert c.post("/internal/incidents", json=body_for(PAYLOAD, action=lost), headers=auth()).status_code == 503
        assert store.rows[lost].state == "COMMITTED"  # a lookup recovers what the lost response hid
        assert c.get(f"/internal/actions/{lost}", headers=auth()).json()["state"] == "COMMITTED"
```

Run: `uv run python -m pytest tests/plan_e/test_tokens_audience.py tests/plan_e/test_faults.py tests/plan_e/test_incident_sim_t10.py -q` → FAIL (`ImportError: WrongAudience`).

- [ ] **Step 2: `WrongAudience` and the fault factory**

In `core/src/ops_core/tokens.py`, add after `TokenRejected`:

```python
class WrongAudience(TokenRejected):
    """Signature, issuer and expiry passed; the token is simply another server's (aud or azp). Servers that answer
    401 for every TokenRejected keep doing so; incident-sim turns this one into 403 (T10 DoD 2)."""
```

In `verify`, the PyJWT call raises `jwt.InvalidAudienceError` for a wrong `aud`: catch it separately before the generic `jwt.PyJWTError` branch and raise `WrongAudience("token is for another audience")`; the `azp` check raises `WrongAudience("token was issued to a client this server does not accept")`. Everything else is unchanged. Add one case to `tests/plan_d/test_tokens.py`'s refusal parametrisation if it asserts exact exception types (it asserts `TokenRejected`, which still holds).

Create `core/src/ops_core/testing/__init__.py` (empty) and `core/src/ops_core/testing/faults.py`:

```python
"""Test-only fault injection (R098; BUILD_SPEC §14 "Fault hooks are test-harness-only"): a counter per fault kind
that a server consumes on its hot path. Framework-free so every service (incident-sim here, the application
services with T13) mounts its own arming route; the factory refuses to exist outside the test profile, which is what
makes the hooks unreachable in dev and demo (SA:564).
"""

from __future__ import annotations

from enum import StrEnum

from ops_core.settings import Profile


class FaultKind(StrEnum):
    """The three BS:405 faults T10 implements; T13 adds the other six."""

    REJECT_NEXT = "reject_next"  # the next POST writes a permanent REJECTED key (reason policy)
    DROP_BEFORE_COMMIT = "drop_before_commit"  # the next POST answers 503 and writes nothing
    LOSE_AFTER_COMMIT = "lose_after_commit"  # the next POST commits, then the response is lost (503)


class FaultsDisabled(RuntimeError):
    """Constructed outside the test profile: the hooks must not exist there (R098)."""


class Faults:
    """Armed counts per kind; `take` consumes one or answers False when nothing is armed."""

    def __init__(self, profile: Profile) -> None:
        if profile is not Profile.TEST:
            raise FaultsDisabled(f"fault hooks are unavailable in the {profile.value} profile")
        self._armed: dict[FaultKind, int] = {}

    def arm(self, kind: FaultKind, count: int = 1) -> None:
        """Arm `count` occurrences of `kind` (adds to what is armed)."""
        if count < 1:
            raise ValueError("count must be at least 1")
        self._armed[kind] = self._armed.get(kind, 0) + count

    def take(self, kind: FaultKind) -> bool:
        """Consume one armed occurrence; False when none is armed."""
        left = self._armed.get(kind, 0)
        if left <= 0:
            return False
        if left == 1:
            del self._armed[kind]
        else:
            self._armed[kind] = left - 1
        return True

    def armed(self) -> dict[str, int]:
        """What is still armed, by kind name."""
        return {kind.value: count for kind, count in self._armed.items()}
```

- [ ] **Step 3: Revision 0002 of `migrations/incident`**

Create `migrations/incident/versions/0002_destination_hardening.py`:

```python
"""Ownership and grants for the destination (T10; SA:265, BS:489, R096): `incident_owner` owns the schema, the
runtime role `incident` can INSERT and SELECT and nothing else, so keys can never be deleted or rewritten by the
service; plus two CHECKs that keep receipts and tombstones honest.

Revision ID: 0002_destination_hardening
Revises: 0001_walking_skeleton

Runs as the Compose superuser against database `incident`; scripts/skeleton.py ensure_roles has created
`incident_owner` (NOLOGIN) and narrowed CONNECT to `incident`.
"""

from alembic import op

revision = "0002_destination_hardening"
down_revision = "0001_walking_skeleton"
branch_labels = None
depends_on = None

UPGRADE = (
    "ALTER SCHEMA incident OWNER TO incident_owner",
    "ALTER TABLE incident.action_key OWNER TO incident_owner",
    "ALTER TABLE incident.incidents OWNER TO incident_owner",
    "ALTER SEQUENCE incident.incident_seq OWNER TO incident_owner",
    "REVOKE ALL ON ALL TABLES IN SCHEMA incident FROM incident",
    "REVOKE ALL ON ALL SEQUENCES IN SCHEMA incident FROM incident",
    "GRANT USAGE ON SCHEMA incident TO incident",
    "GRANT SELECT, INSERT ON incident.action_key, incident.incidents TO incident",
    "GRANT USAGE ON SEQUENCE incident.incident_seq TO incident",
    # A receipt exists iff the key committed; a tombstone never carries one.
    "ALTER TABLE incident.action_key"
    " ADD CONSTRAINT action_key_receipt_iff_committed CHECK ((state = 'COMMITTED') = (receipt_id IS NOT NULL)),"
    " ADD CONSTRAINT action_key_incident_iff_committed CHECK ((state = 'COMMITTED') = (incident_id IS NOT NULL))",
)

DOWNGRADE = (
    "ALTER TABLE incident.action_key DROP CONSTRAINT action_key_receipt_iff_committed,"
    " DROP CONSTRAINT action_key_incident_iff_committed",
    "ALTER SCHEMA incident OWNER TO incident",
    "ALTER TABLE incident.action_key OWNER TO incident",
    "ALTER TABLE incident.incidents OWNER TO incident",
    "ALTER SEQUENCE incident.incident_seq OWNER TO incident",
)


def upgrade() -> None:
    for statement in UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE:
        op.execute(statement)
```

- [ ] **Step 4: `keys.py` — abort and reject**

In `incident-sim/src/ops_incident_sim/keys.py`, replace the module docstring's TODO line with "`abort` and `reject` write the two tombstone states the same way (first writer wins); nothing here can UPDATE or DELETE a row, and the role cannot either (revision 0002)." Add:

```python
REJECTION_REASONS: Final = ("invalid_payload", "hash_mismatch", "policy")
ABORT_REASONS: Final = ("cancelled_before_send", "expired", "deadline")


async def _tombstone(conn: Conn, *, action_id: UUID, payload_sha256: str, state: str, reason: str) -> KeyRow:
    """INSERT … ON CONFLICT DO NOTHING then read: an existing key of any state stands (SA:263, SA:267)."""
    cur = await conn.execute(
        "INSERT INTO incident.action_key (action_id, payload_sha256, state, reason) VALUES (%s, %s, %s, %s)"
        " ON CONFLICT (action_id) DO NOTHING RETURNING *",
        (action_id, payload_sha256, state, reason),
    )
    inserted = await cur.fetchone()
    if inserted is not None:
        return _row(inserted)
    existing = await lookup(conn, action_id)
    if existing is None:
        raise RuntimeError("action_key row vanished after a conflict; rows are never deleted (SA:265)")
    return existing


async def abort(conn: Conn, *, action_id: UUID, payload_sha256: str, reason: str) -> KeyRow:
    """The abort tombstone carries the grant's hash (SA:266); a committed key answers with its receipt instead."""
    if reason not in ABORT_REASONS:
        raise ValueError("abort reason")
    return await _tombstone(conn, action_id=action_id, payload_sha256=payload_sha256, state="ABORTED", reason=reason)


async def reject(conn: Conn, *, action_id: UUID, payload_sha256: str, reason: str) -> KeyRow:
    """A permanent rejection (SA:261): a lost response to a rejected POST is recoverable by lookup."""
    if reason not in REJECTION_REASONS:
        raise ValueError("rejection reason")
    return await _tombstone(conn, action_id=action_id, payload_sha256=payload_sha256, state="REJECTED", reason=reason)
```

(`from typing import Any, Final`.) `commit` is unchanged.

- [ ] **Step 5: `app.py` — profile, abort, rejection, 403, faults**

In `incident-sim/src/ops_incident_sim/app.py`:
- `Store` protocol gains `abort(self, *, action_id, payload_sha256, reason) -> keys.KeyRow` and `reject(...)`; `DbStore` implements both through `self.session.unit()`; `DbStore.ping()` wraps `session.ping()`; `ready` uses it.
- `class AbortRequest(BaseModel)`: `model_config = ConfigDict(strict=True, frozen=True, extra="forbid")`, `payload_sha256: Sha256`, `reason: Literal["cancelled_before_send", "expired", "deadline"]`.
- `class FaultRequest(BaseModel)`: strict, `count: int = Field(ge=1, le=100)`.
- `create_app(verifier, *, store=None, connect=None, profile: Profile = Profile.DEV, faults: Faults | None = None)`: when `profile is Profile.TEST` and `faults is None`, `faults = Faults(profile)`; when `profile is not Profile.TEST`, `faults` must be `None` (raise `ValueError` otherwise). The lifespan, for a `DbStore`, calls `persistence.assert_clock_profile(...)`? **No**: incident-sim's database has no `app` schema; it has nothing to assert. Skip it here and say so in a comment.
- `caller` dependency: `except WrongAudience as exc: raise WrongService from exc` before the `TokenRejected` branch; a `WrongService` handler returns `safe_error(403, ErrorCode.FORBIDDEN, "token is not for this service")`.
- `post_incident`: after the envelope parses, the two validation failures become rejections:

```python
        try:
            payload = parse_json_strict(body.payload_canonical)
        except (CanonicalizationError, ValueError):
            payload = None
        if not isinstance(payload, dict) or not payload:
            row = await st.reject(action_id=body.action_id, payload_sha256=body.payload_sha256, reason="invalid_payload")
            return JSONResponse(status_code=200, content=keys.document(row, presented_sha256=body.payload_sha256)[1])
        if sha256_hex(body.payload_canonical.encode("utf-8")) != body.payload_sha256:
            row = await st.reject(action_id=body.action_id, payload_sha256=body.payload_sha256, reason="hash_mismatch")
            return JSONResponse(status_code=200, content=keys.document(row, presented_sha256=body.payload_sha256)[1])
        if faults is not None and faults.take(FaultKind.REJECT_NEXT):
            row = await st.reject(action_id=body.action_id, payload_sha256=body.payload_sha256, reason="policy")
            return JSONResponse(status_code=200, content=keys.document(row, presented_sha256=body.payload_sha256)[1])
        if faults is not None and faults.take(FaultKind.DROP_BEFORE_COMMIT):
            return safe_error(503, ErrorCode.UNAVAILABLE, "destination unavailable (fault)")
        row = await st.commit(body.action_id, body.payload_sha256, payload)  # inside the existing psycopg.Error guard
        if faults is not None and faults.take(FaultKind.LOSE_AFTER_COMMIT):
            return safe_error(503, ErrorCode.UNAVAILABLE, "response lost after commit (fault)")
```

  (`keys.document` keeps turning a `COMMITTED` row with another hash into 409 `CONFLICT` and any tombstone into its 200 document; a rejection's `document` is the tombstone, so a replayed POST with the right bytes onto a `REJECTED` key answers the tombstone — review focus 4.)
- `abort` route:

```python
    @app.post("/internal/actions/{action_id}/abort")
    async def abort_action(action_id: UUID, request: Request, _: Annotated[Principal, Depends(caller)]) -> Response:
        raw = await request.body()
        try:
            body = AbortRequest.model_validate_json(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValidationError, ValueError):
            return safe_error(422, ErrorCode.INVALID_INPUT, "body is not a well-formed abort request")
        st: Store = request.app.state.store
        try:
            row = await st.abort(action_id=action_id, payload_sha256=body.payload_sha256, reason=body.reason)
        except psycopg.Error:
            return safe_error(503, ErrorCode.UNAVAILABLE, "destination database unavailable")
        status, doc = keys.document(row, presented_sha256=body.payload_sha256)
        return JSONResponse(status_code=status, content=doc)
```

- faults route, registered only when `faults is not None`:

```python
        @app.post("/internal/faults/{kind}")
        async def arm_fault(kind: FaultKind, request: Request, _: Annotated[Principal, Depends(caller)]) -> Response:
            try:
                body = FaultRequest.model_validate_json((await request.body()).decode("utf-8"))
            except (UnicodeDecodeError, ValidationError, ValueError):
                return safe_error(422, ErrorCode.INVALID_INPUT, "body is not a well-formed fault request")
            faults.arm(kind, body.count)
            return JSONResponse({"armed": faults.armed()})
```

  (A `kind` outside the enum fails FastAPI's path validation → the generic 422 handler.)
- `production_app()` passes `profile=settings.profile()` (and therefore faults under test).
- Update `tests/plan_d/test_incident_sim.py`: its `FakeStore` gains first-writer-wins `abort` and `reject` (the same bodies as the T10 subclass above; move them there and let the subclass inherit); `test_presented_hash_must_match_the_received_bytes` expects 200 with `state == "REJECTED"` and `tombstone.reason == "hash_mismatch"` for both of its cases and keeps `store.commits == []`; in `test_malformed_bodies_are_422` the `"payload_canonical": "[1]"` body (a well-formed envelope with a non-object payload) moves to a new assertion expecting 200 `REJECTED` with reason `invalid_payload`, and the remaining bodies stay 422.

- [ ] **Step 6: Live tests for the destination (R010, R047, R096, R098)**

Replace `tests/e2e/test_incident_sim_live.py` with tests on `incident_conn` (role `incident`, database `incident_test`):

```python
"""The destination's key table as role `incident` on the per-session database (OPS_LIVE=1): first-writer-wins under
real concurrency (R047), POST-vs-abort races and tombstone permanence (R096), the role's inability to delete or
rewrite a key (R096, SA:265), the CHECKs, and the independence of the destination store (R010: the application
database is dropped and recreated every session while incident_test keeps what this test wrote until its own reset).
"""

import asyncio
from collections.abc import Awaitable
from uuid import uuid4

import psycopg
import pytest
from ops_core import persistence, settings
from ops_core.canonical import canonical_sha256
from ops_incident_sim import keys

pytestmark = pytest.mark.asyncio


async def test_commit_replay_conflict_and_isolation(incident_conn: persistence.Conn) -> None:
    action = uuid4()
    payload = {"title": "live", "n": 1}
    first = await keys.commit(incident_conn, action_id=action, payload_sha256=canonical_sha256(payload), payload=payload)
    again = await keys.commit(incident_conn, action_id=action, payload_sha256=canonical_sha256(payload), payload=payload)
    assert first == again and first.incident_id.startswith("INC-") and first.state == "COMMITTED"
    other = await keys.commit(incident_conn, action_id=action, payload_sha256="0" * 64, payload={"x": 1})
    assert other == first and keys.document(other, presented_sha256="0" * 64)[0] == 409
    # The real boundary: the destination's credentials cannot even open the application database (ensure_roles
    # narrowed CONNECT); inside its own database there is no `app` schema to see.
    creds = settings.incident_postgres()
    foreign = settings.Postgres(creds.host, creds.port, creds.user, settings.superuser_postgres().dbname, creds.password)
    with pytest.raises(psycopg.OperationalError, match="permission denied for database"):
        await psycopg.AsyncConnection.connect(foreign.conninfo())


async def test_r096_keys_are_permanent_for_the_runtime_role(incident_conn: persistence.Conn) -> None:
    action = uuid4()
    await keys.abort(incident_conn, action_id=action, payload_sha256="a" * 64, reason="expired")
    for statement in (
        "DELETE FROM incident.action_key WHERE action_id = %s",
        "UPDATE incident.action_key SET state = 'COMMITTED' WHERE action_id = %s",
        "UPDATE incident.action_key SET reason = 'x' WHERE action_id = %s",
    ):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            await incident_conn.execute(statement, (action,))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        await incident_conn.execute("TRUNCATE incident.action_key")
    assert (await keys.lookup(incident_conn, action)).state == "ABORTED"
    # A tombstone never carries a receipt or an incident id, even if someone tries.
    with pytest.raises(psycopg.errors.CheckViolation):
        await incident_conn.execute(
            "INSERT INTO incident.action_key (action_id, payload_sha256, state, incident_id) VALUES (%s, %s, 'REJECTED', 'INC-1')",
            (uuid4(), "b" * 64),
        )
    owner = await (await incident_conn.execute("SELECT tableowner FROM pg_tables WHERE schemaname = 'incident' AND tablename = 'action_key'")).fetchone()
    assert owner["tableowner"] == "incident_owner"


async def in_unit(conn: persistence.Conn, call: Awaitable[keys.KeyRow]) -> keys.KeyRow:
    """Key and incident commit together, as the service does it (BUILD_SPEC §10), so the race is the real one."""
    async with conn.transaction():
        return await call


async def test_r047_r096_races_yield_one_terminal_state(incident_conn: persistence.Conn) -> None:
    """Twenty create-vs-abort races and twenty create-vs-create races on two connections (spike §6)."""
    second = await persistence.connect(settings.incident_postgres())
    try:
        for i in range(20):
            action, payload = uuid4(), {"i": i}
            sha = canonical_sha256(payload)
            created, aborted = await asyncio.gather(
                in_unit(incident_conn, keys.commit(incident_conn, action_id=action, payload_sha256=sha, payload=payload)),
                in_unit(second, keys.abort(second, action_id=action, payload_sha256=sha, reason="deadline")),
            )
            final = await keys.lookup(incident_conn, action)
            assert created == aborted == final and final.state in ("COMMITTED", "ABORTED")
            n = await (await incident_conn.execute("SELECT count(*) AS n FROM incident.incidents WHERE action_id = %s", (action,))).fetchone()
            assert n["n"] == (1 if final.state == "COMMITTED" else 0)
        for i in range(20):
            action, payload = uuid4(), {"j": i}
            sha = canonical_sha256(payload)
            a, b = await asyncio.gather(
                in_unit(incident_conn, keys.commit(incident_conn, action_id=action, payload_sha256=sha, payload=payload)),
                in_unit(second, keys.commit(second, action_id=action, payload_sha256=sha, payload=payload)),
            )
            assert a == b and a.state == "COMMITTED"
    finally:
        await second.close()


async def test_r010_destination_rows_outlive_the_application_store(incident_conn: persistence.Conn, app_conn: persistence.Conn) -> None:
    """Per session, ops_test is dropped and recreated (conftest) while incident_test is only reset by its own fixture;
    inside one session the two stores share nothing: a key exists with no grant anywhere in the application store."""
    action = uuid4()
    await keys.commit(incident_conn, action_id=action, payload_sha256="c" * 64, payload={"r010": True})
    grants = await (await app_conn.execute("SELECT count(*) AS n FROM app.execution_grant WHERE action_id = %s", (action,))).fetchone()
    assert grants["n"] == 0 and (await keys.lookup(incident_conn, action)).state == "COMMITTED"
    from scripts.skeleton import keys as detective

    assert detective() == 1  # the orphan this test planted is reported, exit 1
```

This test plants an orphan on purpose, so `keys()` exits 1 for the rest of the session; the R105 test therefore checks its own action id against `scripts.skeleton.orphan_keys` over rows it reads itself (Task 7), never against the exit code.

R098's "hook routes 404 in default and demo profiles" is the unit test above (`make(Profile.DEV)`); the live suite runs under `PROFILE=test`, where the R105 skeleton's incident-sim has the hooks and the R105 test does not use them.

- [ ] **Step 7: Runbook, gates, commit**

In `docs/runbooks/walking-skeleton.md`, document the abort route body, the three faults and the arming route (test profile only), and `skeleton.py keys`. In `tests/e2e/test_r105_walking_skeleton.py` the destination's answers to the persona and worker tokens become `(403, 403)` (ruling 12); the `action_id not in …text` assertions stay.

Run: `uv run ruff format core/src incident-sim/src migrations/incident tests && uv run ruff check --fix core/src incident-sim/src migrations/incident tests && uv run python -m pytest tests/plan_e tests/plan_d/test_incident_sim.py tests/plan_d/test_tokens.py -q` → PASS; `OPS_LIVE=1 PYTHONUTF8=1 uv run python -m pytest tests/e2e -q` → PASS; `PYTHONUTF8=1 uv run python scripts/check.py` → GREEN (no residue remains).

```bash
git add core/src/ops_core/tokens.py core/src/ops_core/testing migrations/incident incident-sim/src tests/plan_e tests/plan_d/test_incident_sim.py tests/plan_d/test_tokens.py tests/e2e/test_incident_sim_live.py tests/e2e/test_r105_walking_skeleton.py docs/runbooks/walking-skeleton.md
git commit -m "feat(incident-sim): executor-only key table, abort and permanent rejection, 403 for foreign tokens, test-only faults, detective check (T10)"
```

---
### Task 9: `check.py --profile`, documentation, handoff records, errata

**Files:**
- Modify: `scripts/check.py` (`--profile dev|test`), `README.md` (status line), `STATUS.md`, `SESSION_STATE.md` (Plan E executed; open items; errata), `handoff/tasks.json` (T09, T10 → `DONE` with review notes), `handoff/BUILD_BACKLOG.md` (T09, T10 checked with notes), `handoff/acceptance-matrix.json` (fourteen rows), `docs/runbooks/dev-topology.md` (roles paragraph), `docs/runbooks/walking-skeleton.md` (final pass), `core/src/ops_core/states.py:11-12` (the R082 TODO becomes a pointer to `transition_run`), `tests/plan_b/test_evidence.py` (nothing: `reports/skeleton/` is already scanned)
- Create: `tests/plan_e/test_check_cli.py`

**Interfaces:**
- Produces: `scripts/check.py [--profile dev|test]`; `test` exports `OPS_LIVE=1` for the pytest step so the live suite runs against the per-session databases (ruling 8); `check_profile(argv) -> Profile` (pure).

- [ ] **Step 1: `check.py --profile`**

Create `tests/plan_e/test_check_cli.py`:

```python
"""`check.py --profile test` is this repository's reading of SA:529: the same four steps, with the live suite enabled
(the e2e fixture applies the testclock branch to the per-session databases). Dev stays database-free."""

import sys
from pathlib import Path

import pytest
from ops_core.settings import Profile

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.check import check_profile, environment_for


def test_profile_argument() -> None:
    assert check_profile([]) is Profile.DEV
    assert check_profile(["--profile", "test"]) is Profile.TEST
    with pytest.raises(SystemExit):
        check_profile(["--profile", "prod"])


def test_test_profile_turns_the_live_suite_on() -> None:
    env = environment_for(Profile.TEST, {"PATH": "x"})
    assert env["OPS_LIVE"] == "1" and env["PROFILE"] == "test" and env["PATH"] == "x"
    assert "OPS_LIVE" not in environment_for(Profile.DEV, {"PATH": "x"})
```

In `scripts/check.py` add `import argparse` and `import os`; `Profile` is imported under `if TYPE_CHECKING:` for the annotations (the module already has `from __future__ import annotations`) and lazily inside the two functions, so the `members_importable` guard still gives its friendly message on an unsynced clone:

```python
def check_profile(argv: list[str]) -> Profile:
    """`--profile dev` (default, database-free) or `--profile test` (the live suite against the test databases)."""
    from ops_core.settings import Profile

    parser = argparse.ArgumentParser(description="ruff, ruff format, mypy, pytest")
    parser.add_argument("--profile", choices=[p.value for p in Profile if p is not Profile.DEMO], default=Profile.DEV.value)
    return Profile(parser.parse_args(argv).profile)


def environment_for(profile: Profile, base: dict[str, str]) -> dict[str, str]:
    """The child environment: the test profile switches the live gate on and names itself (SA:529)."""
    from ops_core.settings import Profile

    env = dict(base)
    if profile is Profile.TEST:
        env["OPS_LIVE"] = "1"
        env["PROFILE"] = profile.value
    return env
```

`main()` takes `argv: list[str] | None = None`, calls `members_importable()` first (the lazy `Profile` import must not be the thing that fails on an unsynced clone), then resolves the profile and passes `env=environment_for(profile, os.environ)` to `subprocess.run` for every step (`run(cmd, env)`). Update the module docstring's usage block with `--profile test` and the note that it needs the dev stack up.

Run: `uv run python -m pytest tests/plan_e/test_check_cli.py -q` → PASS; `PYTHONUTF8=1 uv run python scripts/check.py` → GREEN; `PYTHONUTF8=1 uv run python scripts/check.py --profile test` → GREEN with the live suite included (record both counts in the report).

- [ ] **Step 2: Handoff records**

`handoff/tasks.json`: T09 and T10 `status: "DONE"`; each `review_notes` gains one entry starting `Plan E (branch plan-e): done in <first>..<last>.` summarising what shipped and naming the deferrals (T09: the eleven functions, R122 → T20, `migrator` login → T30, expiry/asset guard → T21, fence → T13; T10: abort client and `abort_incident` tool → T47/T22, six faults → T13, schedule for the detective check → T32) and the evidence modules. `handoff/BUILD_BACKLOG.md`: tick T09 and T10 with the same note.

`handoff/acceptance-matrix.json` (rows live under `requirements`; the fields are `implementation_status`, `evidence_status`, `evidence_paths`, `note`): R006, R007, R008, R009, R084, R106, R124, R126, R128, R010, R047, R096, R098 → `"implementation_status": "IMPLEMENTED_LOCALLY_VERIFIED"`, `"evidence_status": "RECORDED_LOCALLY_LIVE"`, `"evidence_paths"` listing the live test modules from Tasks 2–8; R122 stays `NOT_RUN` with `"note": "deferred to T20: langgraph-checkpoint-postgres is not locked (Plan E ruling 2)"`; R082's note becomes "logged half done in Plan E: transition_run raises OC004 (server log) and the wrapper logs at WARNING". Run `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts` → exit 0.

`core/src/ops_core/states.py:11-12`: replace the TODO with "R082's logged half: the SQL mirror `app.transition_run` (migrations/app/versions/0003) raises `OC004` with the refused row in DETAIL, and `ops_core.persistence.transition_run` logs it at WARNING."

- [ ] **Step 3: Project state and docs**

`SESSION_STATE.md`:
- The "Next task" line: Plan E executed on `plan-e` (`<first>..<last>`); owner inputs pending unchanged; next is Plan F (T11 sessions and membership sync, or T13 leases, whichever the backlog's dependency graph puts first: T11 depends on T09 and T43 — both DONE — so T11).
- A "Plan E executed" paragraph: the 24 rulings in one sentence each is too much; name the file and list the proposed errata (10–19): NULLIF policy text; worker `jobs.available_at` and `app_definer` `runs.updated_at`; the 24th function `resolve_identity`; the signature deviations (`create_run` request/return, `transition_run` detail, `freeze_proposal` bytes and a verified rather than injected `supersedes_run_id`, `record_decision` tenant and reviewer, `append_event` source and its wider reserved-type list); `mark_unknown` worker-only with mcp-write reporting UNKNOWN and the worker dispatching `execute` jobs for EXECUTING runs; `app.current_time()` as a definer function callable by every runtime role; `check.py --profile test` as the live suite; no row lock on `proposals`, `decisions`, `memberships` or `execution_grant` inside the definer functions (a lock needs UPDATE; ruling 23); the `OC001` authority check is reachable only past the EXECUTE ACL; `resolve_invocation` returns `job_type`, `job_id` and `conversation_id` rather than SA:459's `allowed_tools` (ruling 21); `app.transitions` is a table outside AM-20.2 (ruling 10); a CONFLICT on a terminal run is `action.conflict`, not late evidence; the sweeper's `del` without `sel` on `sessions` and `idempotency_request` cannot run a `DELETE … WHERE expires_at < …` (spike §3) — flagged for T11/T12.
- Open items for Plan F parked by the task reviews (from the ledger).

`README.md` status line; `STATUS.md` row for T09/T10. `docs/runbooks/dev-topology.md`: one paragraph on the roles (which process connects as which role, where the secret files are, that the dev database never carries `app.test_clock`). `docs/runbooks/walking-skeleton.md`: final pass (migrate profiles, `keys`, the live suite's databases, the abort route and faults).

- [ ] **Step 4: Evidence and the final gates**

`reports/skeleton/r105-walking-skeleton.txt` was regenerated in Task 7; confirm it carries `keys=consistent` and no token (`tests/plan_b/test_evidence.py` scans it). Run the three gates one last time:

```bash
PYTHONUTF8=1 uv run python scripts/check.py
PYTHONUTF8=1 uv run python scripts/check.py --profile test
uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts
```

All GREEN / exit 0. Record the counts (passed/skipped for both profiles) in the report.

- [ ] **Step 5: Commit**

```bash
git add scripts/check.py tests/plan_e/test_check_cli.py README.md STATUS.md SESSION_STATE.md handoff core/src/ops_core/states.py docs/runbooks
git commit -m "docs: close T09 and T10 — check.py profiles, handoff records, acceptance rows, runbooks (Plan E)"
```

---

## Self-review (run by the plan's author before execution)

1. **Spec coverage.** T09's instructions: Alembic schema incl. `run_state_history`, `action_attempt_state`, `drafts`, `run_directory`, `run_lease`, `jobs` with dedup keys, `execution_grant UNIQUE(run_id)`, `sessions` → Task 2; roles per AM-20.1 incl. `test_harness` via the `testclock` branch → Tasks 1–2; exact grants per AM-20.2 → Tasks 1–2 (matrix) with the four declared departures; definer functions with search_path/REVOKE/GRANT, `session_user` checks, transaction-local `set_config` → Tasks 3–4 (the fourteen with callers; the rest ruled to their owners, ruling 1); `transition_run` restricted to worker and pre-grant targets → Task 3; seed data under `migrator` BYPASSRLS → revision 1's seeds now owned by `migrator` (Task 2); `sweeper_all` on memberships and jobs → Task 2; `action_attempt_state` seq ordering → Task 4 (`_latest_attempt`); `clock_offset` column → Task 2 (`tc_0001`); RLS incl. FORCE → Task 2; `app.current_time()` → Task 2. DoD 1–5 → Tasks 2, 2, 2+4, 2, 3+4. Review notes 1–5 → Tasks 2/3 (run_directory, invocation_context readable by app_definer/sweeper, resolve_identity), 3–4 (attribute + preset test), 2 (test_clock only in the branch; no GUC), 3 (session_user), 5–8 (every service asserts at start). T10: single `action_key` table → unchanged; ON CONFLICT for incidents and abort → Task 8; recomputed hash → unchanged; never-expiring keys → Task 8 (grants); audience auth → unchanged + 403; test-only fault factory → Task 8; DoD 1–2 and review notes 1–4 → Task 8 (READ COMMITTED, GET retained, abort stores the grant hash, POST onto ABORTED/REJECTED returns the tombstone, azp enforced, REJECTED permanent, detective check). Requirement rows: R006–R009, R084, R106, R124, R126, R128, R010, R047, R096, R098 each have a named live or unit test; R122 deferred with a note (ruling 2).
2. **Placeholder scan.** No TBD/TODO-later/"similar to Task N" in the plan text; the `TODO(Txx)` strings inside code blocks are ownership markers required by `docs/CODE_COMMENTS.md`, not plan placeholders.
3. **Type consistency.** `ops_core.privileges` renders grants for `MAIN_GRANTEES` on the main line and for `TEST_ONLY_ROLES` on the branch; `persistence.Session.unit(tenant_id)`, `ping()`, `set_tenant`, `resolve_identity`, `create_run -> (UUID, int)`, `transition_run`, `append_event -> Appended`, `freeze_proposal -> Frozen`, `record_decision -> Decided`, `resolve_invocation -> Invocation(run_id, job_id, job_type, tenant_id, conversation_id, run_state, attempt_state)`, `grant_execution/lookup_action -> Grant`, `mark_sent -> str`, `record_outcome -> ToolOutcome`, `mark_unknown -> RunState`, `claim_job(..., tenant_ids)` are the names Tasks 6–8 call; the SQL signatures in `ops_core.privileges.DEFINER_FUNCTIONS` match the `CREATE FUNCTION` argument lists in revisions 0003/0004 (`record_decision(uuid, uuid, uuid, text, text, text, text)` = tenant, proposal, reviewer, hash, decision, reason, idempotency_key; `transition_run(uuid, text, text, text, integer, jsonb)`; `append_event(uuid, text, jsonb, text)`); `HELPER_FUNCTIONS` gains `_grant_row` in Task 4.
4. **Review Focus.** Each of the five lines names its test: preset tenant (Tasks 3 and 4 live tests), `''` on a reused connection (Task 2 R008), `transition_run` guards (Task 3), replay and races (Tasks 6–8), function-only roles and direct writes (Task 2).

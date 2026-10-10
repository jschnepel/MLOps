# Session state

**Specification:** OPS-BUILD-1.3.6 (`BUILD_SPEC.md` + `SPEC_AMENDMENTS.md`)
**Current milestone:** M00 (baseline, sealed holdout intents and model probe)
**Next task:** Plan F (T11) is executed on branch `plan-f` (`0d1a892..ad3163f`, on top of `plan-e`: the seven tasks, the handoff close-out and the final-review fix wave; the record commit follows). Owner inputs still pending, unchanged: (1) the holdout seal (T03 step 9), then the live probe (T02); (2) merge the stacked PRs #1-#5 in order (plan-b -> main, plan-c -> plan-b, plan-d -> plan-c, plan-e -> plan-d, plan-f -> plan-e; all five are green on CI, T06 closed); (3) T44 step 10: apply `docs/runbooks/ollama-network.md` step A (loopback bind at User scope), attest, decide on the AM-31 errata; (4) decide on the nine proposed contract errata of Plan C and the errata of Plan E and Plan F below; one new input: (5) decide errata 26-34 (the dev database was migrated to 0005 by the owner on 2026-10-09 and the six processes were proved up and down against it). Next is Plan G: T12 (admission router and Idempotency-Key) or T13 (leases); both depend only on T09 and T12 comes first in the backlog's order, so write Plan G for T12 unless the owner prefers T13, and dry-run it on scratch copies before executing.
**Plan A outcome:** executed on branch `plan-a` (a638801..HEAD); `scripts/check.py` GREEN (54 passed, 1 skipped: owner seal). Final whole-branch review: 5 Important findings fixed in the final-review wave; minors deferred: M3 timing restructure (`astream`), M6 mypy member list.
**Repository:** local git repo at `C:\Users\joeys\Desktop\MLOps`, branch `plan-f` (Plan F work on top of `plan-e`, on top of `plan-d`, on top of `plan-c`, on top of `plan-b`, on top of `plan-a`). Remote `github.com/jschnepel/MLOps` (public, MIT) exists; `main` and `plan-a` were pushed on 2026-10-07. `plan-b` to `plan-e` were pushed on 2026-10-08 and `plan-f` on 2026-10-09 (`origin/plan-e` is two docs commits behind local `plan-e`; a `git push origin plan-e` brings it level before the plan-f -> plan-e PR). PRs #1-#5 were opened on 2026-10-09 and are green after the EXE001 fix (first green run https://github.com/jschnepel/MLOps/actions/runs/37962510516; record `reports/ci/t06-first-ci-runs.txt`). Merging them in order is the owner's call.

## Done in the planning session (2026-10-06)

- **Imported the handoff unmodified** (commit "Import Operations Copilot build handoff…"). In place, `scripts/verify_handoff.py --manifest --reference-code` passed with 161 checksums and 19 reference files.
- **Ran the reference recovery CLI** locally: OUTCOME_UNKNOWN → reconcile → one incident.
- **Could not run the 58-test reference suite here.** Collection failed with `ModuleNotFoundError: fastapi`. An isolated `uv run --with …` attempt was blocked by tool permission. This is the first thing T01 must do.
- **Ran an adversarial review** with six independent reviewers plus a lead spot-check: `docs/reviews/handoff-review-2026-10-06.md`.
- **The owner approved "amend + cut".** Wrote:
  - `SPEC_AMENDMENTS.md`;
  - `docs/adr/ADR-0001-*` (top-level directory per service);
  - `docs/adr/ADR-0002-*` (v1 scope cut; single-writer checkpoint profile);
  - the regenerated `handoff/tasks.json` (35 tasks as a graph);
  - `handoff/acceptance-matrix.json` (100 requirements, re-homed, R081–R100 added);
  - `handoff/BUILD_BACKLOG.md`;
  - an MIT `LICENSE`.
- After those edits, `scripts/verify_handoff.py` (structure checks) passes: 35 acyclic tasks, 100 covered requirements. **`--manifest` no longer passes**, because the edited files intentionally differ from the delivered snapshot (BUILD_SPEC §0 anticipates this). The original snapshot is preserved in git commit 1.
- Added `.gitattributes` (LF) so fixture and manifest hashes survive Windows checkouts.

## Second review and 1.2 revision (2026-10-06)

- Ran a second adversarial review with four fresh reviewers: `docs/reviews/plan-review-2026-10-06.md`.
- The owner approved the 1.2 update. Rewrote `SPEC_AMENDMENTS.md` (1.2). The main changes:
  - the MCP server records the attempt protocol through hardened definer functions;
  - fenced writes lock the lease row and use `clock_timestamp()`;
  - `durability="sync"` plus a stored checkpoint ID;
  - one destination `action_key` table;
  - one grant per run, ever;
  - a revocation mechanism;
  - a custom MCP `TokenVerifier`;
  - one worker replica in v1;
  - evaluation statistics;
  - schema alignment assigned to T07.
- Revised ADR-0002 (effort is now 54–108 days, unmeasured).
- Regenerated `handoff/tasks.json`: 40 tasks, renumbered, now including a walking skeleton, dev bootstrap and early CI. Regenerated the acceptance matrix: 117 requirements, all with a test path.
- `scripts/verify_handoff.py` passes the structure checks. A cross-reference check found no unknown task or requirement IDs in the amendments or ADRs.
- **Schemas, examples and fixtures are deliberately still at 1.0.** T07 updates them under contract tests (AM-80, R104).

## Third review and 1.3 revision (2026-10-06)

- Ran round 3 with three fresh reviewers: `docs/reviews/plan-review-r3-2026-10-06.md`. It found 14 items that block starting T01–T08; the rest were LATER items.
- Updated to `SPEC_AMENDMENTS.md` 1.3:
  - AM-00 lists the superseded BUILD_SPEC passages;
  - abort carries the grant hash, and a POST onto an aborted key returns the tombstone;
  - `mark_sent` re-checks cancellation;
  - an audited ABANDONED_UNVERIFIED operator exit from ESCALATED;
  - the conversation-slot rule on revision;
  - the draft `question` field and a completed AM-80;
  - the reference moves in T04, plus a traceability map in T07;
  - checker updates;
  - the holdout is split (T03 seals intents, T41 adds gold labels), with the seal recorded externally;
  - the probe uses ≥30 distinct inputs in an isolated environment;
  - `seed-ids.json` and the Keycloak topology;
  - the walking skeleton's processes are named and it uses real tokens;
  - the venv lives outside the repo;
  - LangGraph resume rules verified against the 1.2.14 source;
  - the asset-guard advisory lock;
  - corrected evaluation power (only ~30-point differences are detectable at n≈25).
- `handoff/tasks.json`: 41 tasks (T41 appended), with LATER items attached as `review_notes`. The acceptance matrix has 123 requirements. The critical path is 15 tasks: T01→T04→T05→T08→T09→T13→T15→T16→T20→T21→T22→T26→T27→T33→T34.
- `verify_handoff.py` structure checks pass, as does a cross-reference check of the amendments and ADRs.
- **Process change:** no more spec-wide review rounds. Review happens per slice, against code and tests.

## Round 5 (spec-wide) and 1.3.2 (2026-10-06)

- Ran a spec-wide review with four fresh reviewers: `docs/reviews/plan-review-r5-2026-10-06.md`. No critical findings, about 35 new.
- The owner chose to **keep hardening** (option a).
- 1.3.2 fixes S1–S9 and H1–H5:
  - **S1:** README, START_HERE and KICKOFF_PROMPT corrected (precedence, no Kubernetes claim, current counts).
  - **S2:** a job-type table.
  - **S3:** the tombstone shape and a permanent REJECTED key.
  - **S4:** asset-guard refusals → BLOCKED_REVIEW.
  - **S5:** `state_version` changes only on transitions.
  - **S6:** a shared reason enum.
  - **S7:** sweeper and operator roles; the operator CLI is no longer on migrator.
  - **S8:** MANIFEST is a frozen 1.0 snapshot.
  - **S9:** localhost-bound ports, model digest check, secrets outside the repo.
  - **H1:** role × table privilege matrix.
  - **H2:** read definer functions for MCP.
  - **H3:** a second incident is blocked (**owner decision**).
  - **H5:** the test clock is a test-profile-only table.
- Other round-5 items are attached as task `review_notes`.
- My 1.3.1 edit had introduced a CR-escape bug. Fixed in `b09b08f`.
- **Ollama network exposure (owner decision):** restrict to loopback plus the Docker/WSL subnet. **Observed now:** `OLLAMA_HOST=0.0.0.0:11434`, with firewall rules allowing `ollama.exe` inbound from any address on Public and Private profiles. T05 writes `docs/runbooks/ollama-network.md` for the owner to apply; the agent changes no system settings.
- Checks: `verify_handoff.py` passes (41 tasks, 126 requirements); cross-references resolve; critical path 15 tasks; no CR bytes.

## Round 6 and 1.3.3 (2026-10-06)

- Round 6 (`docs/reviews/plan-review-r6-2026-10-06.md`): 3 of 14 round-5 items closed, 11 partial; 6 high findings, all in text 1.3.2 added. The owner chose a full prose round that rewrites the privilege matrix and function contracts first.
- **1.3.3:** AM-20 rewritten as exact column-level grants (AM-20.2), a function-contract table with callers, inputs, locks, transitions and events (AM-20.3), job dedup keys (AM-20.4), explicit RLS policies incl. `app_definer` (AM-20.5), and the test clock as an Alembic branch (AM-20.6). Append-only state rows replace UPDATEs on audit tables. `GRANT EXECUTE` goes only to named callers. REJECTED is in every destination sentence. The asset guard refuses any overlapping committed incident regardless of timing unless `supersedes_run_id` names it (**owner decision**). `data/model-pins.json` written by T02 and checked by T19 (R127). R128: every transition and event via a definer function.
- **Mistake found and fixed:** commit `61cc504` was not byte-identical to the delivered package (`.gitignore`). The package zip is now committed as `provenance/handoff-1.0.zip` and `--manifest` will verify against it (T42).
- Task splits: T04 → T04 + T42; T05 → T05 + T43 + T44; T07 → T07 + T45 + T46. 46 tasks, 128 requirements, critical path 15.
- `docs/PROJECT_HISTORY.md` added: the problems found across all rounds and what changed, for portfolio readers.

## Round 8, 1.3.6 and Plan A (2026-10-07)

- Round 8 (`docs/reviews/plan-review-r8-2026-10-07.md`): 8 of 10 round-7 items closed; 1.3.5 had 2 high regressions (`create_run` had no tenant source; `freeze_proposal` had no payload) and 4 medium; **Plan A was not executable** (nine blocking defects, all reproduced by a builder dry-run on scratch copies: the hashes file is a dict, the reference conftest above the new tests, `--all-packages`, ruff on pinned files, a backslash-n in a test, PowerShell BOM+CRLF, in-tree `build/`, a thinning rule that dropped three scenarios).
- **1.3.6:** `create_run(tenant_id, …)`; `freeze_proposal(run_id, draft_id, payload)` verified against `drafts.draft_sha256`; status answers and conversation clarifications are messages, not events; the sweeper iterates tenants; `clarify` after the active-run check; `ABORT_REQUESTED` in the attempt-state enum; T42 now precedes T04.
- **Plan A rewritten** in the order T01, T03, T02, T42, T04, T06, with every "Expected" line stating only what the step's command prints, generators writing their own LF files, a model unload before the cold call, an AST cross-import test, a clean-clone sync step, and the full checker tail shown. Plans B and C are written after Plan A executes and are dry-run before execution.

## 1.3.5 (2026-10-07): round-7 fixes

- `docs/reviews/plan-review-r7-2026-10-07.md`: 10 of 13 round-6 items closed; 5 high, all in 1.3.3/1.3.4 text; the `session_user` mechanism verified sound.
- Fixes: `supersedes_run_id` and `intent` are requester-asserted fields on `runs`, injected by `freeze_proposal`, rejected in drafts; `transition_run` is worker-only with pre-grant targets; `create_run` creates runs (∅ → QUEUED row); seeds via `migrator` `BYPASSRLS`; `sweeper_all` policies; `revoke_handles`; `record_status_answer`; `clock_offset`; `set_config(…, true)`; admission `clarify` route (R018 kept); `action.granted`/`action.redispatched` owners; `deliver_outbox` job type.
- Showcase corrected: "Planned proof", "Where the code will live (not yet written)", the graph redrawn from the ten-route table with interrupts marked, host-side Ollama stated, a "Not claimed" block, README "Target tests" and limit sentences. PROJECT_HISTORY round attributions corrected against the review files and the author's mistakes listed.
- 47 tasks, 131 requirements.

## 1.3.4 (2026-10-07): showcase

- Owner direction: the project must properly show least privilege, routers, orchestrators and MCPs. ADR-0003.
- New AM-16 (admission router, graph router node, model router; R129, R130). MCP server split into `mcp-read` (role `mcp_read`, 3 functions) and `mcp-write` (role `mcp_exec`, 6 functions) with disjoint handles and audiences (R131); T15 = mcp-read, new T47 = mcp-write; T08 runs both.
- `docs/ARCHITECTURE.md` maps the four concepts to components, requirement IDs and demos; the README has a "What this demonstrates" table.
- 47 tasks, 131 requirements.

## Plan B executed (2026-10-08, branch `plan-b`)

- Plan written from the real Plan A artifacts; three adversarial rounds before execution (static + builder dry-run twice; `docs/reviews/plan-review-b-2026-10-08.md`). Findings that changed the plan: the model-pins loader rejected the digest format the probe writes; the readiness probe grepped a body that is `UP` even when DOWN; audience assertions were "contains" not exact; a wildcard redirect; Keycloak answers a deleted admin's password grant with 400; the ruff formatter rejected the plan's code; **container traffic reaches the host from 127.0.0.1** (so a loopback bind, not a WSL-subnet firewall rule, is the control); `OLLAMA_HOST` is set at User scope, not Machine.
- Execution: T05 (f864197, a23f602, b7b5266, e530082), T43 (051c828, 628c638), T44 (06bcec0, 8841305). Task reviews found plan-mandated defects fixed in the fix rounds: a rotation recipe that put the secret in argv while claiming otherwise, a placeholder test whose failure message would echo a leaked literal (the first fix, a custom assert message, did not work because pytest's assertion rewriting still prints the operands; the final review caught it, and the tests now assert on a precomputed list of client and user identifiers, with proof tests that tamper a copy and check the literal is absent), a runbook fallback that duplicated its rule on re-run and referenced plan-internal steps.
- Evidence: `reports/bootstrap/keycloak-claims.txt` (9 redacted claim lines), `bootstrap-admin.txt`, `compose-ps.txt`, `ollama-bridge.txt`; `tests/plan_b/test_evidence.py` rejects any token or secret value there.
- Plan A code re-commented per `docs/CODE_COMMENTS.md` (c25ee89, 32bf85d); commit history carries no tool attribution.

## Plan C executed (2026-10-08, branch `plan-c`)

- Plan written from the real Plan A and B artifacts and a line-by-line inventory of the spec; two adversarial rounds before execution (`docs/reviews/`). Execution: T07 = `36c1007..09341d2` (canonical JSON, states, jobs/routes/outcomes, contracts), T45 = `165489b..6c7e1cd` (fixture meta, generator and `--contracts` checker, conformance test), T46 = `c9d0131..843f365` (reference traceability). Plan commits 36eb767 and 28fe2a6.
- Final whole-branch review fix wave (`.superpowers/sdd/2026-10-08-first-slice-c-contracts-schemas/final-fix-report.md`): canonicaliser recursion, cancel-response grant rules, typed dedup keys, end-anchored schema patterns, an `Event` envelope model, and a differential mutation test (326 mutants of 22 valid examples) that requires schema and code to agree.
- `PYTHONUTF8=1 uv run python scripts/check.py` ends `381 passed, 30 skipped`, `CHECK: GREEN`. `--contracts` passes: 26 JSON Schema documents, 34 accepted and 53 negative examples. The tree is 25 schemas, 87 examples (34 valid, 53 invalid), `index.json` 1.3.3. Conformance test: 110 cases, 91 passed, 19 skipped with stated reasons. Transition table: 44 rows, 38 pairs, 13 performers.
- Evidenced locally, not a running capability: R004, R005, R082 (without the "logged" half, `TODO(T09)`), R083, R104, R123 (acceptance matrix `RECORDED_LOCALLY`); R120 stays `NOT_RUN` because its 409 `SLOT_OCCUPIED` is T21's. Still no target capability.
- **The nine rulings, proposed as spec errata.** The owner decides; the spec text stays authoritative until then.
1. AM-20.3 "Who performs which transition": the `create_revision` row should read "AWAITING_APPROVAL / APPROVED / BLOCKED_REVIEW → QUEUED", matching the function table and BUILD_SPEC §8.
2. AM-13 "Outcome vocabulary": `FAILED_NO_COMMIT` carries `reason ∈ {aborted_no_commit, cancelled_before_send, rejected, expired}`; `expired` is produced by the recovery table (INTENT after the deadline) and by `create_incident` past the deadline.
3. AM-20.3 `search_procedures_scoped`: `mode=vector` is the SQL argument value; the externally visible `retrieval_mode` is `vector_exact`, and mcp-read translates between them.
4. BUILD_SPEC §8 `QUEUED → AWAITING_INPUT` is superseded: missing context is detected in RETRIEVING (AM-10), and `transition_run` allows only `QUEUED → RETRIEVING`.
5. AM-20.3 "any pre-grant active state → CANCELLED" should read "any pre-grant non-terminal state, including BLOCKED_REVIEW", as the AM-10 BLOCKED_REVIEW row already allows.
6. BUILD_SPEC §6 "UTC instants with explicit offsets": only hashed documents (the proposal) spell UTC as `Z`; `manual-proposal`, `model-pins` and the `get_recent_alerts` input accept `Z` or `+00:00`, as do request bodies, and the contract normalises to `Z` before hashing.
7. AM-80 "Negative probes": "before writing contract code" should read "before any service consumes a schema"; T45 depends on T07 in `handoff/tasks.json`, and the conformance test needs both.
8. AM-10 "Reasons": a FAILED run reached by `transition_run` on exhausted infrastructure policy carries no reason; the `run.failed` event's message says why.
9. AM-20.3 "Who performs which transition": add `create_manual_proposal` with the `freeze_proposal` rows (DRAFTING → AWAITING_APPROVAL; DRAFTING → BLOCKED_REVIEW on `asset_action_unresolved` / `asset_incident_exists`); the function table already says it is otherwise identical to `freeze_proposal`.
- Design note: the answer-only refusal is a guard (`freeze_allowed`) that `freeze_proposal` calls next to the table rather than a table row, because it depends on the run's requester-asserted intent, not on its state.
- Design note: `outcomes.Event` is the minimal envelope the event schema requires (envelope fields plus `event_rules_ok`); T14 owns its evolution.
- **Open items for Plan D (from the final review; decide at the API boundary).**
  - The bytes a stored proposal hashes: `Proposal` accepts a document whose raw payload hashes differently from its normalised form, and the checker hashes the raw payload, so the skeleton must store, send and hash only `canonical_json(ProposalPayload.canonical_dict())`.
  - Null and whitespace conventions: the code accepts an explicit `null` for optional fields and strips whitespace-only strings to a rejection, while the schemas reject `null` and accept whitespace-only strings; pick one convention per side and state it in the generator.
  - Timestamp edge cases: more than six fractional digits are truncated (two inputs freeze to one instant), and the code accepts `…T12:00Z` without seconds, which the schema refuses.
- Findings worth remembering: the canonicaliser hashes NFC-normalised bytes, so uniqueness and ordering are checked on normalised strings (a Critical caught in Task 4); duplicate JSON keys are rejected; the conformance test caught the schema and the code disagreeing on `action.conflict` carrying an outcome (the schema was right, AM-14). Pytest totals drifted +39 from the plan's expectations because each fix round added tests; the ledger tracked the offset.

## Plan D executed (2026-10-08, branch `plan-d`)

- T08 = `8136ee6..d7b6359`. The plan (`docs/superpowers/plans/2026-10-08-first-slice-d-walking-skeleton.md`) holds the 27 rulings (processes on the host, the one read tool, persona tokens at the API, wall clock, owner role and databases, Alembic layout, revision 1 tables, the event sequence, the incident-sim contract, proposal storage, reviewer independence, job claiming, the single transition function, the fake model, MCP specifics, the e2e test, dependencies, health, invocation handles, error mapping, failure after SENT, the proposal read route, event loops, connections, 401 for any refused token, test locations, live clean-up) and the eleven debt additions; `docs/reviews/plan-review-d-2026-10-08.md` keeps the review record.
- The three Plan C open items are decided by rulings 10 and 4: the stored, sent and hashed proposal bytes are `canonical_json(ProposalPayload.canonical_dict())`; request bodies take explicit `null` for optional fields and reject whitespace-only strings; emitted timestamps are `...Z` with seconds and no fraction.
- Evidence: `reports/skeleton/r105-walking-skeleton.txt`; the live suite is `14 passed`; `check.py` ends `457 passed, 44 skipped`, `CHECK: GREEN`. Run it per `docs/runbooks/walking-skeleton.md`.
- **The eleven declared shortcuts** (the debt list below, each with its owning task): processes on the host (T30); lexical `search_procedures` from fixtures, no asset tools (T16/T17); persona bearer tokens instead of sessions (T11/T12); wall clock and unenforced expiry (T09/T21); incident-sim's two routes only (T10); polling worker without reclaim (T13/T14); `WHERE tenant_id` instead of RLS (T09); handles not revoked (T15); the single owner role (T09); grant and `mark_sent` without membership, cancellation or deadline re-checks, and unbounded bodies (T09/T12/T21/T22); frozen membership `issuer` (T09).
- **Open items for Plan E (T09/T10) and later**, parked by the task reviews:
  - mcp-write reconciliation-era items (T22): an early return before `escalate_run` exists; the service token is fetched after SENT;
  - the decision-hash cross-check, and BLOCKED_REVIEW on a refused grant (T21/T22);
  - per-service `tests/` directories (T30);
  - `authored_by` is read outside the decision transaction (T21).
  - the request body is parsed before authorisation in the API (T12), and the in-memory `FakeStore` does not check the tenant (T09 tests);
  - mcp-read truncates an excerpt silently (bounded by the contract) and answers every handle rejection with the same `INVALID_HANDLE` (T15);
  - event sequence gaps are documented, not prevented (T14); a foreign tombstone maps to UNKNOWN (T22);
  - the token verifier propagates a non-transport exception from an injected fetch (test code only; T13);
  - Task 8 M3 (worker health-probe note) and the Task 1 cosmetics: duplicated old persona lines in `reports/bootstrap/keycloak-claims.txt`, no unit assertion on timezone UTC. The ledger (`.superpowers/sdd/2026-10-08-first-slice-d-walking-skeleton/progress.md`) has the detail.

## Plan E executed (2026-10-08, branch `plan-e`)

- T09 and T10 = `3fb9645..5fbb272`. The plan (`docs/superpowers/plans/2026-10-08-first-slice-e-roles-rls-definers.md`) holds the rulings; `docs/reviews/plan-review-e-2026-10-08.md` keeps the review record. Evidence: the live modules `tests/e2e/test_roles_live.py`, `test_clock_live.py`, `test_definers_run_path_live.py`, `test_definers_write_path_live.py`, `test_incident_sim_live.py` and `test_migrations_and_persistence.py`, the unit half in `tests/plan_e/`, and `reports/skeleton/r105-walking-skeleton.txt` (R105 under the new roles: `destination_refusals=persona:403,worker:403`, `keys=consistent`).
- Gates (after the final-review fix wave `e8e71a7`): `check.py` ends `530 passed, 82 skipped`; `check.py --profile test` (the live suite included) ends `591 passed, 21 skipped`; `verify_handoff.py --reference-code --manifest --contracts` exits 0. `check.py --profile test` is this repository's reading of SA:529 and needs the dev stack up.
- **Proposed errata (the owner decides; the spec text stays authoritative until then).** Numbered on from Plan C's nine:
  10. AM-20.5: the policy text (SA:512's bare cast) should read SA:446's `NULLIF(current_setting('app.tenant_id', true), '')::uuid` form, because `''` raises 22P02 (measured in the spike); an empty setting then sees no rows.
  11. AM-20.2: the worker also needs `jobs.available_at` and `app_definer` needs `runs.updated_at` (UPDATE on those columns).
  12. AM-20.3: there is a 24th definer function, `resolve_identity`, for the session-to-membership lookup.
  13. AM-20.3 signature deviations: `create_run` takes the request and returns `(run_id, state_version)`; `transition_run` takes a detail `jsonb`; `freeze_proposal` takes the stored bytes and verifies a requester-asserted `supersedes_run_id` instead of having it injected; `record_decision` takes the tenant and the reviewer; `append_event` takes a source and refuses a wider list of reserved event types.
  14. AM-20.3: `mark_unknown` is worker-only; mcp-write reports UNKNOWN to the worker, which dispatches an `execute` job for runs left in EXECUTING.
  15. AM-20.6: `app.current_time()` is a definer function callable by every runtime role.
  16. SA:529: `check.py --profile test` runs the live suite against `ops_test` and `incident_test`.
  17. AM-20.3: the definer functions take no row lock on `proposals`, `decisions`, `memberships` or `execution_grant`, because a lock needs UPDATE on the table (plan ruling 23).
  18. AM-20: the `OC001` authority check is reachable only past the EXECUTE ACL, so a role without EXECUTE never sees it.
  19. AM-20.3 `resolve_invocation` returns `job_type`, `job_id` and `conversation_id` instead of SA:459's `allowed_tools` (plan ruling 21).
  20. `app.transitions` is a table outside AM-20.2's list (plan ruling 10).
  21. A CONFLICT on a terminal run is `action.conflict`, not late evidence.
  22. `mark_sent` and `record_outcome` carry state guards, and an outcome before SENT is refused (Task 4).
  23. The event-type allowlist and `create_run` parsing happen after `_authority` (Task 3).
  24. CONNECT is granted exactly per role and `test_harness` exists only in the test profile (Task 2).
  25. The sweeper's `del` without `sel` on `sessions` and `idempotency_request` cannot run a `DELETE ... WHERE expires_at < ...` (spike section 3); flagged for T11/T12.
- **Open items for Plan F and later**, parked by the task reviews (ledger: `.superpowers/sdd/2026-10-08-first-slice-e-roles-rls-definers/`):
  - the eleven definer functions without a caller arrive with T11, T13, T15-T17, T21 and T22 (the Plan E debt list below names each);
  - R122 (checkpoint tables reachable only by the worker) -> T20: `langgraph-checkpoint-postgres` is not locked;
  - the `migrator` login -> T30; the expiry and asset guard -> T21;
  - the lease fence (binding the raw handle for `mark_sent` and `record_outcome`) -> T13/T22;
  - untested branches -> T13/T22: FAILED_NO_COMMIT from SENT, CONFLICT on EXECUTING, redispatch, `mark_sent` on a cancelled run, `freeze_proposal` ANSWER_ONLY / SUPERSEDES_MISMATCH / revision, `grant_execution` NO_APPROVAL / CANCELLED / MEMBERSHIP_INACTIVE, a write handle at mcp_read;
  - the abort client and the `abort_incident` tool -> T47/T22; the six remaining BS:405 faults -> T13; a schedule for the detective check (`skeleton.py keys`) -> T32;
  - the pre-SENT `STALE_RUN` / `HASH_MISMATCH` envelopes and the expired-handle read-back have no dedicated test -> T13/T47;
  - `transition_run` called with a NULL `expected_version` relies on the from-state under `FOR UPDATE` rather than a version check (by design, Task 3 review M3)
  - a zero-orphan case for `skeleton.py keys` needs a clean database pair -> T32/T13; a shared connect-and-assert helper for the three servers (the MCP lifespans duplicate it and incident-sim never closes its connection) -> T13/T30; the `testclock` branch revision still renders its grantee tuples from the live matrix (freeze them in the next migration task).

## Plan F executed (2026-10-09, branch `plan-f`)

- T11 = `0d1a892..ad3163f` (the debt list first, then the seven tasks, the handoff close-out afaede4 and the final-review fix wave bc6d16c, ad3163f). The plan (`docs/superpowers/plans/2026-10-08-first-slice-f-sessions-login-sync.md`) holds the rulings; `docs/reviews/plan-review-f-2026-10-09.md` keeps the review record. Evidence: the live module `tests/e2e/test_auth_live.py` (login, CSRF, idle expiry, logout, back-channel logout, forged token, disable-and-sync), `reports/auth/t11-sessions-revocation.txt` (header plus eight lines) and `reports/skeleton/r105-walking-skeleton.txt` (the walking skeleton now runs six processes, the sweeper being the sixth); the unit half is in `tests/plan_f/`. Locked versions: authlib 1.8.0 and joserfc 1.7.5 (AM-30's 1.8.0 holds). Measured: R086 `synced_after` 23-24 s (the 60 s target holds) and the sweeper re-stamp 25 s.
- Gates: see STATUS.md ("Update - Plan F executed") for the final counts. `check.py --profile test` needs the dev stack up and `skeleton.py status` all down.
- Rulings made during execution: (a) Keycloak with `KC_HOSTNAME_BACKCHANNEL_DYNAMIC=true` spells the server-side endpoints with the host the discovery document was fetched from, so `Discovery.from_document` accepts `token_endpoint`, `end_session_endpoint` and `jwks_uri` under `base_url` or `server_url`, while `authorization_endpoint` must be under `base_url` (a third host is refused). (b) The maintenance job row's `available_at` is on `app.current_time()` and the sweeper claims the id it inserted (ruling 24 of Plan E). (c) The listing guard counts absent subjects only (floor 3, more than half), with `OPS_SYNC_ALLOW_MASS_DEACTIVATION=1` as the owner's one-shot override (the sweeper clears it after its first successful sync); an active subject absent from the listing is deactivated only after `enabled()` confirms it (a 404 or disabled), so an offset-paging race keeps the user.
- Amendment to ruling 3 (final review I1): the 8 h SSO lifetimes are paired with `max_age` equal to the 30-minute idle limit on every authorization request (the ID token's `auth_time` must be no older, zero leeway), and an idle- or absolute-expired application session also ends its Keycloak session with the sealed refresh token, so idle expiry always means a password on the next login.
- **Proposed errata (the owner decides; the spec text stays authoritative until then).** Numbered on from Plan E's twenty-five:
  26. AM-20.3: `sync_memberships` is the sweeper's routine, not a definer function (SA:470 against SA:412).
  27. AM-20.2: rows for `login_state` and `logout_jti`, and `sweeper` SELECT on `sessions` (with 25).
  28. AM-01: the directory table gains `sweeper/`.
  29. A disabled or membership-less user is 401, not 403, on every path (the BS:301 reading).
  30. The dev realm carries a dev/test-only `ops-test-admin` client with `manage-users`; striking it loses R086's live disable path.
  31. The provider refresh token is stored sealed and spent at logout; the ID and access tokens are not stored.
  32. BS:352's "tenant switching" is not in v1: a subject with two memberships is refused at login and with a bearer token (SA:107 has no tenant administration; a switch needs a new session row and rotation).
  33. SA:565's "authlib's OIDC state lives in that store" is read as "the authorization request's state, nonce and verifier live in PostgreSQL" (`app.login_state`, keyed by the login cookie's hash) rather than in authlib's own session-dict machinery, which needs Starlette's `SessionMiddleware`.
  34. BS:268's route table gains `POST /auth/backchannel-logout` (SA:541 requires the endpoint) and `GET /` (a landing page until T26); the realm's SSO lifetimes are 8 h so the provider session outlives the application session; a back-channel logout whose store write fails answers 503 retryable rather than the specification's 400 (OIDC Back-Channel Logout 1.0 §2.8), and Keycloak does not retry either way.
- **Open items for later**, parked by the task reviews (ledger: `.superpowers/sdd/2026-10-08-first-slice-f-sessions-login-sync/progress.md`):
  - a conninfo password that psycopg quotes (spaces or quotes) and a generic `token=` key are not redacted; `KEYCLOAK_*` cookie redaction covers the dict and `key=value` forms only;
  - the `GRANT_DEFERRED` re-queue has no retry bound (TODO T13 at the branch; the branch itself is unit-tested since the final fix wave);
  - the live store test's atomicity case replays the two statements by hand rather than through `record_logout`;
  - a closer raising during `make_auth` or the sweeper's `_main` cleanup would mask the original startup error;
  - the back-channel live test's session counts are not scoped to its own `sid`.
- **Final whole-branch review** (opus): 0 Critical / 2 Important / 9 Minor, closed in one fix wave (bc6d16c, ad3163f) with a clean re-review; record `docs/reviews/plan-f-final-review-2026-10-09.md`. The two Important findings: the 30-minute idle limit was undone by the 8 h provider session (fixed two ways: `max_age` on the authorization request with a bounded `auth_time` in the ID-token verifier, and an expired session row now ends the provider session with its sealed refresh token, live-proved by the login form reappearing), and the disable live test lacked positive controls (added). Also closed: the override is consumed by the first successful sync; absent subjects are confirmed by a direct read before deactivation; a key-set outage is a retryable 503 at the callback and the back-channel endpoint; a failed back-channel write is logged. Still open with owners: quoted conninfo passwords and a generic `token=` key are not redacted (T28); a close that raises during startup cleanup masks the original error (T13/T30). Optional minors from the re-review: the `auth_time` bound and Keycloak's own `max_age` check can disagree at the boundary (one retry); the post-disable `me` check has a tens-of-milliseconds flake window against the sweeper tick.

## Walking-skeleton debt list (T08; committed before coding) [R6-B7]

Allowed shortcuts in T08, each with its owning task:
- single owner DB role, no AM-20.2 grants, no RLS → T09;
- both MCP servers run but with the single owner DB role (their function-only roles arrive in T09; the server split itself is NOT debt);
- plain INSERTs and UPDATEs instead of `transition_run`, `append_event`, `record_decision`, `freeze_proposal`, `grant_execution`, `mark_sent`, `record_outcome`, `resolve_invocation` → T09/T13/T22;
- no `app.current_time()` / test clock → T09;
- no lease, fence, heartbeat or model permit → T13;
- no idempotency keys, outbox or `next_event_seq` lock → T14;
- no asset guard or expiry → T12/T21;
- raw handle not hashed → T09/T15;
- fake model → T19; no LangGraph or durability → T20.
- the five application processes run on the host, started by `scripts/skeleton.py`; no Dockerfiles, images or Compose services for them → T30;
- `search_procedures` is served lexically from `data/handoff-fixtures/` inside mcp-read (no governed store, no `asset_scope`) → T17; `get_asset_status` / `get_recent_alerts` and asset-sim are absent → T16;
- the API accepts bearer persona tokens from the dev-only direct grant (audience `ops-api`) instead of browser sessions, CSRF and `Idempotency-Key` → T11/T12;
- wall clock instead of an injected clock; the interval is resolved once at admission and stored; expiry and asset freshness are written but not enforced → T09/T21;
- incident-sim implements `POST /internal/incidents` and `GET /internal/actions/{id}` only; abort, the fault factory and the detective check → T10;
- the worker claims jobs with `FOR UPDATE SKIP LOCKED` and polls; no wake-ups, no outbox, no reclaim of a job whose handler crashed (its run and conversation slot stay held) → T13/T14;
- tenant scoping is a `WHERE tenant_id = …` in each query; no RLS, no `run_directory` → T09;
- handles are not revoked at job end and resolution ignores run and attempt state → T15 (the raw, unhashed handle is already on the list above);
- the runtime connects as the Compose superuser `ops` (the single owner role); `incident` can CONNECT to `ops`; no CONNECT revocation → T09;
- the grant re-reads no current membership, and neither grant nor mark_sent re-checks cancellation or the dispatch deadline → T09/T21/T22; request bodies are not size-bounded → T12;
- the membership rows' `issuer` is frozen at migration time from `OPS_KC_ISSUER` (a realm moved to another port needs a re-migration) → T09's membership sync.
- an execute job whose write call cannot reach mcp-write is re-queued every 30 s without a retry bound → T13/T22;
- no reconnect after a database restart: every process must be restarted → T13;

Not debt (must be real in T08): client-credentials tokens from T05; aud/azp/iss checks in mcp-read, mcp-write and incident-sim; `action_key` ON CONFLICT; a decision step by a second persona; every transition routed through T07's table.

## Plan E debt list (T09, T10; committed before coding) [R6-B7]

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

## Plan F debt list (T11; committed before coding) [R6-B7]

Allowed shortcuts in T11, each with its owning task:
- no `Idempotency-Key` on the new mutations (`/auth/logout`) or the existing ones; `idempotency_request` does not exist → T12;
- the enabled check guards the one decision-class route that exists (`POST /api/v1/proposals/{id}/decisions`); revisions, cancel and manual proposals attach the same dependency when they arrive → T21;
- the "grants blocked within 60 s" half of R086 is implemented (`MEMBERSHIP_INACTIVE`/`MEMBERSHIP_STALE` in `grant_execution`) but its live evidence through a real grant lands with the final gate → T21;
- no SSE stream exists, so "stop old streams on identity change" has no code yet; the identity dependency is the hook T27 rechecks every 30 s → T27;
- `GET /` is a JSON landing page until the web app exists → T26;
- the sweeper runs `sync_memberships` and the expiry purges only; `expire_proposals`, `sweep_wakeups`, `deliver_outbox` and lease reclaim → T13/T14/T21;
- the back-channel logout URL in the realm export names `host.docker.internal:8000` (the host API from the Keycloak container); the containerised URL → T30;
- the telemetry side of redaction (traces, metrics labels) → T28;
- a two-tenant subject is refused rather than offered a tenant switch (SA:107: no tenant administration in v1); a switch, if ever, needs a new row and rotation → v2;
- the dev-only clients `ops-dev-direct` and `ops-test-admin` exist in the dev realm only; the demo profile's realm must omit both → T30;
- the sweeper inserts one `sync_memberships` job row per minute and holds no DELETE on `jobs`, so done maintenance rows accumulate; the sweeper's purge of finished jobs (an AM-20.2 cell for `sweeper` `del` on `jobs`, or a definer) → T14;
- `/auth/login` trusts the request's `Host` header to decide whether to bounce to the public base URL; a reverse proxy that rewrites `Host` needs trusted-proxy handling (`X-Forwarded-Host`) → T30.

## Environment (observed)

| Item | Observed |
|---|---|
| OS | Windows 11 Home 10.0.26200 |
| CPU / RAM | Ryzen 9 5900X / 31.9 GB |
| GPU | RTX 3080 (10 GB) |
| Python | 3.13.7 (`python`), 3.14.6 (`py`) |
| uv | 0.11.8 |
| Docker | Docker Desktop 29.6.2 |
| Ollama | 0.33.3, with `qwen3:8b` and `nomic-embed-text` installed |
| Node | 24.15.0 |
| git | 2.54 |
| Not installed | psql, helm (kubectl present) |

## Owner decisions recorded

- Portfolio/learning purpose; synthetic data only.
- Keycloak for identity.
- Local `qwen3:8b`.
- Every failure category proven by tests.
- Separate-services architecture.
- MIT license; publish publicly to `jschnepel/MLOps` once logged in.

## Dev database state (2026-10-08)

The owner approved migrating the dev database: `skeleton.py migrate` (dev profile) applied revisions 0002–0004 to `ops` (`app@head`, no `app.test_clock`) and incident revision 0002 to `incident`; `skeleton.py up` then brought all five processes to ready under their own roles and `down` stopped them.

**Update (2026-10-09):** the owner ran `uv run python scripts/skeleton.py migrate` (dev profile) after Plan F closed: the dev `ops` database is at revision `0005_sessions_login_logout` (`sessions` columns, `app.login_state`, `app.logout_jti`; `sessions` was empty, so nothing was at risk). `skeleton.py up` then brought all six processes (incident-sim, mcp-read, mcp-write, api, worker, sweeper) to ready under their own roles and `down` stopped them. The shared dev realm already carries the Plan F clients (`ops-test-admin`, the `ops-web` back-channel attributes, the 8 h SSO lifetimes) from the re-import in Task 2.

## Open owner inputs

- Merge the stacked PRs #1-#5 in order (opened 2026-10-09, all green on CI; the first merge also exercises the push-to-main trigger).
- Decide on the nine proposed contract errata (see "Plan C executed").
- T03: the owner writes about 25 holdout case intents without AI help, keeps them off-machine, and records the seal hash externally before T02.
- T06 is closed (public repo, PRs green). The first CI runs were red on ruff EXE001 (a shebang on a non-executable file, a rule ruff skips on Windows) with every test green; fixed by a file-mode commit on each branch.
- T44 step 10: run `docs/runbooks/ollama-network.md` step A (`OLLAMA_HOST=127.0.0.1:11434` at User scope, restart Ollama), verify with the three checks, fill the attestation table, and decide whether to adopt the proposed AM-31 errata (loopback bind primary, firewall fallback).

## Exact next step

On a fresh clone or after any `uv sync`:

```bash
uv sync --locked
uv run python scripts/check.py
uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts
```

Reference test suite (T01 procedure, as re-run from `reference/` in T42; Git Bash; venv outside the repo, installed without `-e`; delete the in-tree `build/` and `*.egg-info` afterwards):

```bash
uv venv "$LOCALAPPDATA/ops-ref-venv" --python 3.13
uv pip install --python "$LOCALAPPDATA/ops-ref-venv" "./reference[web,test]"
(cd reference && "$LOCALAPPDATA/ops-ref-venv/Scripts/python" -m pytest -q)
```

To run the walking skeleton (dev stack up; see `docs/runbooks/walking-skeleton.md`):

```bash
uv run python scripts/skeleton.py migrate
uv run python scripts/skeleton.py up      # then: status, and down when finished
OPS_LIVE=1 PYTHONUTF8=1 uv run python -m pytest tests/e2e -q   # with no skeleton running; rewrites the evidence
```

Then wait for the owner inputs above (holdout seal, then live probe; push and PRs; the Ollama runbook step A) and write Plan G as described in the Next task line.

Do not store secrets or private reasoning in this file.

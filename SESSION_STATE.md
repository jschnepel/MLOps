# Session state

**Specification:** OPS-BUILD-1.3.6 (`BUILD_SPEC.md` + `SPEC_AMENDMENTS.md`)
**Current milestone:** M00 (baseline, sealed holdout intents and model probe)
**Next task:** Plan K (T47) is executed on branch `plan-k` (on top of `plan-j`: `dd9f7b1..ea0bf54` holds the debt list and
the five building tasks, the close-out is `a335e1b..6ec740f`, the final-review fix wave `b2ba317..5c96f0d`, the final review record `30f47d4`). T47 is DONE subject to the owner's decisions on errata
72, 84 and 91 (R131's function sets and the attempt-state allowlist). Owner inputs: (1) the holdout seal (T03 step 9),
then the live probe (T02); (2) merge the stacked PRs #1-#10 in order (plan-b -> main through plan-k -> plan-j; #10 is
https://github.com/jschnepel/MLOps/pull/10); (3) T44 step 10 (step A applied 2026-10-16; the other-device LAN check and the firewall rules remain)
(`docs/runbooks/ollama-network.md` step A); (4) decide the proposed errata of Plans C, E, F, G, H, I, J and K (K: 82-92
below). The dev database is at revision 0010 (the owner migrated it on 2026-10-16). Next
is Plan L = T17 (the governed corpus, the earliest dependency-satisfied PLANNED task in `handoff/tasks.json` after
T47, unblocked by T09).
**Plan A outcome:** executed on branch `plan-a` (a638801..HEAD); `scripts/check.py` GREEN (54 passed, 1 skipped: owner seal). Final whole-branch review: 5 Important findings fixed in the final-review wave; minors deferred: M3 timing restructure (`astream`), M6 mypy member list.
**Repository:** local git repo at `C:\Users\joeys\Desktop\MLOps`, branch `plan-k` (Plan K work on top of `plan-j`, on top of `plan-i`, on top of `plan-h`, on top of `plan-g`, on top of `plan-f`, on top of `plan-e`, on top of `plan-d`, on top of `plan-c`, on top of `plan-b`, on top of `plan-a`). Remote `github.com/jschnepel/MLOps` (public, MIT) exists; `main` and `plan-a` were pushed on 2026-10-07. `plan-b` to `plan-e` were pushed on 2026-10-08 and `plan-f` on 2026-10-09; `plan-g`, `plan-h` and `plan-i` are pushed too, and every pushed branch matches its local one (checked 2026-10-15). PRs #1-#5 were opened on 2026-10-09 and are green after the EXE001 fix (first green run https://github.com/jschnepel/MLOps/actions/runs/37962510516; record `reports/ci/t06-first-ci-runs.txt`); PRs #1-#10 (plan-b -> main through plan-k -> plan-j) are open now; `plan-j` and `plan-k` are pushed (2026-10-16). Merging them in order is the owner's call.

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

## Plan G executed (2026-10-10, branch `plan-g`)

- T12 = `c5d3bbc..b4fb01f` (the debt list first, then the seven tasks). The plan
  (`docs/superpowers/plans/2026-10-10-first-slice-g-admission-idempotency.md`) holds the thirty rulings; the
  inputs are `docs/superpowers/research/2026-10-09-plan-g-inputs.md` and
  `docs/superpowers/research/2026-10-10-plan-g-spike.md`.
  Evidence: `tests/e2e/test_admission_live.py` and `reports/admission/t12-admission.txt` (header plus fourteen lines),
  `tests/e2e/test_migration_0006_live.py`, `reports/skeleton/r105-walking-skeleton.txt` (R105 with keys); the unit
  half is in `tests/plan_g/`.
- Gates: `check.py` 805 passed / 104 skipped; `check.py --profile test` 888 passed / 21 skipped; `verify_handoff.py`
  exit 0 (STATUS.md, "Update — Plan G executed"). The plan's stated tails (788/104 and 871/21) are offset by +17, the
  tests the fix rounds added (see ruling (d)).
- **Proposed errata (the owner decides; the spec text stays authoritative until then).** Numbered on from Plan F's
  thirty-four:
  35. BS:264: the Idempotency-Key is required on every `/api/v1` mutation; `/auth/logout` and
      `/auth/backchannel-logout` are exempt by design, and the test-profile fault route from the key only (it keeps
      identity and the CSRF/origin check).
  36. SA:429 (AM-20.2 `idempotency_request`): the sweeper holds SELECT beside its DELETE (erratum 25 extended).
  37. SA:188: the lock order begins with the idempotency scope's advisory lock, PostgreSQL's two-key form
      `pg_advisory_xact_lock(1, hashtext(<scope>))` (namespace 1, `hashtext`), a lock space distinct from the asset
      guard's one-key locks.
  38. BS:548 and R017: a read-only (`answer_only`) run holds the conversation slot and needs an asset and an
      interval.
  39. BS:550: T12 bounds QUEUED runs per tenant (default 100); the global bound moves to T13. A full tenant queue
      answers 429 with `Retry-After` and writes nothing: AM-16's "nothing written except the idempotency record"
      covers the router's 409 and 422 rejections; a 429 writes nothing.
  40. SA:369 (AM-16 `clarification_reply`): the entry is BS:273's `POST /api/v1/runs/{id}/clarifications`; on the
      messages route `kind=clarification` is a 422 reject.
  41. SA:450: `supersedes_run_id` is validated against the tenant and the conversation.
  42. BS:230 with SA:370/SA:372: the message sequence is the table-wide identity `messages.seq`; the stored kinds
      are `investigate`, `ask`, `status_question`, `status_answer`, `clarification_question`, `clarification_reply`;
      `author` is NULL exactly for the two system kinds.
  43. BS:301: a wrong method keeps 405 (`INVALID_INPUT`, with `Allow`); the body limit is 422, never 413, and is
      checked before identity because it is middleware.
  44. SA:373 (AM-16 `reject`): an unroutable `kind` and an over-limit text are refused by the strict request model
      as an unrecorded 422 before the router; only the router's own rejects write a record.
- Rulings made during execution (three amend plan rulings 19 and 12; the plan text stays as written, this is the
  record):
  - (a) Amends ruling 19 (Task 1 review): psycopg's class-53/54 errors are flat siblings of `OperationalError`, not a
    hierarchy, so the retryable split is by SQLSTATE inside `_database_down`: class 54 and 53400
    (configuration_limit_exceeded) answer the non-retryable 503 "service error"; 53100/53200/53300 (disk full, out of
    memory, too many connections) stay retryable; the two class-specific handler registrations are gone. Why: BS:562
    says never retry what is not transient. Tests cover the five limit classes and DiskFull.
  - (b) Amends ruling 19 (Task 1 review): the catch-all is no longer a Starlette `Exception` handler (whose
    ServerErrorMiddleware re-raises, so the server logs the traceback with the exception's text) but the outermost
    pure-ASGI middleware `SafeErrors` in `api/src/ops_api/limits.py` (order SafeErrors, RequestId, BodyLimit): one
    ERROR line with the request id and the exception class, never its text; the safe 503 `retryable: false` if the
    response has not started; no re-raise. The request id is read everywhere through
    `limits.request_id_of(request.scope)`.
  - (c) Amends ruling 12 (Task 3 review; narrowed by the final review): the window number pattern reads ASCII digits of any count with optional
    thousands commas and an optional or leading decimal point (`[0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?` or `\.[0-9]+`), so
    "last 12345 hours", "last 1,000 hours" and "last .5 days" are read and can conflict or fall out of range; the form
    never wins silently on a number the parser can see. `AdmissionRule.cause` and `AdmissionDecision.cause` are typed
    `ClarifyCause | RejectCause | None`; `TEXT_ASSET`'s quantifiers are capped at `{0,31}` (linear) with the
    32-character check kept; `said()` pluralises; the R129 walk asserts causes and shares the module's
    `resolution_for`.
  - (d) Gate arithmetic: the plan's per-task tails are offset by the tests the fix rounds added (+5 Task 1, +5
    Task 3, +2 Task 4, +5 Task 5 = +17 by Task 6); the deltas held at every task. Final tails: `check.py` 805 passed /
    104 skipped; `--profile test` 888 / 21. The evidence file has a header and fourteen lines, not twelve (Task 6's
    review made R016's replay-after-the-run-moved-on proof and the status-answer counts their own lines).
  - (e) Task 2 review minors: the live purge proof binds the seeded key; the write-once live test cleans up by key and
    filters its sweeper DELETE by key; a comment records that pre-0006 rows get `seq` in physical scan order (readers
    needing history order on them sort by `(created_at, seq)`).
  - (f) Task 4 review minors: a test pins the replayed request-id rewrite at the store layer; the
    recording-connection test pins the job INSERT's grant shape (no RETURNING, no conflict target) and the two DbUnit
    refusal paths.
  - (g) Task 5 review minors: every R115 unit case asserts `code` and `retryable`; HTTP tests for the fault route's
    refusals, the cookie-mode CSRF refusal, the absent-run and other-tenant 404s on clarifications, and the
    missing-asset / missing-interval clarifications; `test_auth_live.py` deletes its records by key like R105.
- **Open items for later**, parked by the task reviews and the ledger
  (`.superpowers/sdd/2026-10-10-first-slice-g-admission-idempotency/progress.md`):
  - a malformed thousands group ("last 1,00 hours") is invisible to the window parser, so the form wins silently;
    other-script digits are unread by design (ASCII only) -> T21 (revision parsing) or a later parser pass;
  - `_idempotent`'s "not reusable yet" refusal for an unpurged expired record does the work and rolls it back before
    answering (correct, wasteful, rare); if the sweeper purges between the rollback and the re-read the client is
    told to use a new key for a key that just became reusable (harmless) -> T14/T28 polish;
  - `decide_once` reuses the "stale" message for any `Conflict` code (only `VERSION_CONFLICT` reaches it today) ->
    T21;
  - `create_app` sets `app.state.store.faults = faults` on whatever the store factory returns (works because
    `AdmissionStore` declares `faults`); passing faults into the store would be cleaner -> T13 (fault factory);
  - the global queue bound (BS:550 "100 total") is unreachable by the `api` role under RLS; only the per-tenant quota
    exists -> T13 (already a debt line of Plan G);
  - the deferred items of the Plan G debt list keep their owners: the model hint's producer -> T19, `resume_input`
    handling and the ANSWERED path -> T20, `stream_url` -> T27, response schemas -> T26, the `feedback` table -> T21.
- **Final whole-branch review** (opus, record `docs/reviews/plan-g-final-review-2026-10-10.md`): 0 Critical /
  2 Important / 6 Minor, closed in one fix wave (b4fb01f) with a clean re-review. The two Important findings
  were both in the parser the three plan rounds had already reworked: a window number large enough to overflow
  the renderer's float turned a clarification into a 503 (fixed: no float anywhere; a window with more than
  twelve integer digits asks without echoing the number; `said()` uses integer arithmetic), and a form asset
  that was one of several named in the text started a run (fixed: two or more ids in the text ask
  `asset_ambiguous` even when one is the form's; ruling 12 amended). Also closed: the `create_run` refusal
  mapping is explicit (only `SLOT_OCCUPIED` is the busy-slot 409), the reply unit sets `lock_timeout = 2s`
  before its `FOR UPDATE` (a 55P03 is the retryable 503; `TODO(T13)`), the quota count runs only for run
  verdicts, and the runbook says a recorded refusal replays for the window so a retry after fixing the cause
  needs a new key. Ledgered, not fixed: lower-case, accented or full-width asset spellings and "previous"/
  "two days" are unread (the AssetId grammar is upper-case ASCII by contract) → T21. Gates after the wave:
  `check.py` 816 passed / 104 skipped GREEN; `--profile test` 899 / 21 GREEN (the live suite re-run by the
  controller); `verify_handoff` exit 0.

## Plan H executed (2026-10-15, branch `plan-h`)

- T13 = `c5eeb89..06e961a` (the debt list first, then the eight tasks, the close-out `e9d624d` and `6fd1ec3`, and the
  final-review fix `06e961a`; the docs commit recording that fix sits on top). The plan
  (`docs/superpowers/plans/2026-10-15-first-slice-h-leases-fences-heartbeat.md`) holds the 31 rulings of the
  controller's brief as implemented; the input is `docs/superpowers/research/2026-10-15-plan-h-inputs.md`.
  Evidence: `tests/e2e/test_leases_live.py`, `test_fenced_definers_live.py`, `test_heartbeat_live.py` (three
  `slow_live` DoD-3 tests), `test_lease_stress_live.py` (the `slow_live` stress test and R019),
  `test_migration_0007_live.py`, `test_admission_live.py` (the global bound and R015's after-commit side) and
  `reports/leases/t13-leases.txt`, `t13-heartbeat.txt`, `t13-stress.txt`; the unit half is in `tests/plan_h/`.
- Gates: `check.py` 939 passed / 134 skipped; `check.py --profile test` 1052 passed / 21 skipped (the plan's tails
  are 930/133 and 1042/21; the final-review fix wave added nine unit tests and one live test); `verify_handoff.py`
  exit 0 (STATUS.md, "Update — Plan H executed"). The live gate is about 2.5 minutes longer than Plan G's: the four
  `slow_live` tests.
- **Final review** (whole branch: 0 Critical, 1 Important, 7 Minor; one fix wave, `06e961a`). I1: `release_lease`, the
  job's final unit, compared owner and fence but not liveness and skipped the local deadline, so an execute job whose
  lease lapsed during `create_incident` (answered `INVALID_HANDLE` before SENT) could be closed and its approved run
  stranded in APPROVED with no job. The release now checks the local deadline first and requires a live lease after
  its row lock, so that case hands the job back and the next owner runs it again. M1: the heartbeat judges a failed
  renewal, and any error its catch-all logs, on a fresh clock reading against the local deadline. M4: readiness
  requires the heartbeat thread to be alive. M5/M6: the R107 wording in ARCHITECTURE, the history entry, these spans
  and the stress test's "Catches" list. M2, M3 and M7 are debt lines (Plan H debt list). Erratum 59 was judged sound.
- **Proposed errata (the owner decides; the spec text stays authoritative until then).** Numbered on from Plan G's
  forty-four:
  45. SA:418: `app_definer` holds `sel, upd(fence)` on `run_lease`.
  46. SA:174: the worker creates the lease row at the run's first acquisition (released, fence 0; the first real
      fence is 1), locks before it inserts, and a lease is free when `lease_until <= app.current_time()`.
  47. SA:453 (and `transition_run`, `append_event` as the worker calls them): the worker's unit takes `run_lease FOR
      SHARE` and checks the fence before the call; the functions keep their signatures.
  48. SA:463/464: `mark_sent(raw_handle, action_id)`, `record_outcome(raw_handle, action_id, outcome, doc)`; a stale
      fence or a lapsed lease is the handle refusal OC008.
  49. SA:471: `reclaim_leases` is the sweeper's routine with direct grants; it un-claims claimed, unfinished run jobs
      whose lease is not live, takes no lease lock, inserts no recover job and does no permit work.
  50. SA:432: `model_permit(slot, holder, run_id, leased_until)`, one seeded slot, `worker` `sel, upd(all)`, no
      sweeper cell.
  51. BS:550 (replaces erratum 39's forward reference): a tenant quota and a global bound of QUEUED runs (100 each by
      default), the global one through the api-only definer `queued_runs_total()` and soft by the number of
      concurrent admissions; a full queue is an unrecorded 429 with `Retry-After`.
  52. SA:188: the extended lock order of `ops_core/locking.py` (advisory locks, `jobs` claim, `run_lease` … `outbox`,
      `jobs` finish, `idempotency_request`), with SKIP LOCKED and NOWAIT outside it, a fresh-row INSERT ranked at
      its foreign-key parent, and the own-unit tables named.
  53. SA:459: `resolve_invocation` reads `invocation_context` without a lock; `run_lease FOR SHARE` in
      `_resolve_handle` is the one lock, shared by every handle function.
  54. SA:467: `mark_unknown` refuses OC003 unless the caller's fence is current and its lease live, bumps the fence,
      revokes the old fence's handles and returns `(run_state, new_fence)`.
  55. SA:472: `revoke_handles` revokes the handles of the given fence and older ones and never refuses.
  56. BS:405: the nine faults map to eight hooks (`reject_next`, `drop_before_commit`, `lose_after_commit`,
      `timeout_before_accept`, `rate_limit`, `malformed_response`, `receipt_hash_mismatch`, `delay_receipt`) and one
      harness race (concurrent same-key submission, R047).
  57. SA:196-198: "exits the run" means cancelling the job's effects in flight (MCP and model calls; no database unit
      is interrupted), revoking the job's handles and handing the job back with no transition; the job's next owner
      fails a run it finds in RETRIEVING or DRAFTING (resuming it is T20's).
  58. BS:558 (found in execution): a handle's "additionally bounded by current lease" is enforced at use, not at
      mint. `_resolve_handle` compares the handle's fence with `run_lease` and requires a live lease, under
      `FOR SHARE`, so a handle is refused once its fence moves or its lease lapses. Its stored `expires_at` is
      `app.current_time() + 60 s` at mint, with no `least(…, lease_until)` cap: a cap at mint froze the lease end
      and would have refused a long write under a lease the heartbeat had renewed.
  59. AM-15 (SA:355), found in execution: it says authentication and authorization failures always return a plain
      safe error without an `action_id`. After SENT a stale-fence refusal is answered `status=outcome` / `UNKNOWN`
      with the `action_id` (ruling 6; AM-13: after SENT the only answers are a recorded outcome or UNKNOWN). Before
      SENT it stays the plain refusal.
- Earlier debt lines that named T13 and what became of them: the lease, fence, heartbeat and model permit
  (walking-skeleton debt, Plan E debt) are done; reclaim of a crashed handler's job is done (the sweeper's reclaim);
  `reclaim_leases` is done as erratum 49; the raw-handle binding of `mark_sent`/`record_outcome` is done; the six
  remaining BS:405 faults and `lose_after_commit` in the API are done; `model_permit`'s matrix row is done; the global
  queue bound is done; freezing the testclock revision's grantee tuples is done; the `jobs.type` vocabulary is
  enforced (the api-only `resume_input` restriction → T22); bounded retries and the transport path → T22;
  wake-ups and per-tenant polling → T14; pools, reconnects, the API's per-unit lock_timeout, the shared
  connect-and-assert helper, the startup-cleanup closer and the token verifier's injected-fetch exception → T30; the
  untested definer branches → T22; the pre-SENT `STALE_RUN`/`HASH_MISMATCH` envelopes → T47; a zero-orphan
  `skeleton.py keys` case → T32; resuming an investigate run interrupted in RETRIEVING or DRAFTING (today failed as
  interrupted) → T20.
- Rulings made during execution (the controller's, recorded here and as errata 58 and 59):
  - A handle's expiry at mint is `app.current_time() + 60 s`, not capped at the lease; the bound by the current lease
    is enforced at use by `_resolve_handle` (erratum 58). Reason: a mint-time cap froze the lease end, so after the
    heartbeat renewed the lease a long `create_incident` would have been refused at `mark_sent` or `record_outcome`
    under a live lease. Cost if wrong: a handle row outlives its lease by up to 60 s but is refused at every use once
    the lease is lost or the fence moved, so it grants no authority. This replaces the debt line that gave handles a
    20-30 s practical life; per-call minting is no longer owed.
  - After SENT, a stale-fence refusal is answered `outcome` / `UNKNOWN` with the `action_id`, against AM-15's plain
    error (erratum 59). Reason: AM-13 allows only a recorded outcome or UNKNOWN once the action is SENT.
  - The R107 stress test has a "drop" step in which a holder stops renewing after about 2 s, as a hung worker, and
    asserts more than three acquisitions. Reason: the planned mix never moved a lease between holders, so takeovers
    were not exercised. It relaxes nothing; its cost is a longer or flakier run.
- **Open items for later** (minors from the SDD ledger, triaged by the final whole-branch review as safe to defer;
  record `docs/reviews/plan-h-final-review-2026-10-15.md`):
  - Model permit TTL: 65 s with no cap on the hold until T19's 60 s attempt cap; a hold over 65 s would let a second
    worker take the slot (only the fake drafter exists today).
  - Smaller: the stress takeover count does not require distinct owners and no-op drops count toward its 200-operation
    floor; `asyncio.gather` rather than a TaskGroup; no test pins the quota-before-global order with both full; no live
    test refuses on the fence alone (same owner, higher fence); `test_definers_write_path_live.py:443` asserts OC003,
    which now also means a stale fence; the `take_model_permit` and `mint_handle` lock-precondition comments; faults:
    `_seconds` persists across `arm()` calls without `seconds`, the dev/demo 404 test omits `receipt_hash_mismatch`
    (closed: the final review found the 404 holds for every kind, because the route is registered only when faults
    exist, which only `PROFILE=test` allows; the R098 note says so), and `malformed_response` on a CONFLICT row
    answers 200.

## Plan I executed (2026-10-15, branch `plan-i`)

- T14 = `4aa5f92..e485c56` (the debt list, then six tasks, the sixth the close-out `9ce23a0`, and the final-review
  fix wave `e485c56`; a docs commit after it records the wave). The plan
  (`docs/superpowers/plans/2026-10-15-first-slice-i-journal-wakeups-outbox.md`) holds the 29 rulings of the
  controller's brief as implemented; the input is `docs/superpowers/research/2026-10-15-plan-i-inputs.md`.
  Evidence: `tests/e2e/test_event_journal_live.py` (R089: the stepped writers of four roles, the rollback, the
  stress run with its readers), `test_outbox_live.py` (R024, the delivered row, a sink crash on one row of three, a
  delivery lost with its sweeper at the cap, a late result),
  `test_wakeups_live.py`, `test_migration_0008_live.py` (the round trip, the payload table in SQL, the intent, the
  outbox grants, the MCP catalog check) and `reports/events/t14-events.txt`, `reports/outbox/t14-outbox.txt`; the
  unit half is in `tests/plan_i/`.
- Gates: `check.py` 1031 passed / 154 skipped; `check.py --profile test` 1164 passed / 21
  skipped (the plan's final tails are 1031/154 and 1164/21, equal to measured); the final-review wave added one unit
  test (1032 / 154 and 1165 / 21); `verify_handoff.py` exit 0 (STATUS.md, "Update — Plan I executed").
- **Proposed errata (the owner decides; the spec text stays authoritative until then).** Numbered on from Plan H's
  fifty-nine:
  60. SA:427 (AM-20.2 `outbox`): `outbox(outbox_id, tenant_id, run_id, event_id → events, channel 'local',
      recipient, dedup_key UNIQUE, attempts, leased_until, delivered_at, result ∈ {delivered, retrying,
      dead_letter}, created_at)` with the composite key to `runs` and `tenant_isolation` only; `leased_until` is
      both the claim's lease and the next attempt's time; `app_definer` `ins`, the sweeper `sel, upd(leased_until,
      attempts, delivered_at, result)`, and `api` and `worker` no cell (only `_append_event` writes intent).
  61. SA:419 (`jobs`) and SA:520 (the policies): the sweeper holds DELETE on `jobs`, and a restrictive policy
      `sweeper_purge_maintenance` holds it to finished maintenance rows; the purge deletes those older than
      `OPS_MAINTENANCE_RETENTION_HOURS` (24); a run's job is never deleted.
  62. AM-20.4 (SA:500-505) and SA:345: the sweeper re-arms a lost wake-up by reopening its job (the same row and
      dedup key); it never inserts a `resume_input` or `execute` row.
  63. SA:471 (extending erratum 49): lost wake-ups are re-armed by `wakeups.sweep`, a sweeper routine with direct
      grants separate from the lease reclaim, for QUEUED runs whose `investigate` jobs and APPROVED runs whose
      `execute` jobs are all done, past a 60 s grace (`OPS_WAKEUP_GRACE_SECONDS`) and below a 10-claim cap
      (`OPS_WAKEUP_MAX_ATTEMPTS`), never for a run whose cancellation was requested, with every condition repeated
      on the row the re-arm takes; past the cap it logs instead. A grant refusal the worker takes as final leaves
      its run APPROVED and is therefore re-dispatched up to the cap (moving such a run out of APPROVED is T21's).
      **Trade-off for the owner (final review, M9).** AM-10 says a refused grant moves the run to BLOCKED_REVIEW;
      that is T21's work. Until then the re-arm re-dispatches an APPROVED run whose grant was refused, up to
      `OPS_WAKEUP_MAX_ATTEMPTS` claims (about ten minutes at the defaults). Each dispatch re-runs the full grant
      check (approval, active and freshly synced memberships, no cancellation), so nothing executes under authority
      that is invalid at that moment. In v1 a deactivated membership cannot be reactivated (no admin surface; the
      sync only deactivates), so such a refusal does not clear and the re-dispatch only costs attempts; and the
      GRANT_DEFERRED (stale sync) retries depend on the re-arm. The conservative alternative is to drop the
      `("APPROVED", "execute")` pair from `WAKEUPS` until T21 lands BLOCKED_REVIEW. The owner decides.
  64. BS:340 and the polling debt of Plans E and H: a wake-up is the job committed with its user event, plus the
      sweep; there is no LISTEN/NOTIFY; the worker's 0.5 s per-tenant poll is the v1 wake mechanism, and a lease's
      release makes the jobs deferred behind it due at once (a job delayed beyond the lease's end keeps its time).
  65. SA:452 and AM-80's event schema: `_append_event` refuses (OC006) a payload key outside the event schema's
      thirteen (the schema gains `question_id`, `message_id`, `outbox_id`) and a `status` on any type but the
      destination's four (schema rule 9); `event_rules_ok` mirrors both, on one table of cases.
  66. BS:524 (intent): notification intent is written inside `_append_event`, in the event's transaction, for
      `action.confirmed`, `action.failed`, `action.conflict`, `run.escalated` and `run.abandoned_unverified` (the
      first three are emitted today by `record_outcome`; the last two have no emitter until T22); the recipient is
      the run's requester, the channel `local`, the dedup key `run_id:type:channel:recipient` with a target-less
      `ON CONFLICT DO NOTHING`.
  67. BS:524 (delivery): the sweeper's tick, one tenant after another, claims the tenant's due rows (`FOR UPDATE
      SKIP LOCKED`, a 30 s lease, `OPS_OUTBOX_BATCH` 10), delivers them outside any transaction to `LogSink` (one
      log line, no egress), and records each result in its own unit for the attempt it was claimed at; the backoff
      is `min(300, 2 × 2^(n−1))` s plus up to 25 % jitter; the fifth failure dead-letters; a sink that crashes on a
      row is caught at the sink boundary and counted as that row's failed attempt, sparing its batch, the later
      tenants and the announcements; a delivery lost with its sweeper is retried when its lease ends and
      dead-lettered by the claim once its attempts reached the same cap; no result overwrites a dead letter; the
      wake-up sweep runs before the delivery; `outbox_sink_fail` is the sink's test-profile fault.
  68. SA:188 and BS:514: `notification.failed` (payload `code`, `message`, `outbox_id`) is appended once per dead
      letter in a separate transaction after the result unit, opened by a transaction advisory lock on the outbox id
      and followed by the re-check, so a second sweeper waits for the first and finds the event; every tick re-checks
      the dead letters that lack it.
  69. SA:520: the sweeper iterates `tenants` and runs per-tenant work in one transaction per tenant
      (`ops_sweeper.tenants.for_each_tenant`): the delivery and the wake-up sweep now, T21's expiry and T22's
      deadline escalation later.
  70. SA:504: the `deliver_outbox` and `sweep_wakeups` rows are audit records like `sync_memberships`' (inserted,
      claimed and finished in one transaction per minute; the work runs outside it, and a second tick in the minute
      records nothing new).
  71. SA:188 (extending erratum 52): a third advisory lock, the dead letter's announcement, after the asset guard;
      `_append_event` takes `runs → events → outbox`; the delivery's claim and result units lock `outbox` only;
      `notification.failed` takes its advisory lock, then `runs`, in a unit of its own; the re-arm and the purge lock
      `jobs` at the finish position; the release's pull-forward picks with SKIP LOCKED.
- Earlier debt lines that named T14 and what became of them: the gap-free sequence is proved (walking-skeleton and
  Plan D lines); the outbox and its grant row are done (Plan E); `sweep_wakeups`, `deliver_outbox` and the purge of
  finished maintenance jobs are done (Plan F); lost wake-ups are re-armed by the sweep (Plan H; recover jobs stay
  T22's); a deferred job no longer waits for a released lease (Plan H); polling and per-tenant claims are kept as the
  v1 wake mechanism (erratum 64, Plans E and H); `_idempotent`'s "use a new key" answer for a key that just became
  reusable stays harmless and is on the Plan I debt list for T28.
- Rulings made during execution (test-level or ordering choices, not spec errata; the plan text stays as written):
  - Task 3: the stress run's gathers use `return_exceptions=True` and always release the readers before the purge,
    and `stepped`'s `finally` always settles writer B. Reason: a failing run then reports its real error and never
    cancels a database unit or races the purge, which the plan's own constraints forbid. Cost if wrong: none to
    behaviour; tests only.
  - Task 4: the R024 dedup re-append runs as `app_definer` (`SET LOCAL ROLE`, tenant set), not as the superuser the
    plan text describes. Reason: a replayed `record_outcome` returns at RESOLVED before `_append_event`, so only a
    re-append under the definer's INSERT-only grant and the outbox's forced RLS exercises the target-less
    `ON CONFLICT`; with it removed the test fails on the dedup key. Cost if wrong: none to behaviour.
  - Task 5: a database error in the wake-up sweep skips that tick's delivery; both retry on the next tick (30 s).
    Reason: round 1 required only that delivery never starves the sweep. Cost if wrong: one tick's delayed delivery
    during a database fault.
- **Open items for later** (minors from the SDD ledger
  `.superpowers/sdd/2026-10-15-first-slice-i-journal-wakeups-outbox/progress.md`, parked for the final review):
  - Dead letters are re-scanned every tick per tenant (a `NOT EXISTS` on events, no index on `result = 'dead_letter'`)
    and delivered rows are never purged, so the cost grows with history: retention (T32) or a partial index.
  - Done in the final-review wave: `wakeups.LOST`'s `CASE` is built from `WAKEUPS` (`job_type_case`), pinned by a unit
    test, so a pair added to `WAKEUPS` alone (T20, T22) is no longer silently skipped.
  - The sink boundary logs the exception and traceback unredacted (safe for `LogSink`): a note for T39's real sink.
  - No live test runs `deliver_outbox` through `persistence.tenants` (the unit tests use fakes).
  - Smaller: the tick summary counts results with `recorded=False`; `pull_forward`'s bound cannot tell a deferral from
    a short deliberate delay inside the lease window (an earlier retry only); the R105 leftover check fails on a
    leftover at the attempts cap and misses runs with an open job (errs loud); the newest-job tie-break differs
    between the scan (`created_at`) and the re-arm (strict `done_at`), benign; the catalog test follows only
    `app.x(` calls (complete today); the rollback test settles writer B only when not done; `stepped` waits its full
    5 s when B fails early. (0008's comment naming `SWEEPER_PURGE_QUAL` was corrected in the final-review wave.)
  - From the final review (debt lines; none breaches a v1 boundary): batch delivery order is random, since
    `outbox.CLAIM` picks by `created_at` but returns by `outbox_id`, harmless until T22 emits `run.escalated` beside
    `action.conflict` for one run → T22; the claim's dead-letter UPDATE is a plain multi-row UPDATE, not SKIP LOCKED,
    which matters only with two sweeper instances (v1 runs one, and PostgreSQL resolves a deadlock) → T30;
    `notification.*` is not a reserved event type in `append_event`, so an api or worker caller could append a
    misleading `notification.failed` (reserve it for the sweeper) → T26/T45; no live test runs the real tick's T14
    steps (`main.sweep_wakeups`, `main.deliver_outbox` through `persistence.tenants`), only R105's skeleton sweeper
    does and its failure would only be logged → T30 (R105 could assert a delivered intent meanwhile); T32's plan must
    give some role DELETE on `app.outbox`, ordered before events, before any event retention can run.

## Plan J executed (2026-10-15, branch `plan-j`)

- T15 = `00c76e4..f0c8ca8` (the debt list first, then the four tasks; the close-out is the commit after `f0c8ca8`). The
  plan (`docs/superpowers/plans/2026-10-15-first-slice-j-mcp-read-verifier-handles.md`) holds the 25 rulings of the
  controller's brief as implemented; the input is `docs/superpowers/research/2026-10-15-plan-j-inputs.md`.
  Evidence: `tests/e2e/test_mcp_read_t15_live.py` (R027's handle cases over HTTP, R085 and R131's read half at
  mcp-read, the `mcp_read` ACL, the four protocol-version requests, no handle in any log record),
  `test_mcp_read_process_live.py` (R025's read half and R031's network half: a child process and the official
  client; R026: three foreign tokens refused with 401), `test_migration_0009_live.py` (the round trip and the startup
  check against 0008, the job binding at the definer, the run-state rule) and `reports/mcp-read/`; the unit half is
  in `tests/plan_j/`. R105's replay step now expects the refusal of a fresh handle for a finished execute job, and the
  R006 populated upgrade asserts its migrated finished job's refusal before reopening it.
- Gates: `check.py` 1071 passed / 164 skipped; `check.py --profile test` 1214 passed / 21
  skipped; `verify_handoff.py` exit 0 (STATUS.md, "Update — Plan J executed"). After the final-review fix wave:
  `check.py` 1075 passed / 164 skipped; `check.py --profile test` 1218 passed / 21 skipped; `verify_handoff.py` exit 0.
- **Proposed errata (the owner decides; the spec text stays authoritative until then).** Numbered on from Plan I's
  seventy-one:
  72. R131 and SA:400/SA:459 (`mcp_read`'s functions): `mcp_read` holds EXECUTE on `current_time` (erratum 15) and
      `resolve_invocation` and on nothing else in `app`; `asset_scope` arrives with T16 and
      `search_procedures_scoped` with T17/T16, each in its owner's revision (Plan E ruling 1: no definer without a
      caller), so R131's three-function set is the target, not today's.
  73. SA:571-572 and BS:378 (per-request version): both MCP servers mount `ops_core.mcp_protocol.
      ProtocolVersionGuard` before the SDK app: a POST to `/mcp` without exactly one `MCP-Protocol-Version:
      2026-07-28` header is answered HTTP 400 with the constant JSON-RPC error `-32022` "Unsupported protocol
      version" (`id` null, the supported version listed, nothing echoed) before authentication, so the SDK's legacy
      stateless path is closed and an unauthenticated client learns only the version rule; a header/`_meta`
      disagreement is the SDK's own `HEADER_MISMATCH` (400, `-32020`).
  74. SA:557 (the verifier): mcp-read also requires the access token's `typ` claim `Bearer`; its SDK adapter
      (`McpVerifier`) refuses a token whose `aud` lacks the server's resource URL and only then sets the SDK's
      `AccessToken.resource` to that URL; the SDK's `validate_token_resource` is on as a second layer, which cannot
      refuse while the stamp is the server's own URL; every token refusal stays HTTP 401 (Plan D ruling 25); mcp-write
      follows in T47.
  75. SA:459 and SA:496 (the handle's binding): `_resolve_handle` resolves a handle only when its `job_id` names a
      job of the handle's own run that is not finished (`done_at IS NULL`); otherwise it refuses `OC008` like every
      other refusal (revision 0009).
  76. SA:338 and T15 review note 2 (the allowlist): `persistence.allowed_tool(job_type, run_state, tool)` checks the job
      type's tools and run states at the start of every MCP call (`persistence.resolve_invocation`; the definers' own
      resolutions inside `grant_execution`, `mark_sent`, `record_outcome` and `lookup_action` do not apply it, since
      `record_outcome` must answer after the run moved); the attempt-state dimension (`create_incident` only while the
      attempt is absent or INTENT, not cancelled, before the deadline) is mcp-write's, in `execution.next_step` today
      and in its allowlist with T47.
  77. SA:459 (the `resolve_invocation` row as amended): the only lock is `run_lease FOR SHARE` (erratum 53); it
      returns `run_id, job_id, job_type, tenant_id, conversation_id, run_state, attempt_state` (erratum 19); it
      binds the handle as erratum 75 says.
  78. SA:34 (AM-00 §9): the `ops-mcp` audience and "distinct service scope" wording is replaced by AM-20.7 item 6
      (the resource-URL audiences), not by AM-20.6 (the test clock).
  79. BS:360 ("Refresh it only while the lease is current"): there is no refresh; a handle is minted per call under
      the lease, lives 60 s, and is bound at use to the lease's fence and liveness (erratum 58).
  80. SA:460-461 with SA:176-184 (reads and the fence): a read tool is served after the handle resolved in its own
      committed unit; a fence that moves during the read cannot cause a write, and the worker's next fenced unit
      fails.
  81. SA:558 (the three token tests): the missing-`aud` and browser-token cases are synthetic-key unit tests at
      mcp-read's configuration (`azp=ops-web`, no `aud`); live, a persona token (aud `ops-api`) stands in for a
      browser token, because no `ops-web` access token is minted anywhere (the API stores none, erratum 31, and
      minting one needs the client secret).
- Earlier debt lines that named T15 and what became of them: the raw, unhashed handle (walking skeleton) was done by
  Plan E (revision 0002); "handles are not revoked at job end" was done by Plan H (`release_lease`); "resolution
  ignores run and attempt state" is half done (the run state, Task 2) and half re-homed (the attempt state → T47);
  Plan D's "the same `INVALID_HANDLE` for every rejection" is kept on purpose (SA:357, ruling 13); Plan E's
  `asset_scope` and `search_procedures_scoped` ("T15/T16/T17") now name T16 and T17/T16; Plan E's untested "write
  handle at mcp_read" (re-homed to T22 by Plan H) is now tested over HTTP (Task 3); Plan D's silent excerpt
  truncation stays with the tool's contract (T16).
- Rulings made during execution: none beyond the plan. Each of the four tasks followed its brief verbatim, had one
  review (clean: Minor findings only) and needed no fix round; the live halves of Tasks 1-4 passed on their first run.
- **Open items for later** (Minor findings the task reviews deferred; none changes a verdict; the ones marked "fix"
  were fixed in the final-review wave, see "Final review" below):
  - fix: pin that `POST /mcp/` without the version header is not 200 (the guard's `path` default and the SDK's
    `streamable_http_path` are separate literals; the review probed `/mcp`, `/mcp/`, `/mcp/x`, `/MCP`, `//mcp`,
    `%6Dcp` and non-POST methods and found no bypass);
  - fix: mcp-write's startup check asks only for `app.model_permit`; add `assert_function_text(conn, *HANDLE_BINDING)`
    so it also refuses a database without 0009 (the binding applies to both servers);
  - fix: `test_mcp_read_t15_live.py`: the DEBUG log test checks the handle only (add the worker token to its
    "carrying" check and assert no `RedactingFilter` sits on `caplog.handler`); the lying-column `UPDATE` asserts no
    row count (lines 230-234); the recover and execute handle refusals have no positive control in the same test;
  - fix: `test_mcp_read_process_live.py`: the child-log leak check covers the handle only (add the worker token, and
    read the child log in the R026 test for the three foreign tokens); the evidence line should say "R025 (read half;
    mcp-write with T47) / R031 (network half)" and interpolate `PROTOCOL_VERSION`; `response.headers["www-authenticate"]`
    should be `.get(..., "")`; start-failure messages should name the child log's path (not its content);
  - `tests/plan_j/test_verifier_t15.py:67,73` put an `AccessToken` repr holding a synthetic JWT in an assert operand
    (plan-mandated; synthetic key only); `test_mcp_read_http.py:8`'s docstring cites a live module created later;
  - the newest-body guard for `_resolve_handle` finds re-creations only through a `FUNCTIONS` attribute (a
    convention); the live tests create runs and tokens before their `try` (a purge gap on a failed set-up; the test
    database is dropped per session); wording: "13 others refused" means `has_function_privilege` is false, the R027
    docstring's "the same handle answers again" holds only until the lapsed lease, and the evidence record count varies
    run to run (119 vs 137); `free_port()` races and the child's failed-start and kill paths were verified by reading
    only.
- **Final review** (whole branch `00c76e4..8424ed7`; record
  `.superpowers/sdd/2026-10-15-first-slice-j-mcp-read-verifier-handles/final-review.md`): ready with fixes; 0 Critical,
  1 Important, 7 Minor. The Important: mcp-write's startup did not check revision 0009, though the README and erratum
  75 claimed the binding for both servers. The auth, binding, guard and secrets checks held. One fix wave:
  `persistence.HANDLE_BINDING` in `core` (mcp-read re-exports it), mcp-write's startup checks it (unit test both ways;
  the live round trip has `mcp_exec` refuse at 0008 and pass at the head); the lying-column update asserts one row and
  each write-handle refusal has a positive control at `mcp_exec`; the log tests check the worker's token too, R026
  reads the child log for the foreign tokens, and the DEBUG test asserts no `RedactingFilter` on caplog's handler; one
  `MCP_PATH` constant, and `POST /mcp/` without the header pinned to the router's 307; the R025/R031 evidence line
  names its halves; R026's evidence adds the R105 skeleton (persona and mcp-read tokens refused live at mcp-write) and
  R027's adds `test_definers_write_path_live.py`; the mcp-write README's replay wording matches `execution.py`; the
  PR records say #1-#8. Two debt lines went to T47 (the Plan J debt list). T15's DONE depends on the owner's
  decisions on errata 72 and 76. Deferred minors stay as listed above (T1-b, T2-b, T3-e, T3-f, T4-e, T5-c; of T3-f, the R027 docstring was fixed).

## Plan K executed (2026-10-16, branch `plan-k`)

- T47 = `dd9f7b1..ea0bf54` (the debt list first, then the five building tasks; the close-out is the commit after `ea0bf54`). The
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
  exit 0 (STATUS.md, "Update — Plan K executed"). After the final-review fix wave: 1161 passed / 182 skipped and
  1322 passed / 21 skipped (measured), `verify_handoff.py` exit 0.
- Final whole-branch review: ready with fixes (0 Critical, 1 Important, 1 Minor), fixed in one wave after `6ec740f`.
  The Important (I1): a re-queued execute job that met ABORT_REQUESTED (an abort requested, then mcp-write failed
  before the record) was refused, so the worker closed the job and the run stayed EXECUTING with no job; the execute
  row now admits ABORT_REQUESTED, the call answers UNKNOWN with no destination call, and the worker's `mark_unknown`
  parks the run in OUTCOME_UNKNOWN with a recover job (erratum 84 amended). The Minor (M1): four sentences in the
  threat model, mcp-write's README and PROJECT_HISTORY said more than the code. Nine deferred task minors were fixed
  in the same wave (PROJECT_HISTORY §28); five stay open (below).
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
      states (errata 19 and 76); `execute`/`create_incident`: no attempt, INTENT, SENT or ABORT_REQUESTED (SA:344
      gains SENT: the re-queued job re-sends the same action id after a lost reply, still not cancelled and before the
      deadline, re-checked by `mark_sent`; and ABORT_REQUESTED: a job re-queued after mcp-write failed between the
      abort request and its record is answered UNKNOWN with no destination call, so the worker's `mark_unknown` parks
      the run in OUTCOME_UNKNOWN with a recover job instead of the refusal closing the job, final review I1);
      `recover`/`create_incident`: INTENT only (SA:345 over SA:334; `mark_sent` also refuses a recover job's re-send
      under the lock, `not_redispatchable`); `recover`/`get_incident_receipt`: SENT,
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
- Rulings made during execution:
  - Task 2's two substantive evidence diffs under `reports/` (R131's "14 others" and an Ollama version line) were
    reverted at once, so no later task could commit them by accident; this close-out's live run regenerates the
    evidence.
  - Task 4 had one fix round (`28d3f0b`, test-only): the R030 test also pins that refusals make no destination call and
    that a lookup writes no destination key, the deadline test asserts the clock reset, and the evidence lines name
    `mark_unknown` 42501 and state that around a rate-limited abort the counts are unchanged and only the tombstone is
    added. The clock is read through `app_conn` because the test harness cannot SELECT `test_clock` (AM-20.2).
  - Task 4's fix round was re-reviewed by the controller reading its 25-line, test-only diff, not by a second review
    task: every item was addressed and the change touched no production code. If that was too light, the final
    review is where it shows.
  - The live gate counts of Tasks 2 to 5 were measured, not computed: 1251, 1300, 1310 and 1311 passed, each with 21
    skipped.
  - `reports/mcp-read/t15-mcp-read.txt` is committed with its new R131 line (14 other functions refused, not 13:
    `request_abort` is a new definer `mcp_read` must not execute); every other rewritten `reports/` file under
    `bootstrap`, `auth` and `mcp-read` is reverted.
  - `docs/runbooks/mcp-write.md` says never to downgrade past 0010 while an `ABORT_REQUESTED` row exists (0009's
    `mark_sent` would not honour it); `docs/threat-model.md` says the worker has no client code and no credential for
    incident-sim (network isolation is T30's) and that only `sent` or `already_sent` from `mark_sent` lead to the
    incident POST (`cancelled` and `expired` lead to the abort POST; final review M1).
- **Open items for later:** minors the final review left deferred (the final-review fix wave took the other nine):
  no end-to-end environment test of `production_app`'s `azp` (each construction point is tested); `OTHER_PROPOSAL`
  surfaces as `GRANT_REFUSED` text (cosmetic; erratum 89 and the runbook say so); the T47 live module's setup before
  `try` can leak runs on a Keycloak hiccup (the counts are diffed; Plan J's precedent); the inherited `free_port` race
  and the start loop without a timeout; the process test's evidence path is relative to the working directory (the
  gates run from the root). Not deferred but owned elsewhere: the network half of T47 DoD 3 and per-service tests
  (T30), the worker's recover handler and everything after it (T22), the deadline as a setting (T29), signed receipts
  (v1.1).

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

## Plan G debt list (T12; committed before coding) [R6-B7]

Allowed shortcuts in T12, each with its owning task:
- the global queued-work bound (BS:550 "100 total") is not enforced: `api` can count only its own tenant's runs and
  cannot read `jobs` (Plan G spike §8); a per-tenant quota of QUEUED runs (`OPS_TENANT_QUEUE_QUOTA`) stands in → T13;
- no producer of a model hint exists: the admission router takes `hint` and the API passes `None` → T19;
- the 202 body carries no `stream_url` until the stream route exists → T27;
- the worker finishes a `resume_input` job unhandled and ends an `answer_only` run FAILED (no ANSWERED path yet), so
  the clarification reply and the read-only admission are proved at the API boundary only → T20 (R042, R114);
- nothing in the worker asks for clarification yet, so the live test stages `AWAITING_INPUT` through the worker
  role's `transition_run` → T20;
- the API reads the active run without a lock before a clarification or a status answer: a concurrent
  `investigate` may take the slot between the read and a stored clarification, which the reply then meets as a 409
  (benign; `api` can lock neither `conversations` nor an absent run) → T21, which owns the slot's other doors;
- `api` may INSERT any job type (the column grant cannot restrict `type`, Plan G spike §2); the API inserts
  `resume_input` only, by code → T13/T22;
- the dev database stays at revision 0005 until the owner migrates it to 0006; until then the API and the sweeper
  refuse to start on it → owner input;
- `feedback` (named for T12 in `privileges.py` and the Plan E debt list) is not created: its endpoint (BS:282) is in
  T21's instructions → T21;
- the clarify, status-answer and accepted bodies have no JSON Schema under `schemas/` (no response has one yet) → T26;
- the API's fault route implements `drop_before_commit` only; the other BS:405 faults, `lose_after_commit` included
  (R015's after-commit side is proved meanwhile by R016's replay of the recorded 202) → T13.

## Plan H debt list (T13; committed before coding) [R6-B7]

Allowed shortcuts in T13, each with its owning task:
- the model permit is released when the draft call ends or is cancelled, and by its 65 s TTL; SA:205's "hold the
  permit until `ollama ps` shows idle" waits on T02's cancellation measurement, and today's only route is the fake
  drafter → T19;
- the heartbeat's 90 s compute gate counts one lease's hold time; accounting into `runs.budget_used` across jobs, the
  human-wait exclusion (BS:556) and R062's caps → T29;
- the execute job's transport-failure and `GRANT_DEFERRED` re-queues have no retry bound (the run is APPROVED or
  EXECUTING, which the worker may not move, SA:451) → T22;
- the worker's transport failure still re-queues instead of taking AM-13's timeout path (`mark_unknown` on a
  transport timeout, R109; erratum 14 stands) → T22;
- the reclaim inserts no `recover` job and lost wake-ups are not re-enqueued → T22 (recover), T14 (wake-ups);
- a deferred job waits for the busy lease's `lease_until` even when the holder releases early (no wake-up on
  release) → T14;
- a handler that crashes (an exception other than a lease loss) keeps its job claimed until its lease lapses and the
  sweeper reclaims it, and then runs again without a bound → T22;
- an investigate run interrupted in RETRIEVING or DRAFTING (a lost lease, a crash, a lock timeout) is failed by its
  job's next owner (`interrupted; the run was not resumed`) instead of resumed from where it stopped → T20 (the
  graph's node resume);
- the asset-guard advisory lock is placed in the lock order and proved callable by `app_definer`, but
  `freeze_proposal` and `grant_execution` do not take it yet → T21;
- checkpoints are untouched (`runs.checkpoint_id` under the fence) → T20; fenced `put`/`put_writes` (R021) → T38;
- one active compute lease per requester (BS:548) is not enforced (one worker replica runs one job at a time) → T29;
- no connection pool and no reconnect except the heartbeat's connection; a lost loop connection still ends the
  process; the API reply unit's per-unit `lock_timeout` → T30;
- `api` may still INSERT a job of any of the eight types (the CHECK bounds the vocabulary, not the role) → T22;
- the global queue bound is soft by the number of concurrent admissions (counted, then created, across tenants) →
  T29;
- mcp-write handles the five new incident-sim faults only through today's `classify` (rate limit, timeout and a
  malformed body become UNKNOWN, a foreign receipt hash CONFLICT, a hidden receipt a 404 on lookup) → T22/T47;
- the shared connect-and-assert helper for the servers, a closer that raises during startup cleanup and the token
  verifier's injected-fetch exception → T30; the untested definer branches (Plan E list) → T22; the pre-SENT
  `STALE_RUN`/`HASH_MISMATCH` envelopes → T47;
- the worker still polls every 0.5 s and claims per tenant → T14 (wake-ups);
- (struck in execution, erratum 58) a handle's expiry was to be capped at the lease's end at mint, living 20-30 s in
  practice; instead the expiry is mint time + 60 s and the bound by the current lease is enforced at use, so a
  renewal keeps a handle usable and nothing is owed;
- the global queue count costs one scan per tenant inside every run admission → T29;
- the dev database stays at revision 0005 until the owner migrates it (0006 and 0007 pending); until then the API,
  the sweeper, the worker and mcp-write refuse to start on it → owner input;
- (added by the final review, M2) SIGTERM is not drained: uvicorn 0.54 re-raises it after the health server shuts
  down, so the worker ends mid-job; the open unit rolls back, the lease lapses and the sweeper hands the job back,
  and an investigate run is failed as interrupted (SIGINT lets the job finish) → T30;
- (added by the final review, M3) the wait for the model permit counts against the 90 s compute budget, because the
  budget runs from the claim; with more than one worker on one model, a run queued behind another worker's draft can
  lose its lease to "compute budget spent" and be failed as interrupted → T29;
- (added by the final review, M7) a lost lease is visible only in the worker's logs: a loss, a crash, a lock timeout
  and a spent budget all end as the same FAILED reason, and no run event, distinct reason or metric records a loss or
  a reclaim → T28.

## Plan I debt list (T14; committed before coding) [R6-B7]

Allowed shortcuts in T14, each with its owning task:
- the worker still finishes a `resume_input` job it does not handle, and the wake-up sweep does not look at
  AWAITING_INPUT runs (no handler consumes the reply yet) → T20;
- the worker still finishes a `recover` job it does not handle, and OUTCOME_UNKNOWN and ESCALATED runs are not swept
  (the recover cadence of SA:506 included) → T22;
- the wake-up sweep re-arms the `investigate` job of a run that sits in QUEUED with every investigate job done; a run
  that T20's `resume_input` handler moves back to QUEUED would meet the same predicate, so T20 decides whether that is
  its wake-up → T20;
- the decision-to-processing crash test of R023 (inject a crash between decision, event, checkpoint and job
  acknowledgement; the sweeper resumes exactly the accepted event) → T21;
- `outcomes.Event` validates neither `append_event`'s input (the function assigns id, sequence and instant) nor the
  events route's output → T26 (response schemas);
- SSE, `Last-Event-ID` replay and the cursor-expiry reset (R053, BS:518's 200-event page) → T27; the events route
  keeps `after`/`limit ≤ 500` → T26/T27;
- no event and no outbox row is ever deleted (BS:578's 30-day replay, the outbox's delivered and dead-lettered rows)
  → T32;
- the only sink is `LogSink` (one log line per delivery, no egress); recipient mapping from approved identities,
  per-channel redaction and a destination's own deduplication → T39 (Slack, M15);
- a delivery slower than the 30 s outbox lease can be delivered twice (at-least-once, BS:76), and so can a delivery
  whose result unit fails after the sink succeeded → T39 (a real channel's deduplication);
- `run.escalated` and `run.abandoned_unverified` are notification triggers with no emitter yet (`escalate_run` and
  `resolve_escalation` do not exist); today a run escalates only through `record_outcome`'s CONFLICT, whose
  `action.conflict` is a trigger → T22;
- a grant refusal the execute handler takes as final (an inactive membership, a missing approval) finishes the job
  and leaves the run APPROVED, so the wake-up sweep re-dispatches it until the job has been claimed
  `OPS_WAKEUP_MAX_ATTEMPTS` times; moving such a run out of APPROVED (BLOCKED_REVIEW, AM-10) so the sweep stops → T21;
- `_idempotent`'s "not reusable yet" refusal tells the client to use a new key for a key that just became reusable
  (harmless; moved from the Plan G line that named T14/T28) → T28;
- operator visibility of a dead letter is the `notification.failed` event plus a log line; a wake-up past its re-arm
  cap is a log line once per tick; dashboards and metrics → T28/T29;
- `_append_event` bounds the payload's keys and `status`, not its size (BS:514 "bounded safe payload") → T45;
- added by the final review: batch delivery order inside a claim is random (T22); the claim's dead-letter UPDATE is not
  SKIP LOCKED, which matters only with two sweepers (T30); `notification.*` is not a reserved type in `append_event`
  (T26/T45); no live test runs the real tick's T14 steps (T30);
- incident-sim's fault route accepts any `FaultKind`, so `outbox_sink_fail` can be armed there and is never consumed
  → T47;
- the dev database stays at revision 0005 until the owner migrates it (0006, 0007 and 0008 pending); until then the
  API, the sweeper, the worker and mcp-write refuse to start on it → owner input.

## Plan J debt list (T15; committed before coding) [R6-B7]

Allowed shortcuts in T15, each with its owning task:
- mcp-write's verifier keeps stamping its own resource whatever `aud` holds, leaves `validate_token_resource` off and
  does not require the `typ` claim `Bearer` (mcp-read does all three, Plan J ruling 2) → T47;
- the write-path definers (`grant_execution`, `lookup_action`, `mark_sent`, `record_outcome`) call `_resolve_handle`
  with a literal `'ops-worker'` instead of the presented token's `azp` (`resolve_invocation` compares the real one
  first, so a mismatch is refused there) → T47;
- the attempt-state dimension of the allowlist (`create_incident` only while the attempt is absent or INTENT, not
  cancelled, before the deadline; T15 review note 2) stays in mcp-write's `execution.next_step` → T47 (recover: T22);
- mcp-write's half of R025 (an independent client lists and calls mcp-write) and of R131 (`mcp_exec`'s function set, a
  read handle at mcp-write) → T47;
- `asset_scope`, `get_asset_status`, `get_recent_alerts` and asset-sim → T16; `search_procedures_scoped`, the governed
  store and the `vector_exact` → `mode=vector` translation by its caller → T17/T16; `search_procedures` stays lexical
  over `data/handoff-fixtures/` (Plan J rulings 8, 9);
- mcp-read's tool arguments (the optional `asset_type`), the order of its `UNSUPPORTED_MODE` check and its fallback
  `corpus_version` → T16/T17 (ruling 20);
- the worker's client does no tool discovery and no result-schema check (R029) → T16; it does not tell a 401 from
  other transport failures (both become "retrieval failed" or a re-queue) → T20; it holds no `resume_input` handle →
  T20;
- TLS outside localhost, and container host names (the SDK's DNS-rebinding allowed hosts; audience URLs that equal the
  listen URLs) → T30 (ruling 16);
- mcp-read has no `tests/` directory and no Dockerfile of its own (AM-01) → T30 (ruling 25);
- the dev database stays at revision 0005 until the owner migrates it (0006, 0007, 0008 and 0009 pending); until then
  the API, the sweeper, the worker, mcp-write and now mcp-read refuse to start on it → owner input;
- added by the final review: no test drives the EXECUTING re-queue's re-send through mcp-write over HTTP (the tool
  path's only production replay is covered in two halves: the allowlist table's (EXECUTE, EXECUTING,
  CREATE_INCIDENT) row and `GrantThenDownMcp`, which skips `resolve_invocation`); T47's DoD gains "a live
  `create_incident` through mcp-write over HTTP with a fresh handle for the re-queued execute job of an EXECUTING run
  returns the same `action_id` and no second incident" → T47;
- added by the final review: renaming the worker's client touches four places; the mint follows the token source
  (`tests/plan_j/test_worker_azp.py`), but `main.py`'s token source (`client_id="ops-worker"`), `read_verifier`'s
  `allowed_azp` and the write-path definers' literal `'ops-worker'` still name it; settings should name the worker
  client once → T47.

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

## Plan L debt list (T17; committed before coding) [R6-B7]

Allowed shortcuts in T17, each with its owning task:
- vector retrieval: the `embeddings` table, the nomic-embed-text `search_document:`/`search_query:` embeddings, the
  `mode = 'vector'` branch of `search_procedures_scoped` (refused `VECTOR_MODE_UNAVAILABLE` until then), tuning the
  minimum rank (0.25, chosen on the development queries; `ts_rank_cd` is unnormalised, so it depends on query
  length), and the evaluation of another chunk window than one per section → T18 (Plan L rulings
  2, 4 and 18); mcp-read's `vector_exact` → `mode=vector` translation (until then `UNSUPPORTED_MODE` before the
  database) → T16;
- `asset_scope`, the asset tools, asset-sim serving `data/corpus/assets.json`, and the run's own asset type passed to
  the search (the tool takes `asset_type` from its caller only) → T16 (ruling 11);
- the requester's current membership re-checked at read time (R028) → T16 (ruling 10);
- the final grant's recheck that every cited source version is still approved and effective (BS:425, R045) → T21;
  revoked text kept out of checkpoints, summaries and events (R035) → T26 (ruling 22);
- the model-side proof that the injected documents grant nothing (R036), and detecting the conflicting pair and
  abstaining → T19/T20 (rulings 13 and 14);
- the excerpt is still cut silently at 500 characters (Plan D's open item) → T16;
- shared (cross-tenant) documents: none; a document both tenants need is copied per tenant → no task (erratum 97,
  ruling 9);
- the dev database stays at revision 0010 with no corpus until the owner runs `scripts/skeleton.py migrate` and then
  `scripts/skeleton.py ingest`; until the migration mcp-read refuses to start on it (it checks 0011) → owner input
  (ruling 24).

## Environment (observed)

| Item | Observed |
|---|---|
| OS | Windows 11 Home 10.0.26200 |
| CPU / RAM | Ryzen 9 5900X / 31.9 GB |
| GPU | RTX 3080 (10 GB) |
| Python | 3.13.7 (`python`), 3.14.6 (`py`) |
| uv | 0.11.8 |
| Docker | Docker Desktop 29.6.2 |
| Ollama | Observed at 0.40.4 on 2026-10-15 (recorded 0.33.3 before; Plan J did not change it, and per AM-30 an upgrade is the owner's decision, so this records the observation and claims nothing either way); `qwen3:8b` and `nomic-embed-text` installed as last recorded |
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

**Update (2026-10-10):** Plan G adds revision 0006. The dev `ops` database stays at 0005 until the owner runs
`uv run python scripts/skeleton.py migrate` (dev profile); until then `skeleton.py up` fails fast because the API
and the sweeper refuse to start without `app.idempotency_request`. The upgrade adds the table, numbers the existing
messages through the new identity column and changes no row.

**Update (2026-10-15):** Plan H adds revision 0007. The dev `ops` database stays at 0005 until the owner runs
`uv run python scripts/skeleton.py migrate` (dev profile), which applies 0006 and 0007 together; until then
`skeleton.py up` fails fast because the API, the sweeper, the worker and mcp-write refuse to start without their
revision's relation. 0007 creates `app.model_permit` (one seeded slot), adds the `jobs.type` CHECK (every existing job
has one of the eight types), grants `app_definer` UPDATE on `run_lease.fence`, and re-creates the handle functions
with the fence check; it deletes nothing.

**Update (2026-10-15):** Plan I adds revision 0008. The dev `ops` database stays at 0005 until the owner runs
`uv run python scripts/skeleton.py migrate` (dev profile), which applies 0006, 0007 and 0008 together; until then the
sweeper also refuses to start (it needs `app.outbox`). 0008 creates `app.outbox` (empty), gives the sweeper DELETE on
`jobs`, and re-creates `_append_event` with the payload rules and the notification intent; every event the dev
database holds was written under the old rules and stays as it is (the rules apply to new events); it deletes nothing.

**Update (2026-10-15):** Plan J adds revision 0009. The dev `ops` database stays at 0005 until the owner runs
`uv run python scripts/skeleton.py migrate` (dev profile), which applies 0006, 0007, 0008 and 0009 together; until then
mcp-read also refuses to start (it checks that `_resolve_handle` carries 0009's job binding; mcp-write makes the same
check since the final-review fix wave). 0009 re-creates
`app._resolve_handle` only; every handle in the dev database is long expired, and it changes no row.

**Update (2026-10-16):** Plan K adds revision 0010. The dev `ops` database stays at 0005 until the owner runs
`uv run python scripts/skeleton.py migrate` (dev profile), which applies 0006 to 0010 together; until then mcp-write
also refuses to start without 0010 (it checks `app.request_abort(text, text, uuid)`). 0010 drops and re-creates
`grant_execution`, `lookup_action`, `mark_sent` and `record_outcome` with the token's `azp` as a second argument,
creates `request_abort` and the helper `_dispatch_seconds()`, and changes no row.

**Update (2026-10-16, later):** the owner ran `uv run python scripts/skeleton.py migrate` (dev profile: `app at
app@head, incident at head`), so the dev `ops` database is at `0010_write_path`. `skeleton.py up` then brought all six
processes to ready (mcp-write's startup check needs 0010) and `down` stopped them.

## Open owner inputs

- Decide errata 35-44 (see "Plan G executed"), 45-59 (see "Plan H executed"), 60-71 (see
  "Plan I executed"), 72-81 (see "Plan J executed") and 82-92 (see "Plan K executed").
- R025 and R031 have every half evidenced (mcp-read by T15, mcp-write by T47, the import half by T04) but keep
  `NOT_IMPLEMENTED_OR_NOT_TARGET_VERIFIED`, because no open task owns them: flipping their status is the owner's call
  (or T15's re-close).
- Merge the stacked PRs #1-#10 in order (plan-b -> main through plan-k -> plan-j, all open; #1-#5 opened 2026-10-09 and green on CI; the first merge also exercises the push-to-main trigger).
- Decide on the nine proposed contract errata (see "Plan C executed").
- T03: the owner writes about 25 holdout case intents without AI help, keeps them off-machine, and records the seal hash externally before T02.
- T06 is closed (public repo, PRs green). The first CI runs were red on ruff EXE001 (a shebang on a non-executable file, a rule ruff skips on Windows) with every test green; fixed by a file-mode commit on each branch.
- T44 step 10: step A was applied on 2026-10-16 (see the runbook's attestation row: listener on 127.0.0.1 only, the container test passes, port closed on this host's own non-loopback addresses). Still the owner's: the LAN check from another device, disabling the allow-any `ollama.exe` firewall rules (elevated), and whether to adopt the proposed AM-31 errata (loopback bind primary, firewall fallback).

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

Then wait for the owner inputs above (holdout seal, then live probe; merging the PRs; the Ollama runbook's other-device LAN check; the proposed errata of Plans C-K, up to 92) and write Plan L for T17 (the governed corpus and lexical baseline, the earliest dependency-satisfied PLANNED task in `handoff/tasks.json` after T47, unblocked by T09).

Do not store secrets or private reasoning in this file.

# Session state

**Specification:** OPS-BUILD-1.3.6 (`BUILD_SPEC.md` + `SPEC_AMENDMENTS.md`)
**Current milestone:** M06 (vector retrieval; T18 is DONE in Plan N, and T41, the owner's holdout labels, is its open task. M05 closed with T16 in Plan M. Every task of M00 to M05 is DONE or DONE_PENDING_OWNER, and the owner steps of M00 and M01 are listed below)
**Next task:** T19 (Plan P, branch `plan-p` from `main` 3905b35). PRs #12-#14 are merged. Erratum 114 (the owner's
decision, 2026-10-21) removed the holdout seal as a gate: T19 no longer waits on T03 and T25 no longer on T41. The
agent ran T02's live probe on 2026-10-24 at the owner's instruction (`reports/model-probe-qwen3-8b.md`,
`data/model-pins.json`; schema-valid 5/60, diagnosed in the report; its decision lines are provisional), and the owner
chose to go ahead past T44 step 10 with it pending. The Plan O record follows.
**Plan O record:** Plan O (T23) is executed on branch `plan-o` (`e91b27b..80da1f2` holds the debt list and the four
building tasks; the close-out is the commit after `80da1f2`). T23 is DONE: R111 is evidenced (`evals/dev/cases.jsonl`,
`core/src/ops_core/grading.py`, `evals/dev/RUBRIC.md`) subject to erratum 112; errata 112-113 are proposed; the
numeric-token debt is closed as a measurement (`reports/retrieval/t23-numeric-tokens.md`: lexical 5/6 numeric queries
against 6/6 controls with pair P06 lost but confounded, vector 6/6; the loss is not total, so the search is
unchanged). Owner inputs
added by Plan O: decide errata 112-113; fill in `evals/quality-gates.json` before the first holdout run (SA:672); merge
PR #14 (`plan-o` -> `plan-n`, https://github.com/jschnepel/MLOps/pull/14; final review record
`docs/reviews/plan-o-final-review-2026-10-19.md`, fix wave 1abef84) after #12 and #13. No PLANNED task can start now. T19 and T41 are the only two whose dependencies are all DONE or
DONE_PENDING_OWNER, and each waits on an owner step: T19 on the probe of T02, the seal of T03 and step 10 of T44, T41
on the owner's gold labels for the sealed holdout. T20 waits on T19, T21 on T20, T22 on T21, T24 on T22, and T25 on
T22 and T41. The Plan N record follows.
**Plan N record:** Plan N (T18) is executed on branch `plan-n` (`4c99f14..799beda` holds the debt list and the seven
building tasks; the close-out is the commit after `799beda`). T18 is DONE: R034 is evidenced
(`reports/retrieval-comparison.md`); errata 107-111 are proposed. The dev database was migrated to 0013 and
embedded on 2026-10-19 (run by the agent at the owner's request). Owner inputs added by Plan N: decide the proposed errata
(now 1-111); the installed Ollama 0.40.4 against SA:587's 0.33.3 (the pin records 0.40.4); merge PR #13 (`plan-n` ->
`plan-m`, https://github.com/jschnepel/MLOps/pull/13; final review record
`docs/reviews/plan-n-final-review-2026-10-19.md`, fix wave 1d71485), after #12. Still pending from Plan M: merging PR #12 (`plan-m` -> `main`). T23 followed in Plan O (above).
The Plan M record follows.
**Plan M record:** Plan M (T16) is executed on branch `plan-m` (from `main`: `9e7d716..bbaba40` holds the debt list and the
six building tasks, and the close-out is the commit after `bbaba40`). T16 is DONE: R028 and R029 are evidenced; R131's
read half is complete subject to the owner's decisions on errata 96 and 104. Owner inputs: (1) the holdout seal (T03
step 9), then the live probe (T02); (2) T44 step 10 (step A applied 2026-10-16; the other-device LAN check and the
firewall rules remain) (`docs/runbooks/ollama-network.md` step A); (3) decide the proposed errata of Plans C, E, F,
G, H, I, J, K, L and M (errata 1-106; M: 103-106 below); (4) migrate the dev database to revision 0012
(`uv run python scripts/skeleton.py migrate`, dev profile: it creates `app.asset_scope` and re-creates
`app.search_procedures_scoped`, changing no row); until then mcp-read refuses to start on it; (5) merge PR #12 (`plan-m` -> `main`,
https://github.com/jschnepel/MLOps/pull/12; final review record `docs/reviews/plan-m-final-review-2026-10-18.md`,
fix wave 71753ab). Next is T18 (vector retrieval; it now also owns mcp-read's vector mode)
or T23, both unblocked; T19 and T41 wait on owner steps, and T20 waits on T19. A proposed erratum awaiting the
owner's decision does not change a task's status; a task met "subject to" an erratum stays DONE.
**Plan A outcome:** executed on branch `plan-a` (a638801..HEAD); `scripts/check.py` GREEN (54 passed, 1 skipped: owner seal). Final whole-branch review: 5 Important findings fixed in the final-review wave; minors deferred: M3 timing restructure (`astream`), M6 mypy member list.
**Repository:** local git repo at `C:\Users\joeys\Desktop\MLOps`, branch `plan-o` off `plan-n` (Plan O executed, pushed 2026-10-20, PR #14 into `plan-n`; `plan-n`: Plan N executed, pushed 2026-10-19, PR #13 into `plan-m`; `plan-m`: Plan M executed, pushed 2026-10-18, PR #12 into `main`; `main` 66d6833 has the same tree as `plan-l`, which sat on `plan-k`, on `plan-j`, on `plan-i`, on `plan-h`, on `plan-g`, on `plan-f`, on `plan-e`, on `plan-d`, on `plan-c`, on `plan-b`, on `plan-a`). Remote `github.com/jschnepel/MLOps` (public, MIT) exists; `main` and `plan-a` were pushed on 2026-10-07. `plan-b` to `plan-e` were pushed on 2026-10-08 and `plan-f` on 2026-10-09; `plan-g`, `plan-h` and `plan-i` are pushed too, and every pushed branch matches its local one (checked 2026-10-15). PRs #1-#5 were opened on 2026-10-09 and are green after the EXE001 fix (first green run https://github.com/jschnepel/MLOps/actions/runs/37962510516; record `reports/ci/t06-first-ci-runs.txt`); PRs #1-#11 (plan-b -> main through plan-l -> plan-k) were merged into `main` by the owner on 2026-10-18 (merge commits; the plan branches are kept); `plan-j` and `plan-k` were pushed (2026-10-16), `plan-l` on 2026-10-18 (PR #11).

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

## Plan L executed (2026-10-18 UTC, branch `plan-l`)

- T17 = `c329145..bbba69c` (the debt list first, then the five building tasks; the close-out is the commit after
  `bbba69c`). The plan (`docs/superpowers/plans/2026-10-16-first-slice-l-governed-corpus.md`) holds the 24 rulings of
  the controller's brief as implemented, with seven departures named at its top; the input is
  `docs/superpowers/research/2026-10-16-plan-l-inputs.md`. Evidence: `tests/e2e/test_migration_0011_live.py` (the
  lifecycle cases at the definer, the test clock moved, tenant and asset-type filtering, ties, limits and refusals,
  the ACL and the worker's RLS, the round trip to 0010 with the extension kept), `test_ingest_live.py` (R032),
  `test_mcp_read_live.py` (the tool over HTTP on the governed corpus), `test_retrieval_baseline_live.py` and
  `reports/retrieval/t17-lexical-baseline.md`/`.json` (R033); the unit half is in `tests/plan_l/` (R099:
  `test_corpus_files.py`); the settings, the score interpretation and the freeze are in `docs/retrieval.md`.
- **R033** is met subject to the owner's decision on erratum 102: at the 0.25 minimum rank 15/20 no-source
  development questions were answered with nothing; the other 5/20 stay open: SA:377 as written counts any returned effective chunk as sufficient and would not abstain on them, so T20 must add a relevance criterion beyond it (for example a score or label-based sufficiency rule). The minimum rank was
  chosen on the same 47 queries, so the baseline is a development figure, not a held-out one.
- **The frozen corpus.** `corpus-1`, lock `81f50c2b8623675f9c899033cba748f289b7f4024003385aabc8a95147b71862`
  (`ops_core.corpus.RELEASES`), is the corpus T41 labels the holdout against; any change to a locked file after T41
  is a new version and requires re-labelling.
- Gates: `check.py` 1270 passed, 191 skipped; `check.py --profile test` 1440 passed, 21 skipped; `verify_handoff.py` exit 0 (STATUS.md, "Update —
  Plan L executed").
- **Proposed errata (the owner decides; the spec text stays authoritative until then).** Numbered on from Plan K's
  ninety-two:
  93. SA:461 (`search_procedures_scoped`): the signature is `(raw_handle, client_azp, query, query_embedding
      vector(768), asset_type, limit, mode)`, the caller's `azp` second as in `resolve_invocation` and the write path
      (erratum 83), because `_resolve_handle` binds the handle to the presented token's `azp`; it returns one row
      `(corpus_version, results)`, the tenant's latest ingested corpus version (`none` before any) and the ranked
      results with a `rank` each, which mcp-read leaves out of the tool result.
  94. AM-20.2 SA:431 with BS:241 (the corpus lifecycle): no role may UPDATE the corpus, so status and effective
      interval are append-only `document_states` rows and the highest `seq` is current; a document's versions form
      one chain (consecutive whole numbers, each naming the one before in `supersedes`); "superseded" is a status or
      the effect of retirement (a later version that has left `draft` has reached its `effective_from`; final, even
      if that successor is later revoked or expires, because ingestion refuses the only changes that could undo
      it: a version that has left `draft` never returns to it and keeps its `effective_from`), "expired" is
      `effective_to` at or before now, "revoked" is final.
  95. AM-20.2 SA:431 and AM-20.5 SA:510: `document_states` and `corpus_ingestions` join `documents` and `chunks` with
      the same cells (`worker` INSERT/SELECT, `app_definer` SELECT) and the `tenant_isolation` policy; `embeddings`
      is created by T18, its first writer.
  96. R131 with errata 72 and 91: `mcp_read` executes `current_time`, `resolve_invocation` and
      `search_procedures_scoped`; only `asset_scope` (T16) is still to come; `mcp_exec`'s "no read function" now
      includes `search_procedures_scoped` (42501 when called).
  97. BS:413 ("tenant or explicit shared policy"): v1 documents are tenant-only; a document both tenants need is copied;
      AM-20.5 keeps its two policies.
  98. AM-20.4 and SA:440 (who writes the corpus): ingestion is an operator command, `scripts/skeleton.py ingest`,
      connecting as `worker` (AM-20.2's ingestion cells), not a job type and not a `migrator` data migration; the
      services start on an empty corpus and the worker then answers INSUFFICIENT_EVIDENCE.
  99. SA:461 and SA:348 (vector mode): `mode = 'vector'` is refused inside the function (`OC005`
      `VECTOR_MODE_UNAVAILABLE`) until T18 stores embeddings; the `vector` extension is bootstrap infrastructure
      (`skeleton.py ensure_extensions`) that revision 0011 requires and never creates or drops.
  100. BS:415 (chunking): one chunk per `## ` section (45-119 words in corpus-1, below the initial 300-600-token
       proposal), measured in `[a-z0-9]+` words because no tokenizer is locked; another window is evaluated in T18's
       comparison.
  101. `data/handoff-fixtures/README.md` ("do not add attack variants to a normal approved corpus without an explicit
       test flag"): AM-50 wins; one injected document per tenant is approved and labelled `injected`, stored and not
       filtered; the delivered fixtures stay the 1.0 contract fixture and no service reads them.
  102. R033 ("missing source remains missing, not guessed"): even above the 0.25 minimum rank, lexical OR-matching
       can return a permitted section for a no-source question (15/20 of the development set's no-source questions
       were answered with nothing); the share is measured and reported. The residue (5/20) is open: SA:377 as written
       counts any returned effective chunk as sufficient, so it would not abstain on those cases; T20 must add a
       relevance criterion beyond it (for example a score or label-based sufficiency rule). R033 is recorded as met subject to this erratum.
- Rulings made during execution (the controller's, from the SDD ledger; none changes a spec line):
  (a) the plan printed `search_procedures_scoped`'s argument types in the wrong order (`text, text, public.vector,
  text, integer, text, text`); the function's real order is `(text, text, text, public.vector, text, integer,
  text)`, found by the first live run of the revision and fixed in the type lists only (the revision, `privileges`,
  `persistence`, the unit tests); the plan file still prints the wrong list in eight places and is left as written.
  (b) The added refusal tests (Task 2) and the fix rounds' tests (Task 3) put the dev count 51 above the plan's
  arithmetic (52 after the final-review wave added one test); every gate figure here is the measured one. (c) Ingestion refuses `superseded` -> `approved` (fail
  closed; an owner who wants the text back publishes a new version). (d) A lock against concurrent ingestions was
  declined (one operator; a concurrent run can raise a unique violation, and nothing is half-written within a
  tenant). (e) The baseline measurement pins the test clock to the labelling instant (`AS_OF`) and asserts the
  permitted set equals both `corpus.returnable(AS_OF)` and the hand-written `RETURNABLE_AT_AS_OF`, so the figures
  reproduce on any date; the in-measurement forbidden check is circular (SQL against the same rule in Python) and
  `docs/retrieval.md` names the hand-written anchor as the independent check.
- **Open items for later** (minors parked by the task reviews; none changes a verdict):
  the final whole-branch review (0 Critical, 0 Important, 5 Minor; record in
  `docs/reviews/plan-l-final-review-2026-10-18.md`, fix wave 2f7efa4 and 34e9c42) took M1 to M3 in a fix wave (no
  `type: ignore` left: `IngestInterrupted` chains the store failure and carries the tenants written; `skeleton.py
  ingest` prints a `PersistenceError`'s own hint, class only for a driver error; this history), recorded M4 as a debt
  line (the Plan L debt list: `retrieved_at` -> T16) and M5 as a line in `docs/retrieval.md`. It ruled three parked
  minors harmless: the Task 5 test pins the rendered development-figure sentence, not the words inside
  `SETTINGS["minimum_rank"]` (the constant already contains them and the markdown is rendered from it, so a test on the
  constant adds nothing); the Task 5 `finally` resets the clock before `purge_run` (if the reset raised, the runs
  would leak only into `ops_test`, which the next session drops, and the clock reset matters more); and `skeleton.py
  ingest` has no concurrency lock (every concurrent interleaving traced ends in a primary-key collision and a tenant
  rollback, never in a wrong state; the operator re-runs). Also open: a phase-2 refusal (the store changed between
  ingestion's two phases, a concurrent run) can leave earlier tenants written and is reported as such, not prevented;
  lengthening or clearing `effective_to` stays allowed; the query is normalised by
  `regexp_replace('[^a-z0-9]+', ' ')` while chunk text is parsed raw, so `4.5` or `M8x1.25` cannot match as one
  lexeme (T18); the no-source questions that still return a section (A15, B10, B13, B17, B18) come from generic
  words such as `records` and are T18's tuning and T20's relevance criterion (SA:377 alone would not abstain on them), not a defect of `corpus-1`; the plan file
  still prints the wrong regprocedure signature in eight places.

## Plan M executed (2026-10-18, branch `plan-m`)

- T16 = `9e7d716..bbaba40` (the debt list first, then the six building tasks; the close-out is the commit after
  `bbaba40`). The plan (`docs/superpowers/plans/2026-10-18-first-slice-m-read-tools-asset-sim.md`) holds the 18 rulings
  of the controller's brief as implemented, with ten writer departures named at its top; the input is
  `docs/superpowers/research/2026-10-18-plan-m-inputs.md`. Evidence: `tests/e2e/test_migration_0012_live.py`,
  `test_asset_sim_live.py`, `test_mcp_read_t16_live.py`, `reports/asset-sim/t16-asset-sim.txt` and
  `reports/mcp-read/t16-read-tools.txt` (live); `tests/plan_m/` (unit).
- Shipped: revision `0012_asset_scope` (`asset_scope`, the requester re-check in both read definers, the search's
  `retrieved_at` and whole-section excerpt; exact downgrade to 0011); asset-sim on port 8091, the skeleton's seventh
  process; mcp-read's `get_asset_status` and `get_recent_alerts` and the search on the run's asset type; the committed
  input schemas advertised and checked (`ops_core.tool_contracts`); the worker's R029 checks.
- Gates: `check.py` `1372 passed, 205 skipped`; `check.py --profile test` `1556 passed, 21 skipped`; `verify_handoff.py` exit 0. (The plan's own
  arithmetic, 1344 and 1528, is superseded: the review rounds added tests.)
- **Proposed errata (the owner decides; the spec text stays authoritative until then).** Numbered on from Plan L's
  hundred and two:
  103. T16's instruction and review note (`handoff/tasks.json`, "vector mode: mcp-read computes the nomic
       search_query embedding"), SA:348 and SA:461: mcp-read's `vector_exact` → `mode=vector` translation and the
       `search_query:` embedding move to T18 with the embeddings; until then mcp-read answers `vector_exact` with
       `UNSUPPORTED_MODE` after the handle resolution, and the definer refuses `mode=vector`.
  104. SA:460 (`asset_scope`): the signature is `(raw_handle, client_azp)`, the caller's `azp` second as in
       `resolve_invocation`, the write path and the search (errata 83 and 93), because `_resolve_handle` binds the
       handle to the presented token's `azp`; it returns one row `(run_id, tenant_id, asset_id, start_at, end_at,
       as_of)`, `as_of` being `app.current_time()` read after the lease lock (SA:157), the instant asset-sim answers
       at; `mcp_read` only; it checks no tool (the allowlist stays in Python, erratum 19).
  105. BS:362 and BS:401 with R028 (the requester's policy at read time): `asset_scope` and `search_procedures_scoped`
       require an active `memberships` row `(the run's tenant, subject = runs.requester, role 'requester')`, matched
       without the issuer because `runs` keeps none (the API admits a requester by `(issuer, subject)` with the
       realm's one configured issuer); without it the call is refused exactly as a dead handle is (`OC008`, one
       message, SA:355). `resolve_invocation` is unchanged (erratum 77). Note for the owner: the read-path check
       requires only an active row, with no `synced_at` freshness bound like the write gate's `MEMBERSHIP_STALE`
       (0005:129-139). While the sweeper syncs, a deprovisioned requester keeps read access until the next sync (a
       60-second cadence, SA:547); if the sync stops, that access lasts until it resumes. A read-path freshness bound
       is T20's, subject to the owner's decision on this erratum.
  106. SA:461 with erratum 93 (`search_procedures_scoped`'s answer): one row `(corpus_version, retrieved_at,
       results)`, `retrieved_at` the instant its effectiveness rule ran at; each result's excerpt is the whole section
       up to the contract's 8000 characters and carries `excerpt_cut`, which mcp-read turns into the envelope's
       `truncated` and leaves out of the result. It amends erratum 93's 500-character excerpt: on corpus-1, 15 of the
       69 sections (504 to 669 characters) now return whole.
- Rulings made during execution (the controller's, from the SDD ledger; none changes a spec line): (a) the stray
  broad `ValueError`/`TypeError`/`RuntimeError` catch around asset-sim's token fetch and request (Task 3) could turn a
  bug into a retryable `UNAVAILABLE`; the window is small and the catch is commented, so it is parked, not fixed.
  (b) The review minors that were debts, not defects, went to the debt list instead of code: the read-membership
  freshness bound (erratum 105's note), the packaging of `schemas/` for the images of mcp-read and the worker (T30),
  and a raw-listing check for a tool the SDK drops before the worker sees it (T30). (c) Where a review found the plan's
  own text wrong (a forged cursor with a valid binding, a status answer's `observed_at`), the fix follows the review
  and the plan file keeps its text. (d) Task 6 rewrote thirteen sentences of the brief's documentation to match the
  built code, for example a lost audience gives `UPSTREAM_INVALID`, not `UNAVAILABLE`.

## Plan N executed (2026-10-19, branch `plan-n`)

- T18 = `4c99f14..799beda` (the debt list first, then the seven building tasks; the close-out is the commit after
  `799beda`). The plan (`docs/superpowers/plans/2026-10-19-first-slice-n-vector-retrieval.md`) holds the 18 rulings of
  the controller's brief as implemented, with eleven departures named at its top; the input is
  `docs/superpowers/research/2026-10-19-plan-n-inputs.md`; the plan review is
  `docs/reviews/plan-review-n-2026-10-19.md`. Evidence: `reports/retrieval-comparison.md` and `.json`,
  `tests/e2e/test_retrieval_comparison_live.py`, `test_vector_retrieval_live.py`, `test_migration_0013_live.py`
  (live); `tests/plan_n/` (unit); `data/embedding-pins.json`.
- Shipped: the embedding pin and its schema (the script validates before it writes and will not replace another
  model's pin); `ops_core.embeddings`; revision `0013_embeddings` (`app.embeddings` with a CHECK against a stored zero
  vector, `app._min_similarity()` 0.68, the vector branch, which never keeps a NaN similarity; exact downgrade to
  0012); `scripts/skeleton.py embed` (the pin re-verified before each tenant's write); mcp-read's `vector_exact` (an
  unreadable pin answers as a missing one); the comparison report.
- Result (development queries, k = 5; the report holds every figure and interval): hit@5 27/27 lexical and 26/27
  vector (A08 is the miss); recall over expected sections 31/31 and 29/31; no-source cases answered with nothing
  15/20 lexical and 18/20 vector (B10, B13, B17 and B18 improve, A13 regresses); no forbidden section in either
  mode (0/122 and 0/87 rows). McNemar p is 1.0 and 0.375: no ranking claim. The vector threshold was tuned and the
  lexical one was not; the same rule on lexical gives 0.79 and 17/20.
- Final whole-branch review: ready with fixes, 0 Critical, 1 Important and 7 Minor; one fix wave after `3c69add`
  (the commit after it): erratum 107 and `skeleton.embed`'s docstring now say that a pin mismatch found by the re-check
  names the tenants already written (I1); `checked()` refuses a component above 1e6 or a norm below 1e-6 (m1); an
  unreadable pin file is a `ModelPinsError` for every caller (m2); the Downstream row, the T18 note's endpoints and
  deferred items, the over-long lines, `TODO(T30)` and the ambiguous Claim sentence (m3, m4, m7). The `3c69add`
  subject names "the comparison report", which was committed in Task 6, not there (m5; history is not rewritten).
  The stored-digest read-path check stays debt with its trigger, the first embedding-model change (m6).
- Gates: `check.py` `1461 passed, 218 skipped`; `check.py --profile test` `1658 passed, 21 skipped`; `verify_handoff.py` exit 0.
- **Proposed errata (the owner decides; the spec text stays authoritative until then).** Numbered on from Plan M's
  hundred and six:
  107. SA:598 and SA:768 (`data/model-pins.json`): the file stays the generation model's (T02, T19); the embedding
       model's pin is `data/embedding-pins.json` (`{model, digest, dimension, ollama_version, probed_at}`, schema
       `schemas/embedding-pins.schema.json`, `ops_core.model_pins.load_embedding_pins`), verified against the digest
       `/api/tags` reports (AM-31 names `/api/show`, which carries none, as T19's note found for qwen3:8b), by
       `scripts/skeleton.py embed` before it writes (and again before each tenant's write) and by mcp-read on every
       vector call. A mismatch or a missing pin found before `embed` writes makes it exit 1 writing nothing; one found
       by the re-check before a later tenant's write exits 1 naming the tenants already written (their rows stay,
       made while the pin still matched). A mismatch makes mcp-read answer `UNSUPPORTED_MODE`. A pin that is
       unreadable or malformed answers the same way as a missing one in all three (`embed`, the pin script and
       mcp-read).
  108. BS:646 (the MCP row), BS:144 (the diagram), ADR-0001:31 and `docs/ARCHITECTURE.md`: mcp-read → Ollama,
       `/api/tags` and `/api/embed` with the embedding model only, never generation, because SA:348 and SA:461 make
       mcp-read compute the query embedding; recorded in `docs/ARCHITECTURE.md` section 11 and as a dated note under
       ADR-0001. The call is not a `model_permit` holder: SA:203's global model concurrency governs generation.
  109. SA:584 (`pgvector-python` 0.5.0): unused, not violated: vectors cross as pgvector's text form cast in SQL
       (`%s::public.vector`, `repr` floats, `ops_core.embeddings.vector_literal`), so no dependency or adapter is
       added; tests read vectors back by parsing the text form.
  110. SA:461 (`search_procedures_scoped`): `mode` is `lexical` or `vector`; `query` is required and bounded 1-500 in
       both modes; `vector` requires one non-zero embedding of exactly 768 dimensions and `lexical` none, else `OC005`
       `BAD_ARGUMENT`; in vector mode a permitted chunk without an embedding refuses the call (`OC005`
       `EMBEDDINGS_INCOMPLETE`) instead of being left out; the stop-word early return is lexical only;
       `VECTOR_MODE_UNAVAILABLE` (erratum 99) is gone.
  111. BS:242 and BS:417: in vector mode `rank` is the cosine similarity `1 - (embedding <=> query)`, ordered with the
       lexical tie-break and kept above `app._min_similarity()` (0.68), a development figure chosen on the 47
       development queries by a rule fixed before measuring (the largest value on a 0.01 grid at which vector hit@5
       over the labelled cases equals its value at 0); it is not comparable with `ts_rank_cd`. A section whose
       similarity is NaN is never kept: pgvector sums in single precision, so finite extreme components overflow to
       NaN, which PostgreSQL sorts above every number. BS:242's "index version" is recorded as model + digest +
       dimension + prefix + window: there is no vector index, and the search is exact by construction.
- The installed Ollama is 0.40.4; SA:587 records 0.33.3 ("upgrade only with owner approval"). The upgrade predates
  this plan; the pin records the version actually used, and nothing here changed it. The owner decides.
- Rulings made during execution (the controller's, from the SDD ledger; none changes a spec line): (a) the pin
  script's single failure shape, the NaN filter, the per-tenant pin check and the unreadable-pin answer came from
  review rounds and are in the code, not debts. (b) `embed`'s planning phase reads every chunk's full body only to
  count the chunks; it is parked (69 chunks on corpus-1, no behaviour change; cost: a slower plan pass on a large
  corpus). (c) The window experiment degenerates on corpus-1 (every returnable version is one window); the report
  says so, counts its forbidden windows at threshold 0 (JSON key `forbidden_windows`), and nothing else was built.
  (d) The two comparison report files were committed in Task 6, not in the close-out; the final live run is
  restored with `git checkout -- reports/`, keeping nothing new.

## Plan O executed (2026-10-20 UTC, branch `plan-o`)

- T23 = `e91b27b..80da1f2` (the debt list first, then the four building tasks; the close-out is the commit after
  `80da1f2`). The plan (`docs/superpowers/plans/2026-10-19-first-slice-o-dev-eval-set.md`) holds the 12 rulings of
  the controller's brief as implemented, with seven departures named at its top; the input is
  `docs/superpowers/research/2026-10-19-plan-o-inputs.md`; the plan review is
  `docs/reviews/plan-review-o-2026-10-19.md`. Evidence: `evals/dev/cases.jsonl`,
  `evals/dev-case.schema.json`, `core/src/ops_core/grading.py`, `tests/plan_o/` (unit), `evals/dev/RUBRIC.md`,
  `evals/groundedness-label.schema.json`, `evals/quality-gates.schema.json`; the measurement
  `reports/retrieval/t23-numeric-tokens.md` and `.json` (`tests/e2e/test_numeric_tokens_live.py`, live).
- The numeric-token finding: numeric tokens at k = 5 over six pairs: lexical numeric 5/6, controls 6/6, decimal 2/3
  against 3/3, lost P06 (its control is at rank 1; the pair is confounded: its numeric query writes `mm`, which
  corpus-1 never uses, and its control says `millimetre`, so the miss is not the decimal split's alone); vector_exact numeric 6/6, controls 6/6, decimal 3/3 against 3/3,
  lost none; no forbidden row in either mode. The lexical loss on the decimal pairs is not total, so the search is
  unchanged (BS:71) and the debt is closed as a measurement; a change would need a total loss and would be a later
  revision under T20.
- Shipped, as reviewed: 60 development cases (30 per tenant, nine categories, `as_of` 2026-10-06T12:00Z) with gold
  labels checked against corpus-1 by test, file and schema SHA-256 pinned; the case loader, which names the file and
  line of a malformed row; four graders, each a verdict whose reason is a `Literal` rule name (schema, which needs the
  JSON Schema and `ModelDraft` to agree; citation validity; citation sufficiency; abstention, where a question on a
  proposal or an answer fails as `question_unexpected`); the `cross_tenant_or_unpermitted` flag, whose scan reaches
  references nested in lists, tuples and dicts; `case_passes` (2 of 3 trials for conditions B and C, the one manual
  trial for A) and `case_safe` (any trial); the groundedness rubric with ten worked examples whose quotes are tested
  word for word; the label and quality-gates schemas.
- Reviews: one static plan round (0 Critical, 3 Important, 11 Minor, 9 disputed labels; fixed in 10db78d, the
  controller checked the diff instead of a second round) and, per task, one review and one fix round (Tasks 1-3:
  approved with minors; Task 4: needs fixes, 1 Important) and the final whole-branch review (0 Critical,
  3 Important, 8 Minor; the controller ruled on each and one fix wave closed them). Each round's problem and fix is
  in `docs/PROJECT_HISTORY.md` section 32.
- Gates: `check.py` `1539 passed, 219 skipped`; `check.py --profile test` `1737 passed, 21 skipped`;
  `verify_handoff.py` exit 0. No generation model ran (the embedding model did, through local Ollama), and nothing from Plan O connected to the dev database.
- **Proposed errata (the owner decides; the spec text stays authoritative until then).** Numbered on from Plan N's
  hundred and eleven:
  112. R111 ("Development evaluation set has gold labels and calibrated graders") and its expected evidence: the
       graders T23 ships are deterministic (`ops_core.grading`: schema, citation validity, citation sufficiency,
       abstention, and the cross-tenant-or-unpermitted safety flag), unit-tested on hand-written drafts; calibrating a
       grader against the owner's reviewed labels is T25's (R073, "Compare grader with reviewed labels"). R111 is met
       subject to this erratum.
  113. SA:671 and SA:765 assign `evals/quality-gates.schema.json` to T23; `handoff/tasks.json` (T23's instructions
       and definition of done) does not list it. T23 owns the schema (an array of `{metric, condition, threshold,
       applies_to, blocking}`, the metrics `ops_core.grading.GRADERS` plus `groundedness_mean`,
       `unauthorized_writes`, `fabricated_success` and `cross_tenant_leakage`, the conditions A, B and C); the file
       `evals/quality-gates.json` stays the owner's, committed before the first holdout run (SA:672).
- Rulings made during execution (the controller's, from the SDD ledger; none changes a spec line): (a) the plan had
  one static review round on the owner's steer (a portfolio project, scaffolding first, kept lean), with the
  fixes checked by the controller. (b) On 2026-10-19, before the plan ran, the owner asked the agent to run the
  owner steps: `skeleton.py migrate` and `embed` ran on the dev database (0013; alpha 39 and beta 30 sections, recorded
  in 128258c), while merging PRs #12 and #13 and posting a pre-merge review comment on the agent's own PRs were
  refused by the permission system. The merges stay with the owner and block nothing, because `plan-o` is stacked on
  `plan-n`. (c) The plan's live count (1722) was out of date: its arithmetic was one low and the review rounds added
  13 tests to the dev suite (1525 to 1538) and the final review's wave one more (1539). (d) The final live run rewrote the files under `reports/` and they were
  restored with `git checkout -- reports/`, keeping nothing new: the committed numeric report (Task 4) already holds
  these figures.

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
  refuse to start on it → owner input → closed 2026-10-18 (dev at 0011, corpus-1 ingested);
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
  the sweeper, the worker and mcp-write refuse to start on it → owner input → closed 2026-10-18 (dev at 0011, corpus-1 ingested);
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
  API, the sweeper, the worker and mcp-write refuse to start on it → owner input → closed 2026-10-18 (dev at 0011, corpus-1 ingested).

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
  the API, the sweeper, the worker, mcp-write and now mcp-read refuse to start on it → owner input → closed 2026-10-18 (dev at 0011, corpus-1 ingested);
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
  sweeper, the worker, mcp-read and mcp-write refuse to start on it, mcp-write now also without 0010 → owner input → closed 2026-10-18 (dev at 0011, corpus-1 ingested).

## Plan L debt list (T17; committed before coding) [R6-B7]

Allowed shortcuts in T17, each with its owning task:
- vector retrieval: the `embeddings` table, the nomic-embed-text `search_document:`/`search_query:` embeddings, the
  `mode = 'vector'` branch of `search_procedures_scoped` (refused `VECTOR_MODE_UNAVAILABLE` until then), tuning the
  minimum rank (0.25, chosen on the development queries; `ts_rank_cd` is unnormalised, so it depends on query
  length), and the evaluation of another chunk window than one per section → T18 (Plan L rulings
  2, 4 and 18); mcp-read's `vector_exact` → `mode=vector` translation (until then `UNSUPPORTED_MODE` before the
  database) → T16;
- the query is normalised by `regexp_replace('[^a-z0-9]+', ' ')` while chunk text is parsed raw, so a token such as
  `4.5` or `M8x1.25` cannot match as one lexeme (recall loss on numeric values) → T18;
- `asset_scope`, the asset tools, asset-sim serving `data/corpus/assets.json`, and the run's own asset type passed to
  the search (the tool takes `asset_type` from its caller only) → T16 (ruling 11);
- the requester's current membership re-checked at read time (R028) → T16 (ruling 10);
- the final grant's recheck that every cited source version is still approved and effective (BS:425, R045) → T21;
  revoked text kept out of checkpoints, summaries and events (R035) → T26 (ruling 22);
- the model-side proof that the injected documents grant nothing (R036), and detecting the conflicting pair and
  abstaining → T19/T20 (rulings 13 and 14);
- the excerpt is still cut silently at 500 characters (Plan D's open item) → T16;
- `retrieved_at` is the wall clock (`datetime.now(UTC)` in mcp-read's `search_response`) while a version's
  effectiveness is decided at `app.current_time()`, so under a moved test clock a result can carry a `retrieved_at`
  earlier than its own `effective_from`; return the definer's instant (one more column) and stamp `retrieved_at` from
  it, so the evidence row records the instant its permission was decided → T16 (Plan L final review, M4);
- shared (cross-tenant) documents: none; a document both tenants need is copied per tenant → no task (erratum 97,
  ruling 9);
- the dev database: migrated to 0011 and corpus-1 ingested by the owner on 2026-10-18 → closed (ruling 24).

## Plan M debt list (T16; committed before coding) [R6-B7]

Allowed shortcuts in T16, each with its owning task:
- vector mode: mcp-read's `vector_exact` → `mode=vector` translation and the nomic `search_query:` embedding it
  computes, with the embeddings themselves → T18 (Plan M ruling 1, erratum 103); until then mcp-read answers
  `vector_exact` with `UNSUPPORTED_MODE` after the handle resolution and the definer refuses `mode=vector`;
- the worker's calls to `get_asset_status` and `get_recent_alerts` and their results in the draft and the evidence
  bundle (BS:419), and SA:377's evidence-sufficiency rule → T20 (rulings 16 and 17);
- recording the status observation (`observed_at`, `revision`) where the grant can check its 5-minute freshness
  (R116, BS:476) → T21 (ruling 16);
- the worker's write calls (`create_incident` at mcp-write) keep T47's result check: no tool discovery and no
  result-schema check (mcp-write advertises its generated schemas, not the committed files) → T20, which builds
  AM-12's `execute_approved_proposal (mcp-write)` node (SA:207) and every route of R129;
- the worker's 256 KiB result bound is applied after the MCP SDK has read and parsed the body (no hook stops it
  earlier); a transport-level bound → T30, with the container network work (departure 5);
- the worker's listing check sees the listing as the MCP SDK (2.3.0) hands it over: the SDK drops a tool whose
  `x-mcp-header` annotation is invalid before `check_listing` runs (`ClientSession._absorb_tool_listing`), and a
  HEADER_MISMATCH retry inside `call_tool` re-lists outside `check_listing`; a check on the raw listing → T30, with the
  transport-level bound (the called result is still validated in full, and the dropped tool cannot be called through
  this client);
- a run's asset is not tied to its tenant at admission (an alpha run may name beta's B22; asset-sim's own tenant filter
  answers NOT_FOUND, and the search then has no run type) → T21 (the asset guard; its review note names alpha-for-B22);
- a handle that dies between `asset_scope` and the asset-sim call still yields one read of the run's own asset (no
  write, no authority gained): documented, not prevented → no task (ruling 15);
- the fallback `corpus_version` is closed by T17 (the definer answers `none`) and the `UNSUPPORTED_MODE` order stays
  (the handle first) → no task (ruling 14);
- asset-sim and mcp-read read `data/corpus/` and `schemas/` from the checkout; packaging them, asset-sim's Dockerfile
  and `tests/` directory, TLS and container host names, and the network test that only mcp-read reaches asset-sim →
  T30 (ruling 5); `ops_core.tool_contracts.SCHEMAS` finds `schemas/` three directories above its own source file, so
  the images of mcp-read and the worker must ship `schemas/` at that path (or the path becomes a setting) → T30;
- the requester's membership is matched without an issuer (the run keeps none) → owner decision (erratum 105);
- the read path's membership re-check requires only an active row, with no `synced_at` freshness bound like the write
  gate's `MEMBERSHIP_STALE` (0005:129-139): while the sweeper syncs, a deprovisioned requester keeps read access until
  the next sync (60 s cadence, SA:547); if the sync stops, the access lasts until it resumes → a read-path freshness
  bound → T20 (the next read-path task), subject to the owner's decision on erratum 105;
- a retryable read failure ends the run: the worker's investigate handler turns any failed read, including a retryable
  `UNAVAILABLE` from asset-sim behind the search, into FAILED "retrieval failed" and never reads `retryable` → T20
  (honour `retryable` from a read with a bounded re-queue of the investigate job);
- the dev database stays at revision 0011 until the owner runs `scripts/skeleton.py migrate`; until then mcp-read
  refuses to start on it (it checks 0012) → owner input (ruling 3).

## Plan N debt list (T18; committed before coding) [R6-B7]

Allowed shortcuts in T18, each with its owning task:
- the worker still searches in lexical mode only; choosing the mode per run and recording it in the run manifest →
  T20 (the graph's retrieve node) and T25 (SA:660's identical retrieval settings for conditions B and C) (Plan N
  ruling 16; `routing.py` carries `TODO(T25)`);
- the vector threshold (`app._min_similarity()`, 0.68) and the lexical minimum rank (0.25) are development figures
  chosen on the 47 development queries; a relevance or abstention rule beyond them → T20 (erratum 102), and a held-out
  measurement of both modes → T25 (Plan N rulings 6 and 9);
- numeric tokens (`4.5`, `M8x1.25`) cannot match as one lexeme (the query is normalised to `[a-z0-9]+` words while the
  chunk text is parsed raw): the development set gains numeric-token cases and measures the loss first → T23 (Plan N
  ruling 10);
- the stored unit stays one chunk per `## ` section; the 300-word window is an experiment in the comparison report
  only, because another stored unit changes evidence IDs and T41's labels → no task (Plan N ruling 8);
- one embedding per chunk: a model change is a later revision that removes the stored embeddings (or moves them
  aside), after which the pin is replaced as a reviewed change and `embed` runs again (`app.embeddings`'s key and its
  CHECKs pin the model and the dimension; `scripts/pin_embedding_model.py` refuses to replace another model's pin),
  and a read-path check that the stored rows' digest is the pin's belongs to that first re-embedding revision → the
  first embedding-model change (no task yet; the owner opens one). Until then an owner who edits the pin by hand
  without that revision gets mixed-model answers; the edit is a reviewed repository change (Plan N ruling 1; rounds
  1 and 2, I2; final review m6);
- a NaN similarity on a permitted row is dropped, not refused. The embedding client now refuses components above 1e6
  and a norm below 1e-6, so only a row written around the client (a superuser insert) can reach it → no task (final
  review m1);
- chunks ingested after an `embed` run stay without an embedding until `embed` runs again; vector mode answers
  `REFUSED`/`EMBEDDINGS_INCOMPLETE` meanwhile, lexical mode is unaffected → operator step (runbook), no task (Plan N
  rulings 2 and 5);
- mcp-read's route to Ollama in containers (host name, the egress test that mcp-read reaches Ollama's embedding
  endpoints only) and packaging `data/embedding-pins.json` with mcp-read → T30 (erratum 108);
- the installed Ollama is 0.40.4 where SA:587 records 0.33.3; the pin records the version actually used and nothing
  here upgrades or downgrades it → owner decision (SA:587);
- the dev database: migrated to 0013 and embedded on 2026-10-19 (the agent ran `skeleton.py migrate` and `embed` at
  the owner's request) → closed.

## Plan O debt list (T23; committed before coding) [R6-B7]

Allowed shortcuts in T23, each with its owning task:
- the development cases are checked against corpus-1 by unit test and never run: no model trial, no condition A, B
  or C run and no groundedness label exists yet → T19 (the first real drafts) and T25 (trials, conditions, labels)
  (Plan O rulings 4 and 8);
- "calibrated graders" (R111) is met by deterministic graders unit-tested on hand-written drafts; comparing them with
  the owner's reviewed labels → T25 (R073; erratum 112);
- the statistics: case-level Wilson intervals, the case-cluster bootstrap, exact McNemar, intra-rater kappa, and
  unifying the two Wilson functions (`scripts/retrieval_baseline.wilson`, `scripts/probe_stats.wilson`) → T25 (Plan O
  ruling 4);
- `evals/quality-gates.json` (the thresholds) → the owner, committed before the first holdout run (SA:672); the label
  files → T25 (Plan O rulings 6 and 9);
- the citation graders see what a draft cites, not whether its claims follow from it: that is the owner's
  groundedness label (BS:452), and any semantic judge is T25's to calibrate (BS:609, R073);
- operational-fault and control-path cases (lost response, stale approval, cancellation) and the 32 cards → T24 (the
  scenario suite, R097); `evals/handoff-development/README.md`'s stale 80/40 text → T24 (its review note);
- every development case sits at one instant (`as_of` 2026-10-06T12:00Z, the cards' fixture clock); cases at other
  instants, across a version's effective date, → a later dev-set version, no task (Plan O ruling 1);
- the numeric-token measurement is recorded, not acted on: a change to the lexical query normalisation (revision
  0011's `regexp_replace`) needs a total loss on every decimal pair (the only tokens it splits), and even then it is
  a later revision under T20 (the retrieve node and its relevance rule), never T23 (Plan O ruling 7; BS:71);
- condition A on every non-proposal case: a manual proposal is always a proposal with at least one reference
  (`schemas/manual-proposal.schema.json`), so `check_abstention` fails it on every case that expects an answer or an
  abstention (41 of the 60: `proposal_on_answer_only` on the `answer_only` ones, `kind_mismatch` or `did_not_abstain`
  on the rest), by construction; only the 19 proposal-expected cases can pass. How A is scored there (for example,
  "no manual proposal written" counting as the abstention) → T25 (SA:660; round 1, minor 8; final review, I2);
- the safety flag's causes against the SA:673 gates: `cross_tenant_leakage` counts only trials whose `safety` holds
  `cross_tenant`; `unpermitted` (a retired, draft or unknown ID) is a citation-validity failure, not a leak, and T25
  counts each cause separately; `unauthorized_writes` and `fabricated_success` are run-level facts that no grader
  here produces → T25 (final review, I1);
- an unconfounded decimal pair: P06's numeric query writes `mm` and its control `millimetre`, which corpus-1
  never uses, so its miss is not the split's alone; a pair that differs only in the number → the next retrieval change
  (final review, I3);
- `load_cases` reads development rows only (`DV-` ids, `split`, `as_of`, `notes`); a loader for the holdout's rows,
  with T41's labels under their own schema, and the holdout's `as_of` policy (the instant its labels and the safety
  index use) → T25 with T41 (round 1, minor 9).

## Plan P debt list (T19; committed before coding) [R6-B7]

Allowed shortcuts in T19, each with its owning task:
- an `answer` draft and an `abstain` draft with a question end the run FAILED with a templated message; the graph
  router that sends them to ANSWERED and AWAITING_INPUT, and the `resume_input` job, → T20 (SA:137, SA:153; R114,
  R129) (Plan P ruling 11); the payload does not tell the model that an `answer_only` run may not propose, so such a
  run spends its first attempt on a refused proposal and relies on the repair's feedback; stating it in the payload →
  T20 (round 1, M10);
- a model timeout, an unreachable Ollama and a draft still invalid after its one repair each end the run FAILED and
  close the job; bounded retries and outage handling → T22 and T29 (BS:562, BS:680; R061, R062) (ruling 8);
- with the model unavailable, the authorized manual search and proposal path is not offered → T21 (BS:564; R057 and
  R041's "manual path") (ruling 8);
- BS:555's 90 s are the run's: each draft attempt is clipped to what the run's compute budget has left (measured from
  the claim, less a 5 s margin), but the heartbeat still cancels the call itself when the budget runs out ("compute
  budget spent": a lost lease, a hand-back and INTERRUPTED rather than the templated failure), and a run that spent
  its budget waiting for the permit gets no draft at all → T29 (as Plan H's debt line);
- the worker sends the model the request, the asset, the interval and the retrieved procedure sections only; the asset
  status and alert records reach the model with T20's asset reads (BS:419; R028's note, R038) (ruling 1);
- every manifest records the `retrieval_mode` the tool reports, today always `lexical`, the only mode the worker asks
  for; choosing it per run → T20 and T25 (Plan N ruling 16);
- the manifest holds AM-80's six fields; the commit, workflow version, prompt hash and tool schema version BS:572 also
  names, and the Ollama version, stay in logs and the evidence report → T28 and T37 (ruling 9);
- the digest is checked once, at startup: a model replaced under a running worker is not seen until it restarts →
  T30 (probes and readiness) (ruling 4);
- the permit is released when the draft call ends or is cancelled, T02's provisional "release on cancel"; nothing
  polls `/api/ps` → the owner confirms or reverses the line (T02 DoD 2) (ruling 7);
- the model pin and the draft schema (`schemas/model-draft.schema.json`, through `grading.DRAFT_SCHEMA`) are read from
  the checkout, as the embedding pin is → T30 (packaging);
- telemetry of the LangChain call → T28 (R058, R059); LangSmith tracing, a transitive dependency of `langchain-core`,
  stays off (no `LANGSMITH_*` or `LANGCHAIN_TRACING*` variable is set anywhere);
- whether a draft's claims follow from its evidence, the repeated trials and conditions B and C (R130's identical
  routes) → T25 (BS:452, SA:660); untrusted model text shown safely → T26 (R035, R055);
- the real-model evidence is one run on one machine (BS:566), recorded by hand; a trusted workflow for real-model
  checks → T31;
- the model hint SA:375 makes optional is not built in v1 (erratum 118; no task);
- the dev database stays at 0013 until the owner migrates it (revision 0014); the worker refuses to start on it before
  then.

## Environment (observed)

| Item | Observed |
|---|---|
| OS | Windows 11 Home 10.0.26200 |
| CPU / RAM | Ryzen 9 5900X / 31.9 GB |
| GPU | RTX 3080 (10 GB) |
| Python | 3.13.7 (`python`), 3.14.6 (`py`) |
| uv | 0.11.8 |
| Docker | Docker Desktop 29.6.2 |
| Ollama | Observed at 0.40.4 on 2026-10-15 (recorded 0.33.3 before; Plan J did not change it, and per AM-30 an upgrade is the owner's decision, so this records the observation and claims nothing either way); `qwen3:8b` and `nomic-embed-text` installed as last recorded. Plan N pinned `nomic-embed-text:latest` at digest `0a109f422b47e3a30ba2b10eca18548e944e8a23073ee3f3e947efcf3c45e59f`, 768 dimensions, on 0.40.4 (`data/embedding-pins.json`, 2026-10-19) |
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
- **Erratum 114 (decided by the owner, 2026-10-21; applied 2026-10-24 on `plan-p`):** the sealed holdout no longer
  gates anything ("remove holdout seal"). T03 is dropped from T02's and T19's `depends_on`, T41 from T25's;
  `scripts/probe.py` no longer requires `evals/holdout.sha256` and still refuses an edited starter prompt. T25
  evaluates on the development set and every report says its results are not held out. A holdout stays optional
  owner work (T03, T41; `scripts/seal.py` and the case schema remain), and the custody rule still applies to it: no
  agent opens holdout case material.
- **Build autonomously (2026-10-21/24):** the owner asked the agent to run the build until it is set up, and chose to
  go ahead past T44 step 10 with it pending (the loopback bind of step A is applied). The agent records owner
  decisions it takes on that instruction as provisional, for the owner to confirm or reverse.

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

**Update (2026-10-18 UTC):** Plan L adds revision 0011 and the governed corpus. The dev `ops` database stays at 0010 with no
corpus until the owner runs `uv run python scripts/skeleton.py migrate` (dev profile: `vector` is created if missing,
then 0011 adds `corpus_ingestions`, `documents`, `document_states`, `chunks`, `search_procedures_scoped` and `app._min_rank()`,
changing no row) and then `uv run python scripts/skeleton.py ingest` (corpus-1 into alpha and beta, as the worker; a second run
writes nothing). Until the migration mcp-read refuses to start (it checks 0011's function); until the ingestion every
investigation ends INSUFFICIENT_EVIDENCE.

**Update (2026-10-18, later):** the owner ran `uv run python scripts/skeleton.py migrate` on `plan-l` (dev profile: `app at
app@head, incident at head`), so the dev `ops` database is at `0011_governed_corpus`. The corpus is not yet ingested.

**Update (2026-10-18, later still):** the owner ran `uv run python scripts/skeleton.py ingest` (`INGEST: alpha corpus-1: 9
new, 0 restated, 0 unchanged`; `INGEST: beta corpus-1: 7 new, 0 restated, 0 unchanged`), so corpus-1's 16 documents are in
the dev `ops` database. At the owner's request the agent then ran `skeleton.py up`: all six processes reached ready on
the dev profile (mcp-read's startup check needs 0011), and `down` stopped them.

**Update (2026-10-18):** Plan M adds revision 0012 (`app.asset_scope`, and `app.search_procedures_scoped` re-created with
a new return type). The dev `ops` database stays at 0011 until the owner runs `uv run python scripts/skeleton.py
migrate` (dev profile); the upgrade creates one function, re-creates one and changes no row; until then mcp-read
refuses to start on it, and `skeleton.py up` starts seven processes (asset-sim first).

**Update (2026-10-19):** Plan N adds revision 0013 (`app.embeddings`, `app._min_similarity()`, and
`app.search_procedures_scoped` re-created with its vector branch; return type unchanged). The dev `ops` database stays
where it is until the owner runs `uv run python scripts/skeleton.py migrate` (dev profile; it applies 0012 too if that
is still missing) and then `uv run python scripts/skeleton.py embed` (as the worker, through local Ollama; it prints
`EMBED: alpha: 39 new, 0 present` and `EMBED: beta: 30 new, 0 present` on corpus-1, the first time). Until the
migration mcp-read refuses to start on it; until `embed`, vector searches are refused (`EMBEDDINGS_INCOMPLETE`)
and lexical ones work. No agent connected to the dev database during Plan N. Afterwards, on 2026-10-19 and at the
owner's explicit request, the agent ran `skeleton.py migrate` (`MIGRATE: app at app@head, incident at head (profile
dev)`) and `skeleton.py embed` (`EMBED: alpha: 39 new, 0 present`, `EMBED: beta: 30 new, 0 present`): the dev
database is at 0013 with corpus-1 embedded.

**Update (2026-10-20 UTC):** Plan O added no revision and connected nothing to the dev database; its live tests used only
the `ops_test` databases. The dev database stays at 0013 with corpus-1 embedded.

## Open owner inputs

- Decide errata 35-44 (see "Plan G executed"), 45-59 (see "Plan H executed"), 60-71 (see
  "Plan I executed"), 72-81 (see "Plan J executed"), 82-92 (see "Plan K executed"), 93-102 (see "Plan L
  executed"), 103-106 (see "Plan M executed"), 107-111 (see "Plan N executed") and 112-113 (see "Plan O executed").
- Fill in `evals/quality-gates.json` (schema `evals/quality-gates.schema.json`) and commit it before the first holdout
  run (SA:672-674): the safety gates are fixed at a blocking 0; the quality thresholds are the owner's choice.
- Decide on the installed Ollama 0.40.4 against SA:587's 0.33.3 (the embedding pin records 0.40.4).
- PRs #12, #13 and #14 were merged into `main` on 2026-10-20 at the owner's explicit request (each retargeted to
  `main` first, CI green; merge commits da1db4b, f8145a4 and 3905b35).
- R025 and R031 have every half evidenced (mcp-read by T15, mcp-write by T47, the import half by T04) but keep
  `NOT_IMPLEMENTED_OR_NOT_TARGET_VERIFIED`, because no open task owns them: flipping their status is the owner's call
  (or T15's re-close).
- The stacked PRs #1-#11 are merged (`main` carried #11 by 2026-10-20).
- Decide on the nine proposed contract errata (see "Plan C executed").
- T03 (optional since erratum 114): a holdout is the owner's to write without AI help, if they want one; nothing waits on it.
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
uv run python scripts/skeleton.py ingest  # the governed corpus (T17); a repeat writes nothing
uv run python scripts/skeleton.py embed  # after ingest (T18)
uv run python scripts/skeleton.py up      # then: status, and down when finished
OPS_LIVE=1 PYTHONUTF8=1 uv run python -m pytest tests/e2e -q   # with no skeleton running; rewrites the evidence
```

Then continue with T19 (Plan P; fact sheet `docs/superpowers/research/2026-10-24-plan-p-inputs.md`), then T20, T21,
T22, T24 and T25 in dependency order. Owner inputs still open: the Ollama runbook's other-device LAN check (T44 step
10), the proposed errata (up to 113, plus Plan P's), confirming the probe's provisional decision lines, and
`evals/quality-gates.json`. Before erratum 114 (2026-10-21) every remaining task waited on the holdout seal (T03).

Do not store secrets or private reasoning in this file.

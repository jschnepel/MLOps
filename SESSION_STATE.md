# Session state

**Specification:** OPS-BUILD-1.3.6 (`BUILD_SPEC.md` + `SPEC_AMENDMENTS.md`)
**Current milestone:** M00 (baseline, sealed holdout intents and model probe)
**Next task:** Plan C (T07, T45, T46) is executed on branch `plan-c` (`36c1007..843f365` as of 2026-10-08, plus plan commits 36eb767 and 28fe2a6). Owner inputs still pending: (1) the holdout seal (T03 step 9), then the live probe (T02); (2) push `plan-b` and `plan-c` and open/merge the PRs, record the first CI run URL (T06 step 7); (3) T44 step 10: apply `docs/runbooks/ollama-network.md` step A (loopback bind at User scope), attest, decide on the AM-31 errata; (4) decide on the nine proposed contract errata below. Then write Plan D = T08, the walking skeleton, from the real contracts in `core/`, `compose.yaml` and the realm, with the debt list below as its constraint, and dry-run it on scratch copies before executing.
**Plan A outcome:** executed on branch `plan-a` (a638801..HEAD); `scripts/check.py` GREEN (54 passed, 1 skipped: owner seal). Final whole-branch review: 5 Important findings fixed in the final-review wave; minors deferred: M3 timing restructure (`astream`), M6 mypy member list.
**Repository:** local git repo at `C:\Users\joeys\Desktop\MLOps`, branch `plan-c` (Plan C work on top of `plan-b`, which is on top of `plan-a`). Remote `github.com/jschnepel/MLOps` (public, MIT) exists; `main` and `plan-a` were pushed on 2026-10-07. `plan-b` and `plan-c` are local only and await the owner's push and PRs.

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

Not debt (must be real in T08): client-credentials tokens from T05; aud/azp/iss checks in mcp-read, mcp-write and incident-sim; `action_key` ON CONFLICT; a decision step by a second persona; every transition routed through T07's table.

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

## Open owner inputs

- Approval to push `plan-b` and `plan-c` and open the PRs (the remote exists; `main` and `plan-a` are already pushed).
- Decide on the nine proposed contract errata (see "Plan C executed").
- T03: the owner writes about 25 holdout case intents without AI help, keeps them off-machine, and records the seal hash externally before T02.
- T06: decide whether to publish early (public repo at M01) or start private and make it public at T34. (The repo `jschnepel/MLOps` exists and `main`/`plan-a` were pushed on 2026-10-07; `plan-b` is local.)
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

Then wait for the owner inputs above (holdout seal, then live probe; push and PR; the Ollama runbook step A) and write Plan D (T08) as described in the Next task line.

Do not store secrets or private reasoning in this file.

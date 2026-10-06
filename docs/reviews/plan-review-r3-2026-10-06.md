# Adversarial review, round 3: OPS-BUILD-1.2

**Reviewed:** commit `235a0c0`: SPEC_AMENDMENTS 1.2, ADRs, `tasks.json` (40 tasks), acceptance matrix (117 requirements), scenario cards.
**Date:** 2026-10-06.

**Method:** three fresh reviewers:
1. closure and contradictions;
2. attacks on the 1.2 mechanisms (LangGraph 1.2.14 source read);
3. graph, first slice and evaluation (dependencies resolved with `uv pip compile` for Windows / Python 3.13).

Each finding is labelled **BLOCKS-START** (it changes what T01–T08 build) or **LATER** (the owning task can resolve it). The lead spot-checked the findings.

**Legend:** ✓ verified by the lead · ○ reviewer finding.

## Convergence

| Round | Critical findings | What they were about |
|---|---|---|
| 1 | Architecture holes | Crash windows, state gaps, MCP privilege |
| 2 | 3, in my own 1.1 amendments | Recording ownership, fence locking, tombstones |
| 3 | 2, both narrow | Abort hash semantics; cancel vs `mark_sent` race |

Most round-3 findings are **implementation detail that real tests catch better than more spec text**. Further full-spec review rounds are now low-yield.

**Recommendation:**
- Fix the 14 BLOCKS-START items (below) as a small 1.3 edit.
- Attach every LATER item to its owning task as a review note.
- Start building. From then on, review **each slice's code and tests**, not the spec.

## Proven this round

- **The first slice's dependencies install on this machine** ○: the reference pins (fastapi 0.128.2, pydantic 2.13.4, pytest 9.0.2…) and the AM-30 set (mcp 2.3.0, langgraph 1.2.14, checkpoint-postgres 3.1.2, langchain-ollama 1.1.0, authlib 1.8.0, pgvector 0.5.0) resolve to Windows/Python 3.13 binary wheels.
- **Scenario card reachability is as planned** ○: 23 cards at T24, 3 at T27, 3 at T29, 1 at T32, giving 30. DEV-013 and DEV-032 are deferred, as intended.
- **The graph** is acyclic, every requirement has an owner, and all 117 `suggested_test` fields are set ✓ (round-2 checks).
- **Locking rules hold** ○:
  - FOR SHARE cannot starve acquisition, because an expired lease no longer matches the predicate.
  - The R2#10 timeout rule is sound.
  - `durability="sync"` exists.
- **Round-2 closure:** 6 of 19 findings closed, 13 partly closed, 0 open ○.

## BLOCKS-START (fix before T01–T08)

| # | Finding | Fix |
|---|---|---|
| B1 | **Abort tombstone hash.** ○ AM-13 never says whether abort carries `payload_sha256`. A late POST onto an ABORTED key could be read as "different hash" → CONFLICT → ESCALATED, instead of FAILED. | Abort carries the grant hash. Any POST onto an ABORTED key returns the tombstone (`FAILED_NO_COMMIT/aborted_no_commit`) whatever the hash. Add a fault test. |
| B2 | **Cancel vs `mark_sent`.** ○ Cancel is an API write that doesn't bump the fence, so cancel → `mark_sent` → POST is allowed. That falsifies "INTENT cancel = guaranteed no-commit". | `mark_sent` locks `runs` (in lock order), re-checks `cancel_requested` and returns `cancelled`. `create_incident` is allowed only when there is no attempt, or the attempt is INTENT, not cancelled and before the deadline. |
| B3 | **ESCALATED can wedge forever** ○ (destination permanently unreachable, or CONFLICT): no exit, no admin surface, and the asset guard blocks the asset indefinitely. | Add a recorded operator CLI resolution, `ESCALATED → ABANDONED_UNVERIFIED` (terminal, audited, never claims success or failure). The asset guard excludes it after an explicit acknowledgement. State it in the README. |
| B4 | **Conversation slot.** ✓ BLOCKED_REVIEW frees the slot, but BLOCKED_REVIEW → QUEUED (revision) can create two active runs in one conversation. | That revision transition requires a free slot, else 409. |
| B5 | **Abstain with a question.** ✓ `model-draft.schema.json` has no `question` field, so it can't be told apart from INSUFFICIENT_EVIDENCE. | Add `question` (required when the draft clarifies) to AM-80. |
| B6 | **AM-80 is incomplete.** ○ | Add: event payload `reason`; remove the old `unknown` tool status; `abort_incident` result shape; schemas for feedback, manual proposal, revision and cancel response; error codes for asset-guard refusal and post-grant 409; whether `authored_by` is inside the hashed payload (decide: **outside**, stored alongside). |
| B7 | **T07's DoD "58 reference behaviours pass as core tests" is infeasible.** ○ 11 are FastAPI tests and most others need DB, auth or the destination (T09–T22). It also contradicts AM-70's "don't port". | T07 ports the pure-core tests and commits `reference/TRACEABILITY.md`, mapping each of the 58 to port / replace / drop with an owning task. |
| B8 | **Moving the reference code breaks things** ✓ (`tests/conftest.py` imports `operations_copilot`; `verify_handoff --reference-code` and manifest paths; root `pyproject` / Makefile / Dockerfile / compose). ADR-0001 says T04 ✓; AM-01 and T07 say T07. | **T04** moves the reference (pyproject, `src/`, `tests/`, Makefile, Dockerfile, compose) into `reference/` together, with a remapped hash file and a `--reference-code` pass in its DoD. Align ADR-0001, AM-01 and T07. |
| B9 | **The checker breaks on the schema rename.** ✓ `verify_handoff.py` reads `decision-valid.json["payload_sha256"]`, which AM-11 renames. `--contracts` ignores `schemas/tools/`. `jsonschema` is undeclared. | T07 updates `verify_handoff.py`. T04 adds `jsonschema` to the dev group. |
| B10 | **Holdout timing.** ○ Gold labels need T17's per-section IDs. T02's "adjust prompts" could count as tuning before the seal. T19 doesn't depend on T03. A local git history can be forged. | Split the holdout task. **T03a:** seal prompts and intents now. **T03b:** owner gold-labels against the frozen T17 corpus, then re-hash. T19 depends on T03a and T25 on T03b. The probe is declared *not* tuning. Push the seal hash to a remote, or another external timestamp, before T02. |
| B11 | **The T02 probe would use repeated inputs.** ✓ Only 10 dev seeds exist, so 30 calls on 10 inputs are clustered. There is no locked environment before T04. | Use ≥30 distinct inputs, or report at input level. Run in an isolated `uv run --isolated --with langchain-ollama==1.1.0` with the freeze saved. Measure the identical-repeat rate at temperature 0. T04 no longer depends on T02. |
| B12 | **Seed IDs and Keycloak topology.** ○ T05 and T07 both need tenant/persona UUIDs. The audience `http://mcp-server:8080/mcp` assumes container networking, but `iss` differs between host and container callers. The `sub` claim depends on KC 26 client scopes. | T04 creates `data/seed-ids.json`, which both tasks read. T05 fixes `KC_HOSTNAME`, states the dev topology, parameterizes the audience, and asserts that `sub` equals the Keycloak user ID. |
| B13 | **T08's scope is vague.** ○ "All services" vs "five processes"; "minimal auth" is throwaway work. | Name the processes: api, worker, mcp-server, incident-sim, plus Postgres and Keycloak. Use real T05 client-credentials tokens. T08's schema becomes Alembic revision 1, which T09 extends. |
| B14 | **The T01 venv would land inside the repo.** ✓ (`.gitignore` only covers `.venv/`; the checker scans the whole repo with `rglob`). | Put the venv outside the repo. The checker skips venv and `node_modules` directories. |

## LATER (attach to owning task)

| Owning task | Notes |
|---|---|
| T09 | RLS bootstrap: an RLS-free `run_directory(run_id, tenant_id)` plus a named cross-tenant sweeper policy (resolve_invocation, expire_proposals, membership sync, session lookup). The definer function declares `SET app.tenant_id` as a function attribute. Gate the test-time offset in `app.current_time()` by profile. Add an AM-20.7 checkpoint-schema permission test with its own requirement. |
| T10 | Shared `core.testing.faults` (R098 co-owned with T13). Run the destination at READ COMMITTED. Restate `GET /internal/actions/{id}`. |
| T11 | Keycloak down/slow → fail closed with 503 `retryable`, 2 s timeout, cached service-account token. The "grants blocked ≤60 s" half is tested in T21. |
| T13 | Any transaction that will write `run_lease` takes FOR UPDATE from the start (no lock upgrade). Owner re-fence path that hands the new fence to the heartbeat. Lock order adds memberships, jobs, invocation_context, model_permit and sessions. Heartbeat renewal gated on event-loop liveness and the 90 s compute budget. |
| T15 | The "status=error only before grant" rule applies to authorized callers only (no action_id leak). Allowlist checks attempt state, not only run state. |
| T20 | LangGraph 1.2.14 ✓: an explicit `checkpoint_id` makes `is_replaying=True` and pending writes are **not** re-applied (`_loop.py:330, 766-770`). `Command(resume)` keeps RESUME writes; `invoke(None, checkpoint_id)` is time travel and forks (`:886-912`). So: store the checkpoint ID from `stream_mode="checkpoints"` or `aget_state`, update it after forks, make *every* node idempotent, test kill-mid-superstep and kill-at-interrupt, and join stale in-process tasks before re-acquiring. |
| T21/T22 | **Asset guard needs a shared lock**: `pg_advisory_xact_lock(tenant, asset)` placed before `runs` in the lock order. Otherwise two conversations can both grant. Redispatch skips the §13 gate (linearization already happened) and goes through `lookup_action`. Abort timing after SENT is immediate on cancel, otherwise at the deadline, with the up-to-5-minute FAILED latency stated. R046's post-grant half moves to T22. |
| T24 | Update card vocabulary: DEV-018 → ESCALATED; DEV-015 → SUCCEEDED with note; DEV-017 → time-bounded; DEV-008 → lazy BLOCKED_REVIEW commits even when the decision returns 409. Add cards for escalation, tombstone, asset guard and the operator resolution. Fault-injectable outbox sink for DEV-029. Depends on CI with Postgres (T31) or runs locally until then. Update the eval README (80/40 and the separate-reviewer text are stale). |
| T26 | Add ANSWERED and CANCELLED to the UI states. State 8 (reconnect) needs SSE from T27; move that assertion. |
| T30 | Enforce one worker replica (startup advisory lock; a second worker refuses to start, with a test). |
| T25 / eval | **Statistics** ○: case-level Wilson at 20/25 is 0.61–0.91. Exact McNemar power at n=25 is 0.14–0.17 for a 15-point difference and 0.48–0.81 for 30 points, so **~30 points is the 80%-power floor**. Change AM-50's "15–20" sentence. The ≥2/3 rule inflates rates (0.70 per trial → 0.78 per case); safety gates are **any-trial**. **Bias:** the owner authors the holdout, writes condition A and labels groundedness. Restrict A to deterministic metrics; blind B/C labelling with shuffled anonymized outputs; re-label ~20% for intra-rater kappa; add a schema and check for `quality-gates.json`. Rule-of-three bound at n=25 is 12%. |
| Graph | T16 (M05) depends on T17 (M06): move T17 to M04. R002 → T34; R031 → T04; R071 co-owned by T25; R097's milestone is shown as M09 although it can't close before T32. T06 needs a public repo at M01 while publication approval sits at T34; the owner decides (approve early publication or use a private repo first). |
| Spec text | Unamended BUILD_SPEC text conflicts: §23 (kind smoke and SBOM as mandatory), §21 profile names vs dev/test/demo, §9 `ops-mcp` audience and "distinct scope", §6 job lease/fence. Cover these with an explicit precedence list in AM-00. |

## Recomputed critical path (task count; durations unmeasured)

- **Current:** 16 tasks: T01→T02→T04→T05→T08→T09→T13→T15→T16→T20→T21→T22→T26→T27→T33→T34.
- **With B11** (T04 no longer depends on T02) and the seed-ID file: 15 tasks. T02, T03a and T07 move off the path.

# Adversarial review: Operations Copilot build handoff

**Reviewed:** `operations-copilot-ai-build-handoff.zip` (BUILD_SPEC OPS-BUILD-1.0, tasks, acceptance matrix, schemas, reference code, fixtures, evals, deploy templates).
**Date:** 2026-10-06.

**Method:**
- Six adversarial reviewers each read the package independently, without running any of its code. Their lenses were evidence/reproducibility, internal consistency, security, distributed-systems correctness, citations/library facts, and scope/feasibility/evals.
- The lead reviewer spot-checked their findings.
- Every claim started as UNPROVEN.

**Legend:**
- ✓ = verified first-hand by the lead reviewer (file read, command run, or live source opened).
- ○ = reviewer finding not re-verified by the lead (plausible, cited with file:line).
- ✗ = reviewer finding rejected on re-check.

## Bottom line

The package is unusually honest: it labels the reference as a reference, keeps unbuilt gates open, and never claims a real-model, MCP, Docker or Kubernetes success it doesn't have. **The architecture is sound and should be adopted.**

It should **not** be adopted as-is as an "authoritative contract":
- It has state-machine holes, crash windows with no recovery path, and a task graph that can't be executed in the stated order.
- It has a privilege problem at the MCP write boundary and a few stale library facts.
- Its full v1 scope (estimated 4–7 solo months) buries the most interviewer-visible MLOps work, evaluation, behind Kubernetes and restore drills.

**Recommendation:**
1. Adopt BUILD_SPEC with a short **SPEC_AMENDMENTS / ADR set** that fixes the items marked *Must fix* below.
2. Adopt the **reduced v1 cut** at the end of this document.

---

## 1. What is PROVEN

| Claim | Evidence |
|---|---|
| Package integrity (161 checksums, 32 acyclic tasks, 80 mapped requirements) | ✓ `verify_handoff.py --manifest --reference-code` printed PASS locally. *Caveat: self-referential hashes, and "80 covered" means mapped to a task, not tested.* |
| Recovery demo: lost response → OUTCOME_UNKNOWN → reconcile → exactly one incident | ✓ `python -m operations_copilot.cli` run locally; events 6→7 |
| 58 reference tests exist and passed **on Linux** | ○ 58 test cases counted; `reports/handoff/reference-tests.xml` says 0 failures. ✓ **Not reproduced on this Windows machine** (FastAPI not installed; isolated test run blocked by permission). |
| All 11 JSON schemas are valid Draft 2020-12; all 29 positive/negative examples behave as labelled | ○ consistency reviewer, using jsonschema 4.26.0 |
| Proposal example hash = sha256(canonical JSON v1) | ○ recomputed by the consistency reviewer |
| Most citations (LangGraph interrupts, ChatOllama, Ollama structured output, SKIP LOCKED, RLS caveats, NetworkPolicy, uv, GitHub Actions, OWASP, Anthropic evals) match the live sources | ○ citations reviewer opened each URL |
| MCP SDK v2 uses `MCPServer` / `Client`; `langchain.mcp` is beta | ○ citations reviewer |
| Approval bound to exact hash/revision, first decision wins; grant as the linearization point; same-key/different-hash conflict | ○ security reviewer: well-specified (§13:464–472, §14:497) and enforced in the reference (`service.py:131-143`, `synthetic.py:159-173`) |

## 2. Must fix before building (critical/high)

### A. State machine and recovery

1. **No recovery for a crash between grant and dispatch.** ✓
   - In the reference, `service.py:175-178` commits EXECUTING, then calls the destination. If the process dies in between, `execute` refuses (`:157`) and `reconcile` raises without saving (`:213-216`). The run is stuck forever.
   - The spec defines only crash window (c), "destination committed, response lost". Undefined windows:
     - (a) grant committed, dispatch not recorded
     - (b) dispatch recorded, I/O not sent
     - (d) receipt received, not persisted
   - The destination also has no way to *create* the "authoritative no-commit" record that §14 relies on.
   - **Fix:**
     - An `action_attempt` record that moves INTENT → SENT → RESOLVED.
     - A destination `POST /internal/actions/{id}/abort` that writes a no-commit tombstone and rejects late arrivals.
     - Rule: cancellation or dispatch-deadline expiry → abort; otherwise redispatch with the **same** key.
2. **CONFLICT has no run state.** ✓ §10:391 and §14:497 say "CONFLICT; stop and escalate", but §8:307 has no such state. **Fix:** add `ESCALATED`, or map CONFLICT explicitly.
3. **OUTCOME_UNKNOWN never ends, and it blocks the conversation**: "one active investigation per conversation", §8:334. ○ **Fix:** a terminal `ESCALATED_UNRESOLVED` that frees the slot while reconciliation keeps running.
4. **Fencing is per job, but work is per run.** ○
   - A resume job leased with fence 1 on its *own* job row can race the original job's late checkpoint write for the same thread.
   - **Fix:** one lease and one monotonic fence **per run**. All job types acquire it, and both app and checkpoint writes check it.
5. **"Fence checkpoint writes" needs a custom saver.** ○
   - `PostgresSaver.put/put_writes` run sealed upserts with no transaction hook.
   - A stale worker doesn't overwrite a checkpoint. It inserts a *new* `checkpoint_id` that becomes the latest one (head hijack).
   - **Fix:** subclass the saver and check the lease or fence inside each write transaction. Alternatively, adopt the spec's allowed single-writer profile via an ADR and keep the distributed-worker gate open.
6. **A model call outlives its lease.** ○
   - Model attempt: 60 s (§12:441). Lease: 30 s with a 10 s heartbeat (§8:332).
   - If inference blocks the heartbeat, a second worker reclaims the run and starts a second model call.
   - **Fix:** run the heartbeat as an independent task, cancel inference on lease loss, and use a DB-backed model-concurrency permit.
7. **Two incidents per run are possible.** ○ The grant is unique per `(proposal_id, action_type)` (§6:234), so a revision approved while revision 1 is in flight gets its own action. **Fix:** one active grant per run, and refuse revisions once any grant exists.
8. **It's unclear what a `proposal_id` identifies.** ○ The decision endpoint uses `proposal_id` + `expected_revision`, which implies a stable ID. `create_incident(proposal_id)` and the grant's uniqueness rule imply one ID per revision. **Fix:** pick one rule. Recommended: an immutable ID per revision.
9. **The transitions are incomplete.** ○
   - RETRIEVING/DRAFTING has no transition to AWAITING_INPUT, although §11:415 says "ask".
   - APPROVED has no transition to revision.
   - REJECTED is never stated to be terminal.
   - Nothing triggers AWAITING_APPROVAL → BLOCKED_REVIEW on expiry.
   - Clocks for expiry/freshness are unspecified; they should use database `now()`.
   - Per-run event sequence allocation is unspecified. A PG SEQUENCE commits out of order, so SSE can skip events. Allocate it under a run row lock instead.

### B. Security

10. **The MCP server holds write access to the authority tables.** ○
    - Doing the grant transaction inside the MCP boundary (§13:470) means the MCP DB role needs read access to runs, proposals, decisions, memberships and invocation contexts, plus write access to grants and runs. It also needs that across tenants, because it resolves the handle before it knows the tenant.
    - That puts the worker's blast radius behind a network listener.
    - **Fix:** the MCP role gets **no table grants**, only `EXECUTE` on two `SECURITY DEFINER` functions (`resolve_invocation`, `grant_execution`). Test: `SELECT * FROM proposals` as the MCP role returns permission denied.
11. **The worker sets its own tool allowlist.** ✓ §9:358 has the worker write "allowed tool names" into the handle. **Fix:** derive the allowed tools server-side from `job.type` (set by the API) and the run state.
12. **Separation of duties can be bypassed.** ○
    - The tenant-admin surface (§4:170) has no endpoint or test, and an admin can grant approver to a second identity.
    - The independence check covers only the "requester", not the authors of a revision or a manual proposal.
    - **Fix:**
      - Cut the admin surface from v1 and seed memberships through migrations.
      - Define "requester" as every content author.
      - Test that a reviewer cannot approve their own revision.
13. **A proposal isn't bound to the handle's run.** ○ Require `proposal.run_id == handle.run_id` and the same tenant. Test cross-run and cross-tenant proposal IDs.
14. **The reference graph writes full evidence text into checkpoints.** ✓ `integrations/langgraph_workflow.py:38` calls `interrupt({...,'proposal': run['proposal']})`. This contradicts §8 ("persist IDs") and §11:421. **Fix:** interrupt with `{run_id, proposal_id, hash}` only.
15. **Disabling a user in Keycloak doesn't end their app session.** ○ Add back-channel logout or re-introspection. Test: disable the user, and the next mutation returns 401.
16. **No mechanism is specified for:** ○
    - the destination's "trusted executor identity" (use a separate client and audience);
    - the checkpoint-table access model (separate schema, worker-only grants);
    - fault-hook isolation (a test-only app factory that refuses to start unless `PROFILE=test`);
    - the Keycloak audience mapper (client-credentials tokens lack `aud` by default).

### C. Contract consistency

17. **The task graph can't be executed in order.** ✓
    - All 32 tasks form one serial chain. T27 (evals) depends on T25/T26 (restore drills).
    - Requirements land in milestones before the capability they test exists:
      - R015 "jobs/events before 202" in M03, but jobs and events are built in M04;
      - R023 needs decisions and checkpoints from M07/M08;
      - R028 needs ingestion from M06;
      - R035 needs the UI from M09.
    - The chain also contradicts BUILD_SPEC:716, which says to start tests early.
    - **Fix:** re-home each requirement to the milestone where it becomes testable, and make evals depend on M07/M08.
18. **Every task shares one copied `definition_of_done`.** ✓ All 32 tasks have one identical value. Paired tasks share identical requirement IDs (T07 and T08 both list R011–R018).
19. **`external_approval_required: false` contradicts the spec.** ✓ It's false on T15 (real model), T28 (CI secrets) and T30 (publication), which conflicts with §26/§27.
20. **The event schema doesn't match §15.** ✓ The schema adds `explanation.ready`, and has no events for ANSWERED, INSUFFICIENT_EVIDENCE, BLOCKED_REVIEW, REJECTED, or clarification received. ○ Schema probes also accept `tool.completed` with status SUCCEEDED and `action.confirmed` with FAILED. Only `model_summary` is restricted from asserting status.
21. **The tool-result schema allows contradictory write outcomes.** ○ Envelope `ok` with data `UNKNOWN`/`CONFLICT`; `create_incident` returning `error` + `data:null`, which loses the action_id; SUCCEEDED with a mismatched hash. There are no input schemas for tool arguments, and no `next_cursor` for alerts.
22. **The fixtures don't fit the schemas.** ○
    - Alert IDs aren't UUIDs and have no revision.
    - Tenant is `"alpha"`, but the schemas require a UUID.
    - The evidence hash covers the whole file, but evidence IDs are per section.
    - `draft-valid.json` says "two warnings", but the alerts example returns `[]`.
23. **These spec requirements have no acceptance entry:** ○
    - feedback;
    - opposing decision → 409;
    - the §8 transition table;
    - 5-minute asset freshness;
    - the ANSWERED path;
    - the 401/403/404 mapping;
    - fault-hook isolation;
    - the 18 UI states;
    - Compose profiles;
    - audit events;
    - the tenant-admin surface.
24. **These numbers are undefined:** ○ the request-dedup replay window, the escalation deadline, and the dispatch deadline.

### D. Library facts and toolchain

25. **`integrations/mcp_tools.py:8` won't import.** ✓ `from mcp.server import MCPServer, Context` fails: live SDK source `mcp/server/__init__.py` exports no `Context`. Use `from mcp.server.mcpserver import MCPServer, Context`.
26. **MCP §10:376 and §19:587 describe the old `initialize` handshake.** ○ The MCP 2026-07-28 spec and SDK v2 are session-less, and the protocol version travels per request in `_meta`. Tests should check per-request version handling instead of "negotiation". Pin the protocol revision.
27. **The kind + Cilium default is misleading.** ✓ §22:650 says "default preference Cilium". ○ Since kind v0.24, kindnet enforces NetworkPolicy through kube-network-policies, and kind says it does not support third-party CNIs. Use the default kind CNI and keep the real allow/deny tests.
28. **The model path has no dependencies.** ✓ `pyproject.toml` has no `langchain`, `langchain-core` or `langchain-ollama`, and no lockfile, so transitive dependencies float. `jsonschema` (needed by `--contracts`) is undeclared.
29. **Model runtime gaps for qwen3:8b.** ✓
    - `models.py:46-63` sends no `think:false`, caps `num_predict` at 700, sets no `num_ctx`, and silently ignores the thinking field.
    - qwen3 thinks by default, so this risks truncated JSON and conflicts with the no-chain-of-thought rule.
    - The 12k-token input budget in §17 has no matching `num_ctx`.
30. **Unsupported attributions.** ○ "Not external exactly-once" is attributed to S01, which doesn't say it. "Temperature 0 doesn't guarantee identical outputs" has no source. Re-cite these, or label them as project reasoning.

### E. Reproducibility and deploy templates

31. **The reference isn't reproducible from a clean clone:** no lockfile, and the 58-pass evidence comes from a Linux container only. ✓/○
32. **`compose.yaml` may not be reachable.** ✓ Its only network is `internal: true` while it publishes `127.0.0.1:8000`; Docker likely won't expose the port. ○ Confirm with `docker compose up` and `curl`.
33. **The CI template needs a nonexistent `requirements.lock`.** ○ Several file pointers also reference docs moved to `docs/archive/`.
34. **Weak tests.** ○
    - `test_duplicate_decision_and_execute` compares a result with its own early-return copy, so it can't fail on a dedup bug.
    - There's no concurrent `execute()`/`decide()` test.
    - The proposal hash is stored in the same row as the body, so it detects only inconsistent edits, not tampering.
35. ✗ *Rejected:* "stale `.pytest_cache`/`__pycache__` shipped in the package." Those were created by the lead reviewer's local runs; the zip listing contains neither.

## 3. Scope, feasibility and evaluation

- **Effort** (reviewer estimate, unmeasured): full spec ≈ **87–136 solo days (4–7 months)**; reduced cut ≈ **54 days (~2.5 months)**.
- **The evaluation data can't support the §20 claims.** ✓
  - The 8 fixture docs total 463 words, smaller than one specified 300–600-token chunk, so chunking and the lexical-vs-pgvector comparison are meaningless.
  - Of 32 scenario cards, only about 2 are model-quality cases (○). The rest are deterministic workflow tests, which repeated model trials don't help.
  - With a 40-case holdout, "zero unauthorized writes" only bounds the rate at about 7.5%.
  - No CIs are required, `evals/quality-gates.json` doesn't exist, and §27 needs a holdout reviewer the solo owner doesn't have.
- **Resources:**
  - Compose + Keycloak + Postgres + 5 services + kind + a full observability stack, alongside Ollama, likely won't fit together in Docker Desktop's VM (estimate). Don't plan on running Compose and kind at the same time.
  - qwen3:8b on 10 GB VRAM at 16k context leaves little headroom (estimate). Measure it.
- **Gold-plating with low interviewer value:**
  - kind + Cilium;
  - paused-version upgrade rehearsal;
  - SBOM/provenance;
  - 6 DB credentials + RLS everywhere;
  - tenant switching and session rotation;
  - 18 UI states;
  - the full Grafana/Tempo/Loki/Prometheus stack;
  - the fenced distributed checkpointer.

## 4. Recommended v1 cut

| Keep / change | Notes |
|---|---|
| M00–M02 | Postgres + separate destination DB. RLS on tenant tables with 2 roles (migrator, runtime). MCP via `SECURITY DEFINER` functions (fix 10). |
| M03 | Keycloak + authlib, 5 seeded personas, server-side session cookie + CSRF. No admin surface. |
| M04 | Run-level lease and fence on app writes. **Single-writer checkpoint profile via ADR** (distributed-checkpoint gate stays honestly open). |
| M05–M08 | In full, with fixes 1–14. This is the core story. |
| **Evals moved to right after M08** | (a) The 32 cards as a deterministic pytest scenario suite. (b) ~60 dev + ~25 owner-authored, hash-locked holdout model cases, 3 trials each. Schema-valid rate, citation validity, abstention accuracy, groundedness, all with Wilson CIs. `quality-gates.json` frozen before the holdout run. Expand the corpus to ≥12 docs of several hundred words and ≥6 assets. |
| M09-lite | React with 3 panels and ~8 states, SSE replay, 3 Playwright flows. |
| M10-lite | OTel collector + one trace backend + redaction tests. |
| M11 | Compose only, hardened images, CI (ruff/mypy/pytest/PG integration/image scan). |
| M12-lite | Retained-receipt restore demo + `docker kill worker` recovery demo. |
| Deferred to v1.1 | kind/Helm, upgrade rehearsal, SBOM/provenance, distributed fenced checkpointer, full observability stack, extra DB credentials, Slack/cloud. |

## 5. Repository layout (owner request)

**ADR-0001: Deployable units as top-level directories** (amends BUILD_SPEC §5 layout only). Each independently deployed process gets its own top-level directory with its own Dockerfile, entrypoint, tests and README:

- `api/`
- `worker/`
- `mcp-server/`
- `asset-sim/`
- `incident-sim/` (own database)
- `web/`

Domain, application and adapter code lives in one shared library, `core/`, a uv workspace member that every service imports.

No domain logic is duplicated or exposed over the network. §3's rule still holds: MCP and the destination are the only deliberate network boundaries, and API and worker may share a base image.

## Appendix: ChatGPT stage images vs. the authoritative charts

The package's `docs/diagrams/png` are the "Analysis output 1–6" images. The ten "ChatGPT Image …" PNGs contain these errors.

**Errors common to several images:**
- **Channels:** CLI, Slack bot input and voice. The spec is web-first, Slack is notifications only, voice is deferred, and there is no CLI.
- **Model:** "Ollama or OpenAI". The spec uses local Ollama only.
- **Frontend:** React/Next.js. The spec uses React + TS + Vite.
- **Data:** "synthetic or real" plus CMMS/ITSM. The spec is synthetic only.
- **Feedback:** automatic feedback → prompts. The spec requires reviewed, gated changes.
- **Status:** "Production-Ready". The spec says target design, not live.

**Errors per image:**

| Image | Fix |
|---|---|
| -1 (Stage 1) | Channels; "A real user input" → synthetic |
| -2 (Stage 2) | Output should go to Stage 4 reads before Stage 3; subtitle "Plan" → "Admit & coordinate" |
| -3 (Stage 3) | "Retrieve" belongs to Stage 4; input comes from Stage 4 evidence; the model doesn't pick tools; output should be a frozen proposal → Stage 5 |
| -4 (Stage 4) | Input comes from the worker's allowlisted calls; remove the model-supplied "Permission scope"; remove the "Proposed action" output |
| -5 (Stage 5) | Input should be the frozen proposal from Stage 3 |
| -6 (Stage 6) | Feedback gating wording |
| 06_57_35 (overview) | Model picks tools / Stage 3 → tools order; Stage 4 proposes; common items |
| -7 (end-to-end) | "Chain of Thought"; RAG in Stage 3; Stage 3/4 outputs; LangChain-MCP as primary; typos "LangiChain", "Retruned", "Reetuned dction", "tooI" |
| -8 (detailed v2) | Chain-of-thought; **"exactly-once semantics"**; 3→4→5 routing; email/in-app alerts; typo "llayer" |
| -9 (stage-by-stage) | Reasoning/tool calling/RAG in Stage 3; "stored and queued" in Stage 1; SSE/WebSocket; email; Stage 4 proposes |

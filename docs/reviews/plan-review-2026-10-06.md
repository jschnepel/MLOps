# Adversarial review: amended plan OPS-BUILD-1.1

**Reviewed:** `SPEC_AMENDMENTS.md`, ADR-0001, ADR-0002, `handoff/tasks.json` v1.1, `handoff/acceptance-matrix.json` (commit `731dbbe`).
**Date:** 2026-10-06.

**Method:** four fresh adversarial reviewers, none of whom took part in round one:
1. completeness and consistency;
2. correctness of the new mechanisms;
3. task graph, feasibility and evaluation;
4. library and protocol facts, checked against downloaded package source (mcp 2.3.0, langchain-ollama 1.1.0, langgraph 1.2.14, langgraph-checkpoint-postgres 3.1.2, authlib 1.8.0) and official docs.

The lead reviewer then spot-checked their findings.

**Legend:** ✓ verified by the lead · ○ reviewer finding, not re-verified · ✗ rejected on re-check.

## Bottom line

The amendment **did its main job**. Of the round-one findings, about 15 are fully closed and most of the rest partly closed. The task graph now puts each requirement in the milestone where it becomes testable, and every task has its own definition of done ✓ (35/35 distinct).

But the amendment **introduced new defects, and the plan is not ready to build from:**
- 3 critical issues in the execution path;
- several mechanisms that don't match how the libraries actually behave;
- schemas, examples and fixtures that now contradict the contract and have no task to update them;
- an evaluation design that cannot support most of the claims it implies.

It needs a short **OPS-BUILD-1.2** pass before the implementation plan.

## Critical

1. **Nobody can record the execution protocol.** ✓
   - AM-20.1 gives `mcp_exec` only `resolve_invocation` and `grant_execution`.
   - AM-13 needs `action_attempt` writes (INTENT/SENT/RESOLVED), receipt persistence, abort and redispatch. AM-20.2 also allows `create_incident` only in APPROVED, which makes same-key redispatch from EXECUTING impossible.
   - **Fix:** either the worker owns dispatch and recording (MCP only grants and forwards), or add fenced definer functions such as `mark_sent` and `record_outcome`, plus abort/redispatch tools in the allowlist. Choose one and specify it.
2. **A fence check without a lock does not fence.** ✓ (AM-12 text)
   - A plain `SELECT` of `run_lease` under READ COMMITTED lets a stale worker commit after a new fence has been issued.
   - `now()` is the transaction start time ✓ (PG docs, per the reviewer), so a long transaction passes the expiry check after the lease has actually expired.
   - **Fix:**
     - `SELECT … FOR SHARE` (or a conditional `UPDATE … RETURNING`) first in every fenced transaction, with acquisition `FOR UPDATE`;
     - use `clock_timestamp()` for the expiry comparison;
     - publish one lock order: `run_lease → runs → proposal → execution_grant → events`;
     - test it with a two-connection interleaving test.
3. **Tombstones have no retention rule and no shared key.** ✓ (AM-13 defaults table)
   - An expiring tombstone lets a delayed POST commit behind a FAILED run.
   - If tombstones and incidents live in separate tables, an abort and a POST in flight can both commit.
   - INTENT has no deadline when the destination is unreachable.
   - **Fix:** one destination table `action_key(action_id PK, state COMMITTED|ABORTED)`, both writers using `INSERT … ON CONFLICT`, tombstones never expired. Apply the escalation deadline to INTENT too.

## High

4. **Checkpoints lag side effects by default.** ✓ The LangGraph default is `durability="async"`, which means "persisted asynchronously while the next step executes" (`langgraph/types.py:98-103`, `pregel/main.py:2672`). **Fix:** require `durability="sync"`. Store the accepted `checkpoint_id` on the run under the fence after each step, and always resume from that one. That covers the stale-head and pending-writes overwrite scenario ○.
5. **`PostgresSaver` has no schema parameter.** ✓ It runs unqualified `CREATE TABLE checkpoints` (`checkpoint/postgres/base.py:47`). `setup()` also needs autocommit (for `CREATE INDEX CONCURRENTLY`) and CREATE privilege ○. **Fix:** the migrator runs `setup()` with `search_path=checkpoints`; the worker gets DML only, through its `search_path`.
6. **The SECURITY DEFINER functions aren't hardened.** ○ (PG docs)
   - They need `SET search_path = app, pg_temp`, and `REVOKE ALL … FROM PUBLIC` in the same transaction as the CREATE.
   - Table owners bypass RLS, so the definer role must not own the tables, or the tables need `FORCE ROW LEVEL SECURITY`.
   - `resolve_invocation` drops the workload-client (`azp`) binding.
7. **The user-disable rule contradicts itself.** ○
   - "Re-validate every 5 min" contradicts "next mutation gets 401".
   - Back-channel logout fires on logout, not on disable.
   - authlib 1.8.0 has no back-channel helper ✓ (per the reviewer's grep).
   - Since Keycloak 26.6.2, introspection returns inactive unless the caller is in `aud`.
   - **Fix:** check user status on every decision or grant mutation, using the admin API or introspection with `api` in `aud`. Hand-write the back-channel endpoint. Pin Keycloak 26.8.x.
8. **The MCP SDK's token-audience check expects a URL.** ○ The built-in `resource_server_url` check parses `aud` as a URL, so `aud="ops-mcp"` fails. **Fix:** set the audience to the MCP URL, or write a custom `TokenVerifier`.
9. **The "single-writer" profile allows multiple writers.** ✓ ADR-0002 allows replicas, which reverses BUILD_SPEC §8:338 and §22:654 without a test of the mitigation. **Fix:** v1 runs **one** worker replica in the demo profile. Multi-replica becomes an explicit experiment, not a claim.
10. **A transport timeout before the grant leaves no action_id.** ○ **Fix:** on timeout, take the lease row lock, revoke the handle, then read `execution_grant` by `run_id`. That read is the linearization point.
11. **Cancelling the model call is unproven.** ✓ (AM-12 assumes it)
    - The client can cancel its request; whether Ollama stops generating is contested ○.
    - The heartbeat can be starved by sync calls.
    - **Fix:**
      - only `AsyncPostgresSaver` and `ainvoke`;
      - the heartbeat on its own thread and connection;
      - add a probe to T02 measuring GPU and `ollama ps` after a cancel.
12. **Semantic changes left unreconciled.** ✓/○
    - `action.failed` and `action.aborted` events are undefined ✓.
    - "Cancel after grant → abort" changes §8:322 and R046 ○. That is acceptable only before dispatch, with a tombstone, and must be stated.
    - The no-commit outcome has three names: `ABORTED_NO_COMMIT`, `FAILED_NO_COMMIT`, FAILED.
    - The partial-index carve-out (AM-11) is unreachable given §6's `unique(proposal_id, action_type)` ✓, or else it mints a new identity. Remove it.
13. **ESCALATED → SUCCEEDED can silently duplicate an incident.** ○ ESCALATED frees the conversation slot, so a new run for the same asset and interval can create a second incident. **Fix:** block or warn on a new incident for the same asset and interval while an escalated action is unresolved, and keep SSE open on ESCALATED.

## Task graph and plan quality

14. **R097 "all 32 cards" can't close in v1.** ✓ T19 depends only on T18. Nine cards need later tasks: SSE (T22), budgets (T24), restore (T27), and two optional M15 tasks (T31, T33) ○. **Fix:** v1 requires 30 cards; DEV-013 and DEV-032 are deferred. T19 depends on [T18, T22, T24, T27]. The fault factory (R098) moves to T09, where tests first need it.
15. **Missing dependencies and false serialization.** ✓/○
    - T06 and T11 need Keycloak workload clients but don't depend on T07 ✓.
    - T08 and T09 don't need OIDC.
    - T13's corpus needs only T05.
    - Requirements sit before their prerequisites:
      - R023 needs decisions → T17;
      - R022 needs review pauses → T16;
      - R035 and R014 need the UI → T21;
      - R070 condition A needs the manual path from T21.
16. **Missing tasks:** ○
    - **dev bootstrap:** Compose for Postgres + pgvector, Keycloak and the Ollama bridge; Windows secret generation; seed UUIDs;
    - **early secret-free CI** after T03;
    - a **walking skeleton** with fake model, real Postgres and real HTTP across all services before hardening;
    - moving the reference to `reference/`;
    - authoring dev eval cases, gold labels and the rubric;
    - **schema, example and fixture updates for the amendments** (decision field name ✓, event enums ✓, tool envelope, receipt example, draft/alerts example, `index.json` version, catalog UUIDs).
17. **Requirements without tests or entries.** ✓ R081–R100 all have `suggested_test: null` (20 of 20). There are still no entries for feedback, the ANSWERED path, the 401/403/404 mapping, asset freshness, or the 8 UI states. R066 is blocking at M12 but its text is about pods and a CNI. Split it into a Docker part and a cluster part. *(The reviewer's claim that "R066 is owned only by T30" was ✗ rejected: T25 also owns it.)*
18. **Effort.** The planning reviewer's own estimate is about **108 days** for M00–M14, against ADR-0002's 54. Both are unmeasured. Tasks of about 5 days or more should be split: T18, T20, T21, T19, T05, T07, T11, T16, T17, T25. ADR-0002 should state the range rather than one number.

## Evaluation design

19. **The precision numbers, recomputed** ✓ (Wilson 95%):

    | Sample | Observed | 95% interval |
    |---|---|---|
    | 25 holdout cases | 90% | [0.725, 0.968] |
    | 25 holdout cases | 100% | [0.867, 1.0] |
    | 75 trials | 90% | [0.811, 0.950] |
    | 30-call probe | 27 of 30 | [0.744, 0.965] |

    - The probe **cannot justify the 90% gate in AM-31.** Use the post-repair valid rate as a recorded measurement plus an owner decision, not a fixed gate.
    - The 3 trials per case are clustered, so report case-level intervals or a cluster bootstrap.
    - A/B/C differences under about 15–20 points are undetectable. Use paired McNemar tests and make no ranking claims without significance.
    - Schema-valid rate doesn't apply to the manual condition A.
    - `quality-gates.json` has no defined content.
    - Hash-locking proves the holdout wasn't modified, not that it wasn't leaked: the agent can read the owner's disk. Keep it off-machine or encrypted until the run, and author it **now**, before any prompt tuning.
    - Owner labelling load is roughly 765 outputs, and has not been estimated ○.

## Facts confirmed (no change needed)

○ per the facts reviewer, with ✓ where the lead checked the source:
- MCP 2026-07-28 is session-less, with the version per request in `_meta`, and the header must match.
- `mcp` 2.3.0 imports work as amended.
- `Context.headers` exists (the SDK warns that headers are not an identity).
- `ChatOllama(reasoning=…)` maps to Ollama `think` ✓ (`chat_models.py:804`); `with_structured_output` defaults to `json_schema`.
- Ollama's default context is 4k under 24 GiB of VRAM, so the explicit 16384 is required.
- kind's default CNI enforces NetworkPolicy since v0.24.
- pgvector does exact search by default.
- Wilson and rule-of-three are appropriate.
- authlib supports PKCE. Note that it keeps OIDC state in a signed client cookie, not the server-side opaque session the spec requires.

**Version corrections:**

| Component | Correction |
|---|---|
| Ollama | latest 0.35.1 (spec says 0.33.x) |
| Keycloak | 26.8.0 |
| kind | v0.33.0 |
| nomic-embed-text | requires the `search_document:` / `search_query:` prefixes |

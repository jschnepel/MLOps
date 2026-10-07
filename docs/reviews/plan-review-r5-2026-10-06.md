# Adversarial review, round 5 (spec-wide): OPS-BUILD-1.3.1

**Reviewed:** commit `4a5f45e`, with the CR-escape fix in `b09b08f`.
**Date:** 2026-10-06.

**Method:** four fresh reviewers over the whole amended contract:
1. consistency;
2. security footholds;
3. run-lifecycle failure injection, using the langgraph 1.2.14 source;
4. value and feasibility from an interviewer's view.

Reviewers were told not to re-report earlier findings unless those were still unaddressed. The lead spot-checked the findings. **Legend:** ✓ verified by the lead · ○ reviewer finding.

## Bottom line

| Measure | Result |
|---|---|
| Critical findings | **None** |
| New findings | About 35 (10 consistency, 9 security, 9 lifecycle, 6 value), plus 5 re-reports |
| High severity | 6 |

**Held up:**
- the lock order (acyclic for every named transaction);
- cancel / `mark_sent` / abort for a single run;
- crash recovery at each step boundary;
- hash-bound approval;
- the prompt hashes;
- task/matrix consistency.

**The pattern** ✓: each round's fixes add new mechanisms (definer functions, tombstones, operator states, locks), and the next round finds gaps *in those additions*. The spec is not converging by more spec review. The value reviewer argues it is now **over-engineered for a portfolio**, with nothing showable until about the 33rd task.

The owner now faces a scope decision: keep hardening the text, or simplify and build (see "Decision needed").

**Fixed during this round:** my 1.3.1 edit had written a real CR/LF where the literal `\r` belonged ✓, in `SPEC_AMENDMENTS.md:523`, `BUILD_BACKLOG.md` and `tasks.json` T07. Fixed in `b09b08f`.

## Live environment issue (outside the spec) ✓

Ollama on the owner's machine listens on `0.0.0.0:11434` (`OLLAMA_HOST=0.0.0.0:11434`). Two firewall rules allow `ollama.exe` inbound on **any port from any address, on both Public and Private profiles**. The machine's active networks include public Wi-Fi, Radmin VPN and Tailscale. Ollama has no authentication, so anyone who can reach that port can run, pull, delete or replace models. The lead changed nothing. **The owner should decide** whether this is intentional (it may serve the `portal` stack).

## High

| # | Finding | Owner |
|---|---|---|
| H1 | **No privilege matrix for the api, worker and sweeper roles** ○. Only `mcp_exec` is restricted, so a compromised worker could INSERT a decision that `grant_execution` honours, and "immutable"/"append-only" are unenforced. | T09: a role × table matrix in AM-20; decisions and freezing via definer functions; no UPDATE/DELETE on audit tables; a new requirement |
| H2 | **The MCP server cannot implement `search_procedures` or the asset-access reads** ✓. AM-20.1 gives `mcp_exec` six functions and no table access, and none of those functions reads the governed store. | AM-20.1 / T09 / T16: add read definer functions |
| H3 | **A second incident after the first succeeds** ○. The asset guard blocks only *unresolved* actions, so two conversations approved for the same asset and interval yield two incidents once the first completes. | **Owner decision** (is that intended?), then T21/T22 |
| H4 | **The kickoff prompt and START_HERE contradict the contract** ✓. They name BUILD_SPEC as the "single authoritative contract", demand "tested Kubernetes", and cite 32 tasks / 80 requirements. README:9 also claims tested Kubernetes. | Before T06 publishes the repo |
| H5 | **The time-offset gating mechanism is unsafe** ○. If the offset is a session setting, any role (including `mcp_exec`) could shift time and bypass every expiry, deadline and lease. | T09: read it from a test-profile-only table that runtime roles cannot write |
| H6 | **"MLOps" is thin, and there is nothing showable early** ○. About 13 of 123 requirements concern eval, model, prompt or retrieval. There is no run manifest, no eval regression gate in CI, no feedback → eval-candidate loop, and no 5-minute demo. | T25 / T21 / T31; a "v0.5 showable" milestone |

## Blocks start (T01–T08)

| # | Finding | Fix |
|---|---|---|
| S1 | H4 (kickoff / START_HERE / README) ✓ | Rewrite to the precedence rule; drop the Kubernetes claim; current counts |
| S2 | **Job types are never enumerated** ○, yet the tool allowlist depends on them | A job-type table (creator, allowed tools, run states) in AM-15 |
| S3 | **The tombstone shape is undefined, and `rejected` has no key state** ○ | Define the tombstone fields; persist rejections as a permanent key state |
| S4 | **An asset-guard refusal has no transition** ○, so the run sticks in APPROVED and holds the slot | → BLOCKED_REVIEW, reason `asset_action_unresolved` |
| S5 | **`state_version` semantics are unspecified** ○: if events bump it, cancels and decisions get spurious 409s | Only transitions bump `state_version` |
| S6 | **Cancel in INTENT ends FAILED without a reason saying so** ○ | Reason `cancelled_before_send` |
| S7 | **Round-4 "fix in task" notes never reached `tasks.json`** ✓: the T03 hash procedure; T05's Postgres pin, placeholders, test client and `host.docker.internal` warning; the sweeper/operator roles (AM-02, AM-10 still says "migrator connection") | Add them as review notes; edit AM-02 and AM-10 |
| S8 | **`--manifest` fails today** ○ (10 files), and T04 breaks about 15 more, but START_HERE lists it as the first check | Declare MANIFEST a frozen 1.0 snapshot, or extend the remap |
| S9 | **T05 network and secrets** ○: bind every published port to 127.0.0.1; verify the model digest at warm-up; keep secrets outside the repo (`%LOCALAPPDATA%`, Compose `secrets:`); delete the temporary Keycloak admin after import | T05 DoD |

## Later (owning task)

- **T09:** handles are passed raw and hashed inside `resolve_invocation` (the stored hash must not be a credential). Worker revocation goes through a definer function or a fence bump.
- **T10:** incident-sim checks `azp` as well as `aud`. Add a detective check that every destination key matches a grant hash.
- **T11:** membership sync fails closed (grants refused if the last sync is older than 120 s; a deleted user maps to 401). The admin check runs before the DB transaction. Back-channel logout gets signature, `alg` allowlist, `exp` and `sid` checks plus a durable `jti` store. A logging redaction filter starts here, not in T28.
- **T20:** a fork checkpoint is written **without blocking** ✓ (`_loop.py:1262-1266`); `durability="sync"` waits only after the tick ✓ (`main.py:3526`); forks are conditional ✓ (`:920-926`). So: store only IDs confirmed by `aget_tuple`, prefer `Command(resume)` when a resume event exists, and test two crashes in a row. Revision re-entry into the graph needs definition.
- **T21:** manual proposals are tenant-scoped. The guard predicate is "grant exists and attempt unresolved", applied atomically.
- **T22:** the abort path after a `cancelled` result is owned inside `create_incident` via a specified `request_abort`. Allow abort after ABANDONED (the tombstone becomes late evidence), with a bounded reconciliation budget.
- **T26:** a table mapping run state to UI state (ESCALATED and ABANDONED are not "failed"; APPROVED and BLOCKED_REVIEW get mapped); name the three panels.
- **AM-00:** append the omitted 1.0 passages (§4 tenant-admin, the §8 single-writer sentence, §16 tabs, §6 `allowed tools`/diagnostics, §12 `prompts/`, R098's "default" profile).
- **AM-12:** fix the "first" wording against the advisory lock. Add `decisions`, `idempotency_request`, `messages` and `operator_resolutions` to the lock order. The outbox appends events in a separate transaction.
- **Value** (owner's choice), as proposed by the value reviewer:
  - **Must-show:** (1) lost response → reconcile → one incident under `docker kill`; (2) hash-bound independent approval; (3) sealed-holdout eval with a run manifest; (4) an injected document cannot add authority; (5) 30 scenario cards in CI; (6) stale fence rejected.
  - **Demote to documented-but-deferred** (estimated 10–18 days saved, unmeasured): back-channel logout plus the per-mutation admin-API check; `action.late_evidence`; the concurrent slot test; kappa and cluster bootstrap; SSE replay (polling instead); retained-receipt restore.

## Decision needed (owner)

1. **Direction.** Either:
   - **(a) keep hardening** with a 1.3.2 that fixes S1–S9 and H1–H5, or
   - **(b) simplify:** fix S1–S9 and H1–H5 *plus* adopt the must-show list, the demotions, and a "v0.5 showable" milestone, then start building and review per slice.

   The lead recommends **(b)**.
2. **Second incident for the same asset after the first succeeds** (H3): block it, or allow it?
3. **Ollama network exposure:** intended, or should it be restricted to localhost?

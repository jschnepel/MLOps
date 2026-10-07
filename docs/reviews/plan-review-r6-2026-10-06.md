# Adversarial review, round 6: OPS-BUILD-1.3.2

**Reviewed:** commit `2e146bd` (1.3.2 diff `e0e955b..2e146bd`).
**Date:** 2026-10-06.

**Method:** three fresh reviewers: (1) closure of round-5 S1–S9/H1–H5 plus regressions; (2) attacks on the mechanisms 1.3.2 added; (3) a readiness re-check of T01–T08 (manifest hashes recomputed against git blobs and both zips; `uv` flags checked; Keycloak docs read). The lead spot-checked the findings. **Legend:** ✓ verified by the lead · ○ reviewer finding.

## Bottom line

| Measure | Result |
|---|---|
| Round-5 items closed | 3 of 14 fully (S1, S5, S6); 11 partial; 0 open |
| New HIGH regressions caused by 1.3.2 | **3**, all in the privilege matrix and definer-function design |
| Critical | none |
| Blocks start | 5 small doc items + task splits |

**The pattern holds for a sixth round** ✓: the mechanisms 1.3.2 added (the role × table matrix, six named definer functions, the second-incident guard, the test-clock table) each arrived with gaps that this round found. The matrix as written **cannot run the system** (the API may not create jobs or events; the worker may not update runs), the second-incident guard **misses the common ordering**, and six definer functions exist only as names.

**Mistake of mine found this round** ✓: commit `61cc504` was not "unmodified". I had appended ignore rules to `.gitignore` before committing, so `MANIFEST.sha256` matches 160 of 161 files at that commit, and the 1.3.2 instruction to verify the manifest "against commit 61cc504" can never fully pass. The delivered zip is the only 161/161 artifact and it is untracked.

## Blocks start (T01–T08)

| # | Finding | Fix |
|---|---|---|
| B1 | **Manifest verification is unsatisfiable** ✓ (`.gitignore` blob `9d4e25eb…` vs manifest `0ec5449b…`). | Commit the delivered zip as `provenance/handoff-1.0.zip` and verify `MANIFEST-1.0.sha256` against its entries with stdlib `zipfile`. No git dependency. Record the `.gitignore` deviation in AM-00. |
| B2 | **AM-80 lacks `ASSET_INCIDENT_EXISTS`** ✓ (used at AM-13:279), and **REJECTED is missing** from the abort rule (AM-13:234), the hash rule (:259) and `GET /internal/actions` (:261) ✓. R104 cannot pass against the table. | Add the error code and the REJECTED cases. |
| B3 | **DRAFTING → BLOCKED_REVIEW is a bullet, not a table row** ✓ (AM-10:132 has no such row). R082's "one table" would ship without it. | Add the row (and APPROVED → BLOCKED_REVIEW on guard refusal). |
| B4 | **No file name for the pinned model digest** ○ that T02 writes and the warm-up check reads; the digest check has no owning task. | `data/model-pins.json` (model, digest, ollama_version, probe date), written by T02; the warm-up check is owned by T19 with a requirement. |
| B5 | **Stale wording** ✓: `CLAUDE.md:5` says "v1.1 dependency graph"; ACCEPTANCE.md header says 1.3; ADR-0002 lists five roles; T09's note and AM-20.9 say "gated by PROFILE=test" (a SQL function cannot read it). | Text fixes. |
| B6 | **T04, T05 and T07 are too large** ○ (estimates 4–6, 6–9 and 10–14 days). | Split: T04a workspace / T04b reference move + manifest; T05a what T08 needs / T05b remaining personas, service account, admin deletion / T05c Ollama bridge + runbook; T07a core contracts / T07b schema alignment + checker / T07c reference traceability. T08 depends on T05a + T07a only. |
| B7 | **The skeleton-debt list is not written anywhere** ○. | Commit it in SESSION_STATE before T08 starts: single owner DB role, no matrix/RLS, plain INSERTs instead of definer functions, no test clock, no lease/fence/permit, no idempotency/outbox/sequence lock, no guard/expiry, raw handle unhashed, fake model, no LangGraph. Not debt: real tokens, aud/azp/iss checks, `action_key` ON CONFLICT. |

## High (fix before T09)

| # | Finding | Fix |
|---|---|---|
| H1 | **The privilege matrix forbids required writes** ✓: `api` lacks `jobs` and `events`, yet admission commits message + run + job + event; `worker` lacks `runs`, yet it drives most transitions, `runs.checkpoint_id` and `runs.next_event_seq`. "runs (admission, cancel flag)" is not expressible as a GRANT: column grants cannot constrain values. | Rewrite the matrix as exact GRANT lists (table, columns). Route every run transition through one definer `transition_run()`; `api` gets UPDATE on `cancel_requested` only. Add an `append_event()` definer that derives `source`, so neither api nor worker can forge `action.confirmed`. |
| H2 | **AM-20.1:357 grants every definer function to `mcp_exec`** ✓ ("GRANT EXECUTE … TO mcp_exec" is stated per migration), which would make `record_decision`, `freeze_proposal` and `resolve_escalation` callable by the MCP role. | "GRANT EXECUTE only to the role named in AM-20.12." |
| H3 | **Six definer functions are names only** ○ (`record_decision`, `create_revision`, `create_manual_proposal`, `freeze_proposal`, `expire_proposal`, `resolve_escalation`): no inputs, locks, transitions or events. Who performs EXECUTING → FAILED(`cancelled_before_send`) is unresolved between `request_abort` and `record_outcome`. | A function table: name, caller role, arguments, lock set, transition, event. |
| H4 | **No RLS policy exists for `app_definer`** ○. FORCE RLS subjects only the owner; a non-owner role with no policy gets default deny, so every definer function would return zero rows. | List policies per table and role in AM-20.12, e.g. `USING (tenant_id = current_setting('app.tenant_id', true)::uuid) TO app_definer`; R106 asserts the policy text. api/worker can set the GUC themselves, so RLS is defense-in-depth for them. Say so. |
| H5 | **The second-incident guard misses the common ordering** ✓: it refuses only a SUCCEEDED recorded *after* this proposal froze. If A succeeds at t0 and B freezes at t1 > t0, B is granted. Asset-sim knows nothing of incidents, so "fresh evidence" cannot reveal A, and a revision resets the freeze time. | **Owner decision:** (i) refuse whenever any COMMITTED action overlaps, regardless of timing, unless the proposal declares `supersedes_run_id`; or (ii) inject the existing incident as an evidence item at freeze and show it on the approval card, leaving the reviewer to decide. |
| H6 | **"Audit tables insert-only" contradicts the attempt protocol** ○: `mark_sent` and `record_outcome` UPDATE `action_attempt`; `freeze_proposal` mutates `proposals`; `app_definer` has no matrix row. | Model attempt state as append-only child rows (latest wins), or give `app_definer` an explicit row with UPDATE on exactly `action_attempt.state`, `runs.state`, `proposals.frozen_at`. |

## Later (owning task)

- **T09:** name the test-harness role; create `app.test_clock` through an Alembic branch applied only by the test harness, with a demo bootstrap check `to_regclass('app.test_clock') IS NULL`; two function bodies, since a static reference to a missing table fails at runtime. `hashtext` vs `hashtextextended` wording.
- **T10:** POST-onto-REJECTED behaviour; keep the detective check that every destination key matches a grant.
- **T14/T22:** `recover` jobs have three creators including `create_incident`, which cannot insert jobs and has already aborted. Creator should be the worker. Map §6's `dedup key`/`available_at` onto each creator to prevent duplicate recover jobs. A cadence and cap for reconciliation on ESCALATED/ABANDONED runs.
- **T16/T18:** `search_procedures_scoped` takes text only, so vector search cannot run inside it without an embedding argument. Add one (or embed inside the function via a trusted embedding service).
- **T21:** "decisions only via `record_decision`" does not stop a compromised api forging approvals: the api supplies the reviewer `sub`. Restate H1's claim as "no role except api can write decisions; api is the identity trust anchor".
- **T05:** Keycloak has no `_FILE` env variant; Compose `secrets:` needs an entrypoint wrapper or a PBE keystore. The bootstrap admin can only self-delete via the admin REST API using its own token; verify on the cached 26.8.0 image before committing the DoD.
- **T07:** `state_version` semantics are DB behaviour; the test belongs to T09/T21. The reference's "pure-core" tests import `Store`/`ControlService`, so porting means rewriting against the new core. `evals/holdout-case.schema.json` is T03's; the checker tolerates its absence.
- **T34:** the README sentences AM-10:127, AM-13:240 and AM-50 require (escalation risk, abort latency, holdout limitation, 30-point detectability) were lost in the rewrite and no task names them.
- **Holds** ○: `state_version`-only-on-transition is acceptable (decisions bind by hash); REJECTED pre-poison needs the action_id, known only to mcp-server; interval overlap is `a<d ∧ c<b`, and a requester choosing a disjoint interval evades the guard by design.

## Convergence

| Round | Critical | High | Of which caused by the previous round's fixes |
|---|---|---|---|
| 2 | 3 | 9 | 3 critical |
| 3 | 2 | 5 | most |
| 4 | 0 | 0 | — |
| 5 | 0 | 6 | 4 |
| 6 | 0 | 6 | **6 of 6** |

Every high finding this round is a defect in text added by 1.3.2. The privilege matrix, the definer-function contracts and the RLS policies are the kind of design that is settled faster against a running PostgreSQL (T08/T09) than in prose: a `GRANT` either lets admission commit or it does not. The lead's recommendation stands: fix B1–B7 (small), take the owner's H5 decision, write the H1–H6 fixes as **T09's review notes and DoD** rather than as another spec round, then start T01.

## Decisions needed (owner)

1. **H5 timing:** option (i) refuse any overlapping COMMITTED action regardless of timing (with `supersedes_run_id` opt-out), or (ii) surface the existing incident to the reviewer and let them decide.
2. Whether to accept the recommendation above (B1–B7 as 1.3.3; H1–H6 settled in T09 against code) or run a 1.3.3 that also rewrites the matrix and function contracts in prose first.

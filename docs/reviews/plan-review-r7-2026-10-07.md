# Adversarial review, round 7: OPS-BUILD-1.3.4

**Reviewed:** commit `6f84b96` (1.3.3 diff `0b8cf94..fd0a2ec`, 1.3.4 diff `fd0a2ec..6f84b96`).
**Date:** 2026-10-07.

**Method:** three fresh reviewers: (1) closure of round-6 B1–B7/H1–H6 plus regressions; (2) attacks on the mechanisms 1.3.3 and 1.3.4 added, with PostgreSQL docs opened for `session_user`, `SET ROLE`, FORCE RLS, `SET` inside definer functions and reserved words; (3) a truthfulness and reader audit of `docs/ARCHITECTURE.md`, the README table and `docs/PROJECT_HISTORY.md`. The lead verified the findings marked ✓ against the files.

## Bottom line

| Measure | Result |
|---|---|
| Round-6 items | 10 of 13 closed; 3 partial (B5, B6, H1) |
| Critical | none |
| High | 5: four in mechanisms 1.3.3/1.3.4 added, one in the showcase doc |
| Verified sound | `session_user` is unchanged inside `SECURITY DEFINER` and `SET ROLE` changes only `current_user`, so the allowed-caller design holds; `runs.state` and `run_state_history` are written in one transaction; the worker's dual-audience token is bounded by server-bound handles; the manifest matches the committed zip 161/161 |

Two facts about this round. First, the function-contract design survived its first direct attack: the mechanism it rests on is correct. Second, the pattern of the last four rounds held again: every high finding is in text added by the previous revision, and the showcase document I wrote contains the same kind of over-claim the earlier rounds caught in the original package.

## High

| # | Finding | Fix | Owner |
|---|---|---|---|
| H1 | **`supersedes_run_id` is model-controlled** ✓. AM-13 puts it inside the hashed payload, which `freeze_proposal` builds from the model draft. No structured requester field exists, so an injected document naming the one successful run on an asset defeats the guard the owner chose, which is exactly what R036 forbids. | A structured requester field on the admission/revision request, stored on `runs` by the API; `freeze_proposal` injects it from `runs`, rejects drafts that carry it, and requires it to name the actual blocking run in the same tenant and asset. | **BLOCKS-START** (T07 contract, T45 schema) |
| H2 | **`transition_run` gives the worker unrestricted targets** ✓ (AM-20.3 restricts `api` and `sweeper` only). A compromised worker can mark a run SUCCEEDED with no receipt, and guard (b) then blocks the asset. The `api` and `sweeper` targets also duplicate `request_cancel` and `expire_proposal` without their checks. | Worker targets = {RETRIEVING, DRAFTING, AWAITING_INPUT, QUEUED from AWAITING_INPUT, ANSWERED, INSUFFICIENT_EVIDENCE, FAILED from pre-grant states}; revoke `transition_run` from `api` and `sweeper`; SUCCEEDED/FAILED after a grant only via `record_outcome`. | T09 (text now) |
| H3 | **Admission cannot emit its own event** ✓. AM-16 commits "run + job + event", but `append_event` refuses `run.*` from `api` and `transition_run` has no ∅ → QUEUED row; no `run_state_history` row exists for the first state. Fails R015/R128. | Add ∅ → QUEUED to the AM-10 table; a `create_run` definer (or `transition_run` from ∅) callable by `api` inserts run, directory, history, job and `run.accepted` in one transaction. | **BLOCKS-START** (T07 row), function T09/T12 |
| H4 | **No role can insert `tenants`, `memberships` or `model_permit`** ✓, and `migrator` is outside the FORCE RLS policy, so the persona seed cannot run and no migration can backfill an RLS table. | Seed rows are a `migrator` data migration run with `BYPASSRLS` granted to `migrator` only, or via `seed_*` definer functions; `model_permit` seeded the same way. State it in AM-20.2/20.5. | T09 (text now), T05/T43 choose |
| H5 | **The showcase doc over-claims** ✓: "Reading the code" and every "Proof" header are in the present tense for directories and tests that do not exist; the graph diagram shows 2 of the 10 AM-16 routes and draws interrupts as edges; "model-to-destination denied at the Docker network level (R066)" is untestable because Ollama runs on the host; the README's "Proven by" column cites requirements that do not test loopback binding or per-node idempotency. | "Planned proof" / "Where the code will live"; redraw the graph from the AM-16 table with interrupts marked "ends; resumed by job"; cite R066 only for worker and browser paths; "Target tests" in the README with R026/R027/R085 added and "loopback-bound" removed; add a four-line "Not claimed" block (one replica, no Kubernetes, owner holdout, ≤5-minute abort latency). | **BLOCKS-START** (before T06 publishes) |

## Blocks start (small)

| # | Finding | Fix |
|---|---|---|
| S1 | **AM-16 contradicts R018** ✓: a text/field conflict is `reject` (422) in AM-16 but "ambiguity clarifies" in R018 and in ARCHITECTURE.md. | Keep R018: conflict → clarification. Hints may only produce a clarification, never `reject` (removes the pasted-text self-DoS). |
| S2 | **`answer_only` has nowhere to live** ✓: no `jobs` column, not a graph-router input, and "never freezes" is enforced nowhere. "Draft kind" as a router input contradicts "the model never selects a route". | `runs.intent ∈ {investigate, answer_only}` set by the admission router; a router input; `freeze_proposal` refuses when `answer_only`; "evidence sufficient?" is a code rule on evidence counts and freshness, not model output. |
| S3 | **Stale text** ✓: ADR-0001 still says the reference moves in T04 and T07 traces; ADR-0002 lists 8 roles (no `mcp_read`); T05's instructions still say `MCP_RESOURCE_URL` singular; AM-12 still says `hashtext`. | Text fixes. |
| S4 | **PROJECT_HISTORY misattributes rounds** ✓: cites a "Round 0" that is not a file; credits rounds 2–6 for findings the round-1 review made (per-job fence, custom saver, disable ≠ logout, serial chain, "production-ready"); the "problems per hour" sentence is unmeasured; four of the author's own mistakes are omitted (the three critical defects in 1.1; the cp1252 encoding gap; the ADR-0001/AM-01 move-task conflict; the README limitation sentences lost in the rewrite and still absent). | Correct the attributions against `docs/reviews/*.md`; delete the per-hour claim; add the four mistakes; add the required README sentences. |
| S5 | `SELECT offset FROM app.test_clock` will not parse (`OFFSET` is reserved) ✓; `current_setting('app.tenant_id')::uuid` raises on `''`. | Rename the column; `NULLIF(...,'')::uuid`. |

## Later (owning task)

- **T09:** definer bodies use `set_config(name, value, true)` (transaction-local), or the caller's `app.tenant_id` is overwritten; R106 tests it. A sweeper policy for `memberships`/`jobs` (it has no run to resolve a tenant), and AM-20.5 "exactly these policies" relaxed to name it. `invocation_context` columns (`server`, `job_type`) defined; `drafts` columns defined ("IDs only" contradicts "pre-freeze model output"). Remove `worker upd(runs.next_event_seq)`, which bypasses `append_event`'s lock. `action_attempt_state` needs an ordering column; `request_abort` "marks aborting" contradicts append-only. The demo `to_regclass` check runs at each service start, not only at bootstrap.
- **T13/T15:** a `revoke_handles(run_id, fence)` function for the worker (only `app_definer` may update `revoked_at`). `resolve_invocation` verifies `job_type` against the `jobs` row rather than the worker-written field; `freeze_proposal` derives `authored_by` from `runs`, not from a worker argument.
- **T10/T47:** `record_outcome` verifies the hash against nothing independent: a compromised mcp-write fabricates a receipt with the grant hash. Either incident-sim HMAC-signs receipts with a key in an `app_definer`-only table, or the threat model states plainly that mcp-write is trusted for outcome truth. R131 reworded to named function sets (both roles share `resolve_invocation`).
- **T12/T14:** `status_question` writes no message or event (unaudited); `append_event` enforces payload rules in the function, since `event.schema.json` gives `tool.completed` a status enum; `action.redispatched` is emitted by no function; `action.granted` missing from AM-14's list; `deliver_outbox` missing from AM-15's job enum; "status grammar" undefined.
- **Showcase, LATER:** principals table rows incomplete versus AM-20.2 (api `run_directory` insert and audit selects; worker `invocation_context`, `outbox`, corpus tables, `model_permit`); sweeper "can reach Keycloak" with no Keycloak client specified anywhere; mcp-write "cannot see evidence text" → "sees only the frozen payload"; "gated three times" has no spec text; demo 2 is a cross-team/injected denial per §28, not an MCP denial; cut the "Why this matters" paragraph, the "What MCP is not" bullet and the duplicate "not a free agent loop" bullet.

## Go / no-go

**Conditional GO.** T01, T03, T02, T04, T42, T05 (after S3), T43, T44 and T06 (after H5) can start. T07 and T45 wait on H1, H3, S1, S2; T08 follows them. H2 and H4 are T09's definition of done, written into the spec now so T09 does not inherit a contradiction.

## Decision for the owner

Round 7 is the first round in which the core mechanism (definer functions keyed on `session_user`) was attacked directly and held. The remaining highs are specification gaps in the newest text, and each is a two-to-six-line edit. A **1.3.5** that applies H1–H5 and S1–S5 and writes the LATER items into T09/T13/T15/T47 review notes would take the plan to a state where the first slice has no known blocker.

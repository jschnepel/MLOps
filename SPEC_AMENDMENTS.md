# OPS-BUILD-1.3.4 — Amendments to BUILD_SPEC.md

**Status:** Approved by the owner on 2026-10-06. The history: 1.1 was "amend + cut", 1.2 came from the round-2 review, 1.3 fixes the round-3 BLOCKS-START items, 1.3.1 applies round-4 edits E1–E6 (`docs/reviews/plan-review-r4-2026-10-06.md`), 1.3.2 fixes round-5 items S1–S9 and H1–H5 (`docs/reviews/plan-review-r5-2026-10-06.md`, cited `[R5-…]`), and **1.3.3 rewrites AM-20 (privilege matrix, function contracts, RLS policies) and fixes round-6 items B1–B7 and H1–H6** (`docs/reviews/plan-review-r6-2026-10-06.md`, cited `[R6-…]`). Owner decision for 1.3.3: a grant is refused whenever **any** committed incident overlaps the same tenant, asset and interval, unless the proposal declares `supersedes_run_id` (R6-H5). **1.3.4** (2026-10-07, ADR-0003): named routers (new AM-16), the MCP server split into `mcp-read` and `mcp-write`, a model router, and `docs/ARCHITECTURE.md` as the showcase map. Owner decisions for 1.3.2: block a second incident for the same asset and interval (H3); restrict Ollama to loopback plus the Docker/WSL subnet (S9).
**Precedence:** This file overrides `BUILD_SPEC.md` (OPS-BUILD-1.0) wherever they conflict. Everything not amended here stays in force. ADRs in `docs/adr/` record the reasoning.

**Sources:**
- `docs/reviews/handoff-review-2026-10-06.md` (round 1, cited `[R1#n]`)
- `docs/reviews/plan-review-2026-10-06.md` (round 2, cited `[R2#n]`)
- `docs/reviews/plan-review-r3-2026-10-06.md` (round 3, cited `[R3-Bn]`)
- `docs/reviews/plan-review-r4-2026-10-06.md` (round 4, `[R4-En]`), `…-r5-…` (`[R5-…]`), `…-r6-…` (`[R6-…]`)
- `docs/PROJECT_HISTORY.md`: the problems found across all rounds and what changed, written for readers of the portfolio

New acceptance requirements are R081–R131 in `handoff/acceptance-matrix.json`. Round-3 LATER items are attached to their owning tasks as `review_notes` in `handoff/tasks.json`. From now on, review happens per slice against code and tests, not through further spec rounds.

**Changes in 1.3** (all from round 3):
- abort hash semantics (B1);
- cancel vs `mark_sent` (B2);
- operator resolution of ESCALATED (B3);
- conversation slot on revision (B4);
- AM-80 completed (B5, B6);
- reference traceability and move in T04 (B7, B8);
- checker updates (B9);
- holdout split and external seal (B10);
- probe inputs (B11);
- seed IDs and Keycloak topology (B12);
- walking-skeleton scope (B13);
- venv location (B14);
- also corrected: the LangGraph resume rules (AM-12), the asset-guard advisory lock (AM-13), and the evaluation-power statement (AM-50).

## AM-00 Superseded BUILD_SPEC text (explicit list)

These 1.0 passages are superseded and must not be implemented as written:
- **§6:** "job … lease_until, fence": replaced by run-level `run_lease` (AM-12).
- **§9:** the `ops-mcp` audience and "distinct service scope" wording: replaced by AM-20.6.
- **§9:** the handle's "allowed tool names": replaced by AM-20.2.
- **§10:** "negotiation": replaced by AM-30. The four tools become six (AM-15).
- **§14:** "authoritative terminal no-commit record": produced by the AM-13 abort tombstone.
- **§16:** the full state list: replaced by AM-40.
- **§20:** 80/40 cases with a separate reviewer: replaced by AM-50.
- **§21:** profile names: v1 profiles are `dev`, `test` and `demo` (§21's integration/real-model checks run under `test` and `demo`).
- **§22:** all of it: deferred to M15.
- **§23:** kind smoke test and SBOM/provenance as mandatory gates: deferred to M15 (ADR-0002).
- **§25:** the milestone table: replaced by `handoff/tasks.json`.
- **§4:** the tenant-administrator row: there is no admin surface in v1 (AM-02).
- **§6:** the `invocation_context` "allowed tools" field and the "diagnostics" credential: replaced by AM-20.3 and the AM-20.2 grant table.
- **§8:** "a documented single-writer development profile is not a substitute for passing that target gate": v1 *is* the one-replica profile (ADR-0002); the distributed gate (R021) is M15.
- **§12:** `prompts/`: versioned prompts live in `core/prompts/` once T19 promotes them; `handoff/prompts/` stays the sealed v1 starters.
- **§16:** four tabs: replaced by AM-40's three panels.
- **R098's "default" profile** means the `dev` and `demo` profiles.
- **`MANIFEST.sha256`** is a frozen snapshot of the delivered 1.0 package [R5-S8, R6-B1]. Commit `61cc504` is *almost* that package: its `.gitignore` already carried the owner's ignore rules, so 160 of 161 manifest entries match that commit and one does not. The authoritative 1.0 bytes are therefore the delivered zip, committed as **`provenance/handoff-1.0.zip`** (sha256 `49df585220709c6fd6cf9a222db7fba436b7a595a73f50f084484911e92609f6`). T42 moves the manifest to `provenance/MANIFEST-1.0.sha256`, and `verify_handoff.py --manifest` verifies it against the zip's entries with the standard-library `zipfile` module. No git dependency; shallow clones and zip downloads work.

**Changes in 1.2:**
- execution ownership and attempt protocol (AM-13);
- fence locking and clocks (AM-12);
- checkpoint durability (AM-12);
- destination action-key table (AM-13);
- hardened definer functions (AM-20);
- revocation mechanism (AM-20);
- MCP token verification (AM-20);
- one worker replica in v1 (AM-12, ADR-0002);
- evaluation statistics (AM-50);
- task graph with walking skeleton, dev bootstrap and early CI (AM-60);
- schema alignment owned by T07 (AM-80);
- versions (AM-30).

---

## AM-01 Repository layout (amends §5) → ADR-0001

Each independently deployed process gets its own top-level directory, each with its own `pyproject.toml`, `Dockerfile`, `tests/` and `README.md`:

| Directory | Process |
|---|---|
| `api/` | FastAPI: sessions, admission, decisions, SSE, health |
| `worker/` | Run-lease worker: LangGraph graph, LangChain draft node, MCP client |
| `mcp-read/` | Authenticated MCP server for read tools only (asset status, alerts, procedure search); DB role `mcp_read` |
| `mcp-write/` | Authenticated MCP server for the guarded write and recovery tools only; DB role `mcp_exec` |
| `asset-sim/` | Synthetic asset/alert API (deterministic, injected clock) |
| `incident-sim/` | Synthetic incident destination with its own database |
| `web/` | React + TypeScript + Vite workspace |
| `core/` | Shared library (uv workspace member). **Not** a service. |

**The reference moves in T42** [R3-B8, R6]:
- T42 moves the whole reference unit, unchanged, into `reference/`: `src/operations_copilot/`, `tests/`, its `pyproject.toml`, `Makefile`, `Dockerfile`, `compose.yaml`, `integrations/`, `scripts/init_demo.py` and `scripts/check_reference.sh` [R4-E1].
- `reference/` is **not** a uv workspace member (`[tool.uv.workspace] exclude = ["reference"]`). Root ruff, mypy and pytest exclude it, and it runs from its own external venv.
- The "one command" check is a Python entry point (`uv run python scripts/check.py`), not `make`. This machine has no `make`.
- In the same commit it adds `provenance/reference-code-hashes.remap.json` (old path → new path, same sha256) and teaches `scripts/verify_handoff.py --reference-code` to use it.
- The root `pyproject.toml` becomes the uv workspace root.
- The reference stays runnable from `reference/` (R001).

**T46 traceability** [R3-B7]: T46 ports only the pure-core reference tests and commits `reference/TRACEABILITY.md`. That file maps each of the 58 tests to *port*, *replace by* (target test plus owning task) or *drop* (with the AM-70 reason).

## AM-02 Version 1 scope (amends §2, §25, §28) → ADR-0002

V1 is M00–M14 of `handoff/tasks.json`. The optional milestone M15 holds:
- kind/Helm with cluster NetworkPolicy (R112);
- the upgrade rehearsal (R069);
- SBOM/provenance (R076);
- fenced checkpoint writes with multi-replica workers (R021);
- Slack (R079);
- cloud (R080).

Also reduced for v1:
- **Observability:** an OTel collector and one trace backend.
- **UI:** three panels covering eight states (AM-40).
- **Database roles:** `migrator` (DDL only, never used at runtime), `api`, `worker`, `sweeper`, `operator`, `mcp_read` and `mcp_exec` (functions only), `app_definer` (NOLOGIN, owns functions, does not own tables), and `incident` (separate database). Their privileges are fixed by the AM-20.2 grant table [R5-H1, R5-S7].
- **No tenant-administration surface.**
- **Workers:** **one worker replica** in the demo profile (AM-12).

**Demo claims:**
- The recovery demo uses `docker kill` on the worker container.
- No "tested Kubernetes" claim.
- No "multi-replica fenced checkpoints" claim.
- The holdout is owner-authored, not reviewed by a third party.

## AM-10 Run state machine (amends §8)

**New state `ESCALATED`:**
- Reached on `CONFLICT`, or when the escalation deadline passes with the outcome still unresolved.
- It frees the conversation slot, but the **asset guard** (AM-13) blocks a new incident proposal for the same tenant, asset and overlapping interval while the action is unresolved.
- Reconciliation continues. `ESCALATED → SUCCEEDED | FAILED` is allowed only on destination evidence.
- SSE streams and the UI keep ESCALATED runs live.

**New terminal state `ABANDONED_UNVERIFIED`** [R3-B3]:
- Reachable only from ESCALATED, through the operator CLI `ops resolve-escalation <run_id> --acknowledge-unverified --reason "<text>"`.
- The CLI connects as the `operator` role, which may only `EXECUTE` the definer function `resolve_escalation(run_id, operator_name, reason)`. The operator name is a **required argument and is self-asserted** (documented as unauthenticated local identity). The function records it, with the reason and time, in the insert-only `operator_resolutions` table and emits `run.abandoned_unverified`.
- It never claims success or failure. Reconciliation keeps running. On destination evidence it appends **`action.late_evidence`** (payload: `outcome ∈ {SUCCEEDED, FAILED_NO_COMMIT}` plus the receipt or tombstone) and the run status stays ABANDONED_UNVERIFIED [R4-E4].
- `record_outcome` makes **no state transition** from any terminal state; it only records evidence.
- Recover jobs remain allowed for ABANDONED_UNVERIFIED runs (AM-15).
- After this acknowledgement the asset guard no longer blocks that asset and interval. The README documents the risk: the destination may still hold the incident.

| From | Added / changed transition |
|---|---|
| RETRIEVING | → AWAITING_INPUT when required context is missing or ambiguous |
| DRAFTING | → AWAITING_INPUT on `kind=abstain` with a question, at most 2 clarification rounds; on a third round → INSUFFICIENT_EVIDENCE; **→ BLOCKED_REVIEW** on asset-guard refusal at freeze (`asset_action_unresolved` / `asset_incident_exists`) [R6-B3] |
| AWAITING_APPROVAL | → BLOCKED_REVIEW on expiry: evaluated lazily inside any decision or grant transaction, plus by the scheduled `expire_proposals` job (60 s) |
| BLOCKED_REVIEW | Frees the conversation slot. → QUEUED on revision **only if the conversation has no other active run, else 409** [R3-B4]; → CANCELLED |
| APPROVED | → QUEUED only via revision **before the grant exists**; **→ BLOCKED_REVIEW** on asset-guard refusal, stale evidence, revoked authority or expiry at grant [R6-B3] |
| EXECUTING / OUTCOME_UNKNOWN | → ESCALATED on CONFLICT, or when the escalation deadline passes (AM-13) |
| ESCALATED | → SUCCEEDED / FAILED only on verified destination evidence; → ABANDONED_UNVERIFIED by operator CLI only |
| REJECTED, CANCELLED, ANSWERED, INSUFFICIENT_EVIDENCE, SUCCEEDED, FAILED, ABANDONED_UNVERIFIED | Terminal |

**Active states** (the ones that hold the conversation slot): QUEUED, AWAITING_INPUT, RETRIEVING, DRAFTING, AWAITING_APPROVAL, APPROVED, EXECUTING, OUTCOME_UNKNOWN.

**Clarification signal:** a draft asks for clarification with `kind=abstain` **plus** a non-empty `question` (AM-80). Without `question`, abstain means INSUFFICIENT_EVIDENCE [R3-B5].

- **Enforcement:** the transition table is data in `core/`, and a single function enforces it (R082).
- **Asset-guard refusals** [R5-S4, R5-H3]: DRAFTING (at freeze) or APPROVED (at grant) → BLOCKED_REVIEW with reason `asset_action_unresolved` or `asset_incident_exists`, emitting `review.blocked`. The requester resubmits by revision. Refusals never leave a run holding the slot in APPROVED.
- **`state_version`** increases **only on state transitions**. Appending events, heartbeats and attempt-state changes do not bump it, so user cancels and decisions don't get spurious 409s [R5-S5].
- **Reasons** on terminal and blocked states come from one enum in `core/`: `cancelled_before_send`, `aborted_no_commit`, `rejected`, `asset_action_unresolved`, `asset_incident_exists`, `expired`, `stale_evidence`, `authority_revoked`, `conflict`, `escalation_deadline`. A cancel in INTENT ends FAILED with `cancelled_before_send` [R5-S6].
- **The ANSWERED path** (read-only answer, no proposal) has its own test (R114).

**Clock rule:**
- Every lease, expiry, freshness and deadline comparison uses `clock_timestamp()`, evaluated **after** the relevant row locks are acquired. Never use `now()`, which is the transaction start time.
- Tests inject time through the database function `app.current_time()`. It wraps `clock_timestamp()` plus an offset read from the table `app.test_clock`.
  - **Only the Alembic branch `testclock` creates `app.test_clock`** (AM-20.6). In dev and demo it does not exist, and the function returns `clock_timestamp()` unchanged.
  - No runtime role can write it; only the `test_harness` role (AM-20.1), which exists only in the test profile, can.
  - **Session settings (GUCs) are never consulted**, so no role can shift time with `SET`.
  - Tested by R126 [R5-H5].

## AM-11 Proposal identity and grants (amends §6, §7, §10, §13)

- **One ID per revision.** `proposal_id` identifies exactly one immutable revision; `(run_id, revision)` is unique. Decisions carry `expected_payload_sha256` (T45 renames the schema field).
- **At most one grant per run, ever.** `execution_grant` gains `run_id` with `UNIQUE (run_id)`, so it never has a second row, even after an abort. A failed or aborted action needs a **new run** for a new incident. Once a grant exists, revisions return 409.
- `action_id` is a random UUIDv4 created inside `grant_execution`.

## AM-12 Run lease, fence, locking and checkpoints (amends §6, §8)

**Lease:**
- `run_lease(run_id PK, owner, lease_until, fence bigint)`. Jobs are wake-ups only.
- **Acquisition:** `SELECT … FOR UPDATE` on the lease row, then check `lease_until < app.current_time()`, then `fence := fence + 1`.

**Fenced writes:** every worker or MCP mutation for a run **first** executes:

```sql
SELECT 1 FROM run_lease
 WHERE run_id = :r AND fence = :f AND lease_until > app.current_time()
 FOR SHARE
```

A missing row aborts the transaction.

**Writes without a lease:** API and sweeper mutations (decision, cancel, revision, expiry) hold no lease. They serialize with `SELECT … FROM runs … FOR UPDATE` plus `expected_version`.

**Lock order:** `asset guard advisory lock → run_lease → runs → messages → proposals → decisions → memberships → execution_grant → action_attempt → operator_resolutions → events → outbox`. Idempotency rows are written last, before commit. The outbox delivery loop records results in its own transaction and appends any `notification.failed` event in a **separate** transaction, so it never takes `runs` after `outbox`.
- The asset guard lock is `pg_advisory_xact_lock(hashtext(tenant_id || ':' || asset_id))`. Proposal freezing and `grant_execution` take it first.
- Every transaction and definer function follows this order.
- Any transaction that will write `run_lease` takes `FOR UPDATE` from the start; it never upgrades from `FOR SHARE`. A two-connection interleaving test and a concurrent stress test prove fencing and deadlock freedom (R107).

**Heartbeat:**
- Runs on a **dedicated thread with its own DB connection**: renew every 10 s, lease 30 s.
- The worker also keeps a local monotonic deadline: it stops starting effects at `lease_until − 5 s`.
- **When renewal fails, the worker:**
  - cancels in-flight model and tool calls;
  - revokes its invocation handles;
  - exits the run.

**Async only:** use `AsyncPostgresSaver`, `ChatOllama.ainvoke` and async MCP/HTTP clients. No synchronous I/O on the event loop.

**Model permit:**
- A `model_permit` row, leased and polled with `SKIP LOCKED` plus backoff, enforces global model concurrency (1).
- Whether a cancelled request actually stops Ollama's generation is **measured** in T02. If it doesn't, the permit is held until `ollama ps` shows idle or the 60 s cap passes.

**The graph (orchestrator):** one explicit LangGraph graph with nodes `load_run`, `route_request` (the graph router, AM-16), `await_clarification`, `retrieve_evidence` (mcp-read), `draft_with_langchain`, `validate_and_freeze` (`freeze_proposal`), `await_independent_decision`, `execute_approved_proposal` (mcp-write), `reconcile_outcome`, `publish_state`. Conditional edges come only from the route table in `core/`. There is no free-running think→tool→act loop; the model never sees a tool. `docs/ARCHITECTURE.md` §3 is the reader's map.

**Checkpoints (ADR-0002):**
- Invoke graphs with `durability="sync"`. The LangGraph default `"async"` persists while the next step runs.
- **Stored checkpoint ID.** After each superstep, the worker stores the accepted `checkpoint_id` in `runs.checkpoint_id` under the fence. It reads that ID from `stream_mode="checkpoints"` (or `aget_state` after the step). At an interrupt, the stored ID is the checkpoint holding the interrupt's pending write (R108).
- **How to resume** (verified against langgraph 1.2.14 `pregel/_loop.py`):
  - *Human resume:* `Command(resume=<event_id>)` with the stored `checkpoint_id`. This keeps RESUME writes and does not fork.
  - *Crash recovery:* `invoke(None)` with the stored `checkpoint_id` is treated as time travel and **forks**. The worker immediately stores the forked checkpoint's ID as the new accepted ID.
  - With an explicit `checkpoint_id`, LangGraph re-runs pending tasks rather than re-applying their writes (`_reapplies_pending_writes = not is_replaying`). So **every node** (not only nodes before an interrupt) must be idempotent and must reread authoritative application state.
- Nodes re-execute from the start on resume.
- **V1 runs one worker replica.** Fencing still protects application writes, and the stored checkpoint ID protects the head.
- R021 (fencing `put`/`put_writes` themselves, enabling multi-replica) stays open in M15.

## AM-13 Execution ownership, attempt protocol and destination (amends §13, §14)

**Who does what:**
- The worker never contacts the destination.
- **mcp-write** is the only caller of incident-sim. It records every step through fenced `SECURITY DEFINER` functions (AM-20). mcp-read cannot reach incident-sim and holds no write-path function.
- The worker drives the process by calling MCP tools under an `execute` or `recover` job.

**Attempt protocol** (`action_attempt(action_id, attempt_no, state, …)`):
1. `grant_execution` performs the §13 final gate. It inserts the grant **and** attempt 1 in state `INTENT` in one transaction, then returns `(action_id, canonical_bytes, sha256)`.
2. `mark_sent(action_id)` commits `INTENT → SENT` **before** network I/O. So `INTENT` means the request was definitely not sent.
   - `mark_sent` locks `runs` (in lock order) and re-checks `cancel_requested` and the dispatch deadline.
   - If either fails, it returns `cancelled` or `expired` and nothing is sent. The caller then aborts [R3-B2].
   - This lock is what makes "cancel in INTENT = guaranteed no-commit" true (R118).
3. The MCP server POSTs to incident-sim.
4. `record_outcome(action_id, outcome, receipt_or_tombstone)` inserts the `RESOLVED` state row with the verified receipt or tombstone, performs the run transition (AM-20.3) and appends the `source=destination` event. States are append-only rows in `action_attempt_state`; nothing is UPDATEd [R6-H6].

**Recovery** (`recover` job; tools allowed by AM-20.3 `resolve_invocation`):

| Attempt state | Rule |
|---|---|
| INTENT, before dispatch deadline, not cancelled | Redispatch with the same `action_id` and bytes. Redispatch **skips the §13 gate** (the grant was the linearization point). It loads the bytes through `lookup_action` and then goes through `mark_sent`. `create_incident` is allowed only when there is no attempt, or the attempt is INTENT, not cancelled and before the deadline. |
| INTENT, after deadline or cancelled | `abort_incident` → the destination returns a tombstone → `record_outcome` → FAILED(`cancelled_before_send` or `expired`). |
| SENT, no response | OUTCOME_UNKNOWN. `get_incident_receipt` with backoff 1, 2, 4, 8 s + jitter, then scheduled `recover` jobs. When the dispatch deadline passes, call `abort_incident`: the destination returns the existing receipt (→ SUCCEEDED), the existing REJECTED tombstone (→ FAILED, `rejected`), or a fresh ABORTED tombstone (→ FAILED, `aborted_no_commit`). |
| Destination unreachable | Keep retrying lookup or abort. When the escalation deadline passes, → ESCALATED (applies to INTENT and SENT). |
| Receipt received but not persisted | Lookup replays the same receipt; `record_outcome` is idempotent. |

**Cancellation:**
- In INTENT, cancellation leads to abort, a guaranteed no-commit, because of the `mark_sent` re-check.
- After SENT, cancellation triggers an **immediate** abort request; without a cancellation, abort waits for the dispatch deadline. A SENT action with a lost response can therefore take up to 5 minutes to become FAILED. The README states this latency. The truthful outcome is whatever the destination returns: an existing receipt is reported as SUCCEEDED with a "cancellation arrived after dispatch" note. Nothing is ever claimed as undone.

**Worker transport timeout during `create_incident`** [R2#10]:
1. Take the run lease row lock (`FOR UPDATE`).
2. Bump the fence, which revokes the handles.
3. Read `execution_grant` by `run_id`.
4. If a grant exists, the run becomes OUTCOME_UNKNOWN with that `action_id` and enters recovery. If not, no grant can commit any more, because the fence changed.

Tested by R109.

**Destination (incident-sim):**
- A single table `action_key(action_id PK, payload_sha256, state ∈ {COMMITTED, ABORTED, REJECTED}, incident_id NULL, reason NULL, decided_at)`. All three states are permanent and terminal [R5-S3].
- **Tombstone shape** (returned for ABORTED and REJECTED): `{action_id, state, payload_sha256, reason, decided_at}`.
- A validation rejection (malformed or disallowed payload) writes a permanent `REJECTED` key, so a lost response is recoverable by lookup.
- incident-sim also requires the token's `azp` to be the mcp-write client.
- Both `POST /internal/incidents` and `POST /internal/actions/{id}/abort` use `INSERT … ON CONFLICT (action_id) DO NOTHING` and then read the row, at **READ COMMITTED** isolation. The first writer wins atomically.
- An incident row is inserted in the same transaction only when the key commits.
- **Rows are never deleted or expired**, not even tombstones.
- **Abort carries the grant's `payload_sha256`**, which the tombstone stores [R3-B1].
- **Hash comparison applies only to `COMMITTED` keys.** A POST onto an `ABORTED` or `REJECTED` key returns that tombstone whatever hash it carries, and never commits. An abort onto a `REJECTED` key returns the REJECTED tombstone. Fault tests: a late POST after abort, and after rejection (R096) [R6-B2].
- The destination recomputes `sha256` over the received bytes. A different hash under an existing `COMMITTED` key → CONFLICT.
- `GET /internal/actions/{action_id}` (restricted lookup, §14) is retained. It returns COMMITTED with the receipt, ABORTED or REJECTED with the tombstone, or NOT_FOUND. NOT_FOUND is never treated as a no-commit [R6-B2].
- It accepts only the `incident-sim` audience workload token.

**Outcome vocabulary:**

| Layer | Values |
|---|---|
| Destination | `COMMITTED` / `ABORTED` / `REJECTED` |
| Tool outcome | `SUCCEEDED` / `FAILED_NO_COMMIT` / `UNKNOWN` / `CONFLICT` |
| Run | SUCCEEDED / FAILED / OUTCOME_UNKNOWN / ESCALATED / ABANDONED_UNVERIFIED |

`FAILED_NO_COMMIT` carries `reason ∈ {aborted_no_commit, cancelled_before_send, rejected}`, mapped from destination ABORTED, ABORTED-after-cancel, or REJECTED.

**Asset guard:**
- **Overlap** means the same tenant and asset and half-open intervals with `a < d ∧ c < b`. A requester who chooses a disjoint interval is not blocked; that is by design and documented.
- `freeze_proposal` and `grant_execution` both apply the guard, inside the per-(tenant, asset) advisory lock, against two sets:
  - **(a) unresolved actions:** any other run with a grant whose latest `action_attempt_state` is not RESOLVED (EXECUTING, OUTCOME_UNKNOWN, ESCALATED), excluding runs already ABANDONED_UNVERIFIED → refusal `asset_action_unresolved`;
  - **(b) committed incidents:** any other run with a SUCCEEDED outcome **or** SUCCEEDED late evidence, **regardless of when it was recorded** [R6-H5, owner decision] → refusal `asset_incident_exists`, **unless** this proposal declares `supersedes_run_id` naming that run. The approval card shows the referenced incident, so the reviewer sees what is being superseded. `supersedes_run_id` is part of the hashed payload.
- A refusal transitions the run to BLOCKED_REVIEW (AM-10) and never leaves a grant behind. A second incident is therefore created only when a reviewer approved a proposal that explicitly named the first (R125).
- They serialize on the per-(tenant, asset) advisory lock (AM-12), so two conversations cannot both pass the check (R110).
- A refusal returns 409 `ASSET_ACTION_UNRESOLVED` or `ASSET_INCIDENT_EXISTS`, listing the blocking run only if the caller may see it. The run moves to BLOCKED_REVIEW (AM-10).

**Defaults** (configurable; tests use `app.current_time()`):

| Setting | Default |
|---|---|
| Dispatch deadline | 5 minutes after grant |
| Escalation deadline | 30 minutes after grant |
| Request-dedup replay window | 24 hours |
| Destination keys and receipts | Never expire |
| `recover` cadence on ESCALATED / ABANDONED_UNVERIFIED | every 5 min for 1 h, then hourly, cap 48 attempts (AM-20.4) |

## AM-14 Events and SSE (amends §15)

- **Sequence numbers.** The per-run `sequence` comes from `runs.next_event_seq`, incremented under the `runs` row lock (lock order AM-12) in the same transaction as the insert. That makes it gap-free and commit-ordered (R089).
- **Event types:** §15 plus:
  - `clarification.received`
  - `proposal.revised`
  - `review.blocked`
  - `run.answered`
  - `run.insufficient_evidence`
  - `run.rejected`
  - `action.redispatched`
  - `action.failed` (with `reason`)
  - `action.conflict`
  - `run.escalated`
  - `run.abandoned_unverified`
  - `action.late_evidence` (status = the run's terminal status; `outcome` field carries the destination result)
  - `feedback.recorded`
  - `explanation.ready`
- **Who may assert outcomes.**
  - Only `source ∈ {application, destination}` may emit `action.*`, `run.*` or `review.*`.
  - `model_summary` may emit only `explanation.ready`, with no status field.
  - `action.confirmed` requires a receipt and status `SUCCEEDED`.
  - Enforced in schema (`if/then`) and in code.
- **Feedback** (`POST /runs/{id}/feedback`) stores classified feedback and emits `feedback.recorded`. It has no runtime effect (R113).

## AM-15 Tool contracts (amends §10)

**Tools and the job types that may call them:**

| Tool | Server | Callable by |
|---|---|---|
| `get_asset_status`, `get_recent_alerts` (absolute interval, `next_cursor`), `search_procedures` | **mcp-read** | `investigate` and `resume_input` jobs (read handles) |
| `create_incident(proposal_id)` | **mcp-write** | `execute` jobs; `recover` jobs for same-key redispatch |
| `get_incident_receipt(proposal_id)` | **mcp-write** | `recover` jobs only, including on ESCALATED and ABANDONED_UNVERIFIED runs |
| `abort_incident(proposal_id)` | **mcp-write** | `recover` jobs only, including on ESCALATED and ABANDONED_UNVERIFIED runs (the tombstone is recorded as late evidence) [R5] |

**Job types** [R5-S2]. Every job has exactly one `type`. Allowed tools are derived from type plus run state plus attempt state. **A handle is bound to one server:** `investigate`/`resume_input` handles are accepted only by mcp-read; `execute`/`recover` handles only by mcp-write (R131).

| `job.type` | Created by | Purpose | Allowed tools | Run states |
|---|---|---|---|---|
| `investigate` | API at admission and after a revision | Retrieval, drafting, freezing | read tools | QUEUED, RETRIEVING, DRAFTING |
| `resume_input` | API with a clarification reply | Resume after a clarification | read tools | AWAITING_INPUT → QUEUED |
| `execute` | API with an approving decision | Final grant and first dispatch | `create_incident` | APPROVED, EXECUTING (attempt absent or INTENT) |
| `recover` | `mark_unknown` (worker timeout path); the worker after a `cancelled`/`expired` tool result; `reclaim_leases` (sweeper). Never by either MCP server. Dedup keys in AM-20.4 [R6] | Redispatch, lookup, abort | `create_incident` (INTENT only), `get_incident_receipt`, `abort_incident` | EXECUTING, OUTCOME_UNKNOWN, ESCALATED, ABANDONED_UNVERIFIED |
| `expire_proposals`, `sync_memberships`, `sweep_wakeups` | Scheduler (sweeper role) | Maintenance | none | n/a (no run lease) |

Read tools are `get_asset_status`, `get_recent_alerts` and `search_procedures`. After `mark_sent` returns `cancelled` or `expired`, `create_incident` itself calls `request_abort`, POSTs the abort to incident-sim, calls `record_outcome` with the tombstone, and returns `FAILED_NO_COMMIT` (reason `cancelled_before_send` or `expired`). No job is created by either MCP server. For `search_procedures` in vector mode, mcp-read computes the query embedding with `nomic-embed-text` (`search_query:` prefix) and passes it to `search_procedures_scoped` [R6].

- Every tool has an input JSON Schema in `schemas/tools/`. Arguments that supply a role, tenant, actor, approval or destination are rejected.
- **The envelope must agree with the data:**
  - `status=ok` only for a read with data, or `SUCCEEDED`;
  - `status=outcome` for `UNKNOWN` / `CONFLICT` / `FAILED_NO_COMMIT`, with `data.action_id` required;
  - for an **authenticated, authorized** caller, `status=error` only before any grant exists;
  - authentication and authorization failures always return a plain safe error, never with an `action_id`.
- `abort_incident` result `data`: `{action_id, outcome: SUCCEEDED|FAILED_NO_COMMIT, receipt|tombstone}`.
- The old `unknown` envelope status is removed.
- The caller verifies that a `SUCCEEDED` receipt's hash equals the proposal hash. A mismatch becomes `CONFLICT`.

## AM-16 Routers (new in 1.3.4) → ADR-0003

Routing is explicit, enumerable and deterministic-first. Model output may hint at a route; it never selects one. An input the router cannot classify becomes a clarification or a 422 and never starts work (R129).

**Admission router** (`api`, replaces the implicit §7 rules):

| Route | Trigger | Effect |
|---|---|---|
| `investigate` | `kind=investigate` with a resolvable asset and interval, no active run in the conversation | message + run + `investigate` job + event in one transaction, 202 |
| `clarification_reply` | reply bound to an outstanding clarification ID and expected version | message + `resume_input` job, 202 |
| `status_question` | `kind=status` or text matching the status grammar with no asset/interval change | answered from recorded events and state; **no job** |
| `readonly_answer` | `kind=ask` (a question about evidence, no incident intent) | `investigate` job flagged `answer_only`; the graph can end ANSWERED but never freezes a proposal |
| `reject` | unroutable, conflicting structured fields vs text, over limits, or a second active run | 422 / 409 with a safe error; nothing written except the idempotency record |

Optional model-assisted intent classification runs **after** the deterministic rules and can only downgrade a route to `reject`/clarification, never upgrade one.

**Graph router** (`route_request` node in the orchestrator): a route table in `core/routing.py` maps `(run state, context resolved?, evidence sufficient?, draft kind, decision present?, attempt state)` to exactly one of `clarify`, `retrieve`, `draft`, `answer_only`, `abstain`, `freeze`, `await_decision`, `execute`, `recover`, `publish`. Conditional edges are generated from that table; a test enumerates every row and asserts the node reached (R129).

**Model router** (`DraftGenerator` factory in the worker): selects `fake` (deterministic substitute), `qwen3:8b` (local Ollama) or a future named model from `MODEL_MODE` and policy; the choice, model digest and prompt version are written to the run manifest and the `explanation.ready` event; there is **no silent fallback** between routes (R130, R041).

`docs/ARCHITECTURE.md` §2 is the reader's map; AM-80 adds `schemas/route.schema.json` (the three route enums) and `schemas/run-manifest.schema.json`.

## AM-20 Authority boundaries (amends §6, §9, §13) — rewritten in 1.3.3 [R6-H1..H6]

The 1.3.2 matrix could not run the system (the API could not create jobs or events; the worker could not update runs) and its definer functions were names only. This section replaces it. Three principles:

1. **Every state transition, decision, grant, attempt step and event goes through a `SECURITY DEFINER` function.** Runtime roles never UPDATE `runs.state`, never INSERT into `events`, `decisions`, `proposals`, `execution_grant` or `action_attempt_state` directly.
2. **Audit tables are append-only, so "state" is the latest row, never an UPDATE.** `action_attempt_state` and `run_state_history` are insert-only; `runs.state` is a denormalized copy maintained only by `transition_run`.
3. **Functions decide by `session_user`,** which stays the invoking login role inside a `SECURITY DEFINER` body. Each function has an allowed-caller list and raises for any other role.

### AM-20.1 Roles

| Role | Login | Purpose |
|---|---|---|
| `migrator` | yes (DDL only) | Alembic; owns tables and schemas; never used at runtime |
| `app_definer` | **no** | Owns every definer function; **owns no tables**; has the AM-20.5 RLS policies |
| `api` | yes | FastAPI process |
| `worker` | yes | Workflow worker |
| `sweeper` | yes | Scheduler process (expiry, membership sync, wake-up sweep, outbox delivery) |
| `mcp_read` | yes | mcp-read; read-path functions only |
| `mcp_exec` | yes | mcp-write; write-path functions only |
| `operator` | yes | Local operator CLI; one function only |
| `test_harness` | yes, **test profile only** | Writes `app.test_clock`; created by the `testclock` Alembic branch |
| `incident` | yes (separate database) | incident-sim |

### AM-20.2 Exact table grants (schema `app`)

Only these grants exist. Anything not listed is denied. "ins" = INSERT, "upd(cols)" = UPDATE on exactly those columns, "sel" = SELECT, "del" = DELETE.

| Table | `api` | `worker` | `sweeper` | `app_definer` | `mcp_read` / `mcp_exec` / `operator` |
|---|---|---|---|---|---|
| `tenants`, `memberships` | sel | sel | sel, upd(`active`, `permission_version`, `synced_at`) | sel | — |
| `sessions` | sel, ins, upd(`last_seen_at`, `revoked_at`), del | — | del (expired) | — | — |
| `conversations`, `messages` | sel, ins | sel | — | sel | — |
| `runs` | sel, ins, upd(`cancel_requested`, `cancel_requested_at`) | sel, upd(`checkpoint_id`, `next_event_seq`, `budget_used`) | sel | sel, upd(`state`, `state_version`, `reason`, `active_proposal_id`, `next_event_seq`, `slot_held`) | — |
| `run_directory` (run_id, tenant_id; no RLS) | ins | sel | sel | sel | — |
| `run_state_history` | — | — | — | ins | — |
| `run_lease` | — | sel, ins, upd(all) | sel, upd(`lease_until`) (reclaim) | sel | — |
| `jobs` | ins | sel, ins, upd(`claimed_by`, `claimed_at`, `done_at`, `attempts`) | sel, ins, upd(same) | sel | — |
| `invocation_context` (no RLS) | — | ins | sel | sel, upd(`revoked_at`) | — |
| `drafts` (pre-freeze model output, IDs only) | — | ins, sel | — | sel | — |
| `proposals` | sel | sel | sel | ins, sel | — |
| `decisions` | sel | sel | — | ins, sel | — |
| `execution_grant` | sel | sel | sel | ins, sel | — |
| `action_attempt`, `action_attempt_state` | sel | sel | sel | ins, sel | — |
| `events` | sel | sel | sel | ins, sel | — |
| `outbox` | ins | ins | sel, upd(`leased_until`, `attempts`, `delivered_at`, `result`) | ins | — |
| `feedback` | ins, sel | — | — | — | — |
| `idempotency_request` | sel, ins | — | del (expired) | — | — |
| `operator_resolutions` | sel | — | — | ins | — |
| `documents`, `chunks`, `embeddings` | — | ins, sel (ingestion) | — | sel | — |
| `model_permit` | — | sel, upd(all) | upd(`leased_until`) (reclaim) | — | — |
| `app.test_clock` (test profile only) | — | — | — | sel | `test_harness`: ins, upd, del |
| schema `checkpoints` | — | all DML | — | — | — |

Notes:
- `mcp_read`, `mcp_exec` and `operator` have **no table grants**; the right-hand column is only for `test_harness`.
- `runs.state` is written only by `app_definer` (through `transition_run`). The `api` column grant on `cancel_requested` cannot set state, because UPDATE is column-scoped.
- `execution_grant` has no `state` column; grant status is derived from the latest `action_attempt_state` row.
- `proposals` rows are inserted already frozen by `freeze_proposal`, so proposals never need UPDATE. Pre-freeze drafts live in `drafts`.

### AM-20.3 Definer functions

All functions: `SECURITY DEFINER`, owner `app_definer`, `SET search_path = app, pg_temp`, `SET app.tenant_id = ''` as a function attribute. Each migration that creates one runs, in the same transaction, `REVOKE ALL ON FUNCTION … FROM PUBLIC` and then `GRANT EXECUTE … TO <exactly the callers listed below>` [R6-H2]. Every function first resolves `tenant_id` through `run_directory` (or the handle) and sets `app.tenant_id` before touching tenant rows, takes locks in the AM-12 order, and raises `authority_violation` when `session_user` is not an allowed caller.

| Function | Callers | Inputs | Locks (in order) | Effect | Event |
|---|---|---|---|---|---|
| `transition_run(run_id, from_state, to_state, reason, expected_version)` | `api` (only → CANCELLED before grant, → QUEUED on revision), `worker`, `sweeper` (only → BLOCKED_REVIEW on expiry) | as named | `runs` FOR UPDATE | Validates the AM-10 table, the caller's allowed targets and `expected_version`; updates `runs.state`/`state_version`/`reason`; inserts `run_state_history`; maintains `slot_held` and the conversation slot (partial unique index on `runs(conversation_id) WHERE slot_held`) | the matching `run.*` / `review.blocked` event via `append_event` |
| `append_event(run_id, type, payload)` | `api`, `worker`, `sweeper` | as named | `runs` FOR UPDATE (for `next_event_seq`) | Inserts an event with `source` derived from `session_user` (`api`/`worker`/`sweeper` → `application`; `worker` may pass `source=model_summary` only for `explanation.ready`). **Refuses** `action.*`, `run.*` and `review.*` types from these callers; those are emitted only by the functions below | the event |
| `freeze_proposal(run_id, draft_id, authored_by[])` | `worker` | run and draft IDs | advisory(tenant, asset) → `run_lease` FOR SHARE → `runs` FOR UPDATE → `proposals` | Asset guard (AM-13); canonicalizes bytes, computes hash, inserts the immutable `proposals` row with `revision = max+1`; sets `runs.active_proposal_id`; transition DRAFTING → AWAITING_APPROVAL, or → BLOCKED_REVIEW on guard refusal | `proposal.ready` or `review.blocked` |
| `record_decision(proposal_id, expected_payload_sha256, decision, reason, idempotency_key)` | `api` (reviewer identity = the API's authenticated `sub`; the API is the identity trust anchor) | as named | `runs` FOR UPDATE → `proposals` FOR SHARE → `decisions` → `memberships` FOR SHARE | Checks current membership, reviewer ∉ `authored_by`, active unexpired revision, hash equality, first-decision-wins, lazy expiry (→ BLOCKED_REVIEW); inserts the decision; transition → APPROVED or REJECTED; on approval inserts the `execute` job (dedup `proposal_id`) | `approval.recorded` / `run.rejected` |
| `create_revision(run_id, expected_version, author)` | `api` | as named | `runs` FOR UPDATE → `execution_grant` FOR SHARE | Refuses (`GRANT_EXISTS`) if a grant exists; refuses (`SLOT_OCCUPIED`) if the conversation has another active run; transition APPROVED/BLOCKED_REVIEW/AWAITING_APPROVAL → QUEUED; appends `author` to `authored_by`; inserts an `investigate` job (dedup `run_id:revision+1`) | `proposal.revised` |
| `create_manual_proposal(run_id, payload, author)` | `api` | payload per `manual-proposal` schema | same as `freeze_proposal` | Tenant-scopes asset and evidence IDs (404 otherwise); otherwise identical to `freeze_proposal` with `authored_by = [author]` | `proposal.ready` |
| `expire_proposal(run_id)` | `sweeper`; also invoked internally by `record_decision`/`grant_execution` | run ID | `runs` FOR UPDATE → `proposals` FOR SHARE | If the active proposal's `expires_at < app.current_time()`: transition AWAITING_APPROVAL/APPROVED → BLOCKED_REVIEW(`expired`) | `review.blocked` |
| `request_cancel(run_id, expected_version)` | `api` | as named | `runs` FOR UPDATE → `execution_grant` FOR SHARE | Sets `cancel_requested`; if no grant exists, transition → CANCELLED now; otherwise returns `{grant_exists, attempt_state}` for the cancel-response | `run.cancelled` or none |
| `resolve_invocation(raw_handle, client_azp)` | `mcp_read`, `mcp_exec` | the header value and the token's `azp` | `invocation_context` FOR SHARE → `run_lease` FOR SHARE | Hashes the handle inside; checks azp binding, **that the handle's server matches the calling role** (read handles only for `mcp_read`, execute/recover handles only for `mcp_exec`), expiry, current run fence; returns `{run_id, tenant_id, job_type, run_state, attempt_state, allowed_tools}` with the allowlist derived per AM-15 | none |
| `asset_scope(raw_handle)` | `mcp_read` | handle | as above | Returns the run's `tenant_id`, `asset_id`, `[start_at, end_at)` for forwarding to asset-sim | none |
| `search_procedures_scoped(raw_handle, query, query_embedding vector(768) NULL, asset_type, limit, mode)` | `mcp_read` | handle, text query, optional embedding computed by mcp-read with the `search_query:` prefix | as above | Lexical (`mode=lexical`) or exact vector (`mode=vector`, requires the embedding) search over approved, effective, tenant-permitted chunks; returns IDs, versions, section, hash, excerpt | none |
| `grant_execution(raw_handle, proposal_id)` | `mcp_exec` | as named | advisory(tenant, asset) → `run_lease` FOR SHARE → `runs` FOR UPDATE → `proposals` FOR SHARE → `decisions` FOR SHARE → `memberships` FOR SHARE → `execution_grant` → `action_attempt` | The §13 final gate: proposal belongs to the handle's run and tenant; approved, unexpired, hash-matching; requester and reviewer currently active; not cancelled; asset freshness (5 min); **asset guard (AM-13)**; inserts `execution_grant` (random `action_id`, `UNIQUE(run_id)`), `action_attempt` 1 and `action_attempt_state` INTENT; transition APPROVED → EXECUTING (or → BLOCKED_REVIEW with the refusal reason) | `action.granted` (new type) or `review.blocked` |
| `mark_sent(action_id)` | `mcp_exec` | action ID | `run_lease` FOR SHARE → `runs` FOR UPDATE → `action_attempt_state` | Re-checks `cancel_requested` and the dispatch deadline; inserts state SENT, or returns `cancelled`/`expired` without inserting | `action.dispatched` |
| `record_outcome(action_id, outcome, receipt_or_tombstone)` | `mcp_exec` | the verified destination result | `run_lease` FOR SHARE → `runs` FOR UPDATE → `action_attempt_state` → `events` | Idempotent; inserts state RESOLVED; verifies the hash; transition EXECUTING/OUTCOME_UNKNOWN/ESCALATED → SUCCEEDED, FAILED(reason) or ESCALATED(`conflict`); on a terminal run, records late evidence without a transition | `action.confirmed` / `action.failed` / `action.conflict` / `action.late_evidence`, all with `source=destination` |
| `request_abort(action_id, reason)` | `mcp_exec` | reason ∈ {`cancelled_before_send`, `expired`, `deadline`} | as `record_outcome` | Marks the current attempt as aborting; the caller then POSTs abort to incident-sim and calls `record_outcome` with the tombstone. If the attempt is INTENT (never sent), the outcome is FAILED(`cancelled_before_send` or `expired`) | via `record_outcome` |
| `lookup_action(raw_handle)` | `mcp_exec` | handle | `run_lease` FOR SHARE | Returns the grant's `action_id`, canonical bytes and hash for same-key redispatch (no gate re-run) | none |
| `mark_unknown(run_id, fence)` | `worker` (transport-timeout path, AM-13) | as named | `run_lease` FOR UPDATE → `runs` FOR UPDATE → `execution_grant` FOR SHARE | Bumps the fence (revoking handles); if a grant exists, transition EXECUTING → OUTCOME_UNKNOWN and inserts a `recover` job | `action.uncertain` |
| `escalate_run(run_id, reason)` | `worker`, `sweeper` | reason ∈ {`conflict`, `escalation_deadline`} | `runs` FOR UPDATE | Transition EXECUTING/OUTCOME_UNKNOWN → ESCALATED; releases the conversation slot | `run.escalated` |
| `resolve_escalation(run_id, operator_name, reason)` | `operator` | self-asserted operator name, reason | `runs` FOR UPDATE → `operator_resolutions` | Transition ESCALATED → ABANDONED_UNVERIFIED; inserts the resolution row | `run.abandoned_unverified` |
| `sync_memberships(payload)` | `sweeper` | the Keycloak sync result | `memberships` FOR UPDATE | Deactivates memberships of disabled or deleted users; records `synced_at` | none |
| `reclaim_leases()` | `sweeper` | none | `run_lease` FOR UPDATE | Expired leases become reclaimable; stale `model_permit` released; lost wake-ups re-enqueued (dedup keys) | none |

Internal helpers (`_canonicalize`, `_asset_guard`, `_allowlist`) are not granted to any role.

**Who performs which transition** (closes R6-H3):

| Transition | Function |
|---|---|
| QUEUED → RETRIEVING → DRAFTING → AWAITING_INPUT / ANSWERED / INSUFFICIENT_EVIDENCE / FAILED | `transition_run` called by `worker` |
| DRAFTING → AWAITING_APPROVAL / BLOCKED_REVIEW | `freeze_proposal` |
| AWAITING_APPROVAL → APPROVED / REJECTED / BLOCKED_REVIEW | `record_decision` (and `expire_proposal`) |
| APPROVED / BLOCKED_REVIEW → QUEUED | `create_revision` |
| any active state → CANCELLED (no grant) | `request_cancel` |
| APPROVED → EXECUTING / BLOCKED_REVIEW | `grant_execution` |
| EXECUTING → OUTCOME_UNKNOWN | `mark_unknown` |
| EXECUTING / OUTCOME_UNKNOWN / ESCALATED → SUCCEEDED / FAILED | `record_outcome` (FAILED(`cancelled_before_send`) included) |
| EXECUTING / OUTCOME_UNKNOWN → ESCALATED | `escalate_run`, or `record_outcome` on CONFLICT |
| ESCALATED → ABANDONED_UNVERIFIED | `resolve_escalation` |

### AM-20.4 Jobs, dedup keys and creators

`jobs(id, type, run_id, dedup_key UNIQUE, available_at, claimed_by, claimed_at, attempts, done_at)`.

| `type` | Inserted by | `dedup_key` |
|---|---|---|
| `investigate` | `api` (admission), `create_revision` | `run_id:revision` |
| `resume_input` | `api` | `run_id:clarification_event_id` |
| `execute` | `record_decision` | `proposal_id` |
| `recover` | `mark_unknown`, `worker` (after a `cancelled`/`expired` result), `reclaim_leases` | `action_id:trigger` where trigger ∈ {`timeout`, `cancel`, `deadline`, `sweep:<bucket>`} |
| `expire_proposals`, `sync_memberships`, `sweep_wakeups`, `deliver_outbox` | `sweeper` scheduler | `name:<minute bucket>` |

`recover` jobs on ESCALATED or ABANDONED_UNVERIFIED runs run on a bounded cadence: every 5 minutes for the first hour, then hourly, with a cap of 48 attempts, after which only the operator CLI or late destination evidence changes anything. The cadence is recorded in AM-13's defaults.

### AM-20.5 Row-level security

Every tenant table (`memberships`, `conversations`, `messages`, `runs`, `run_state_history`, `jobs`, `drafts`, `proposals`, `decisions`, `execution_grant`, `action_attempt`, `action_attempt_state`, `events`, `outbox`, `feedback`, `documents`, `chunks`, `embeddings`) has `ENABLE ROW LEVEL SECURITY` and `FORCE ROW LEVEL SECURITY` (so even `migrator`, the owner, is subject to it) and exactly these policies [R6-H4]:

```sql
CREATE POLICY tenant_isolation ON <table>
  FOR ALL TO api, worker, sweeper, app_definer
  USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
```

- `app_definer` is a non-owner, so without this policy every definer function would see zero rows.
- `api`, `worker` and `sweeper` set `app.tenant_id` themselves per transaction, so for them RLS is **defense in depth** against application bugs, not a boundary against a compromised credential. The threat model says so.
- `run_directory`, `invocation_context`, `run_lease`, `sessions`, `idempotency_request`, `operator_resolutions`, `model_permit`, `tenants` and `app.test_clock` have **no RLS**; their grants (AM-20.2) are the control.
- R106 asserts the policy text per table (`pg_policies`) and that the definer path cannot read another tenant's rows.

### AM-20.6 Test clock

- `app.current_time()` is defined as: if `to_regclass('app.test_clock') IS NULL` then `clock_timestamp()`, else `clock_timestamp() + (EXECUTE 'SELECT offset FROM app.test_clock LIMIT 1')`. The dynamic `EXECUTE` avoids a static reference to a missing table.
- The table is created by the Alembic branch `testclock`, which only `scripts/check.py --profile test` applies. The `dev` and `demo` bootstraps assert `to_regclass('app.test_clock') IS NULL` and refuse to start otherwise.
- Only `test_harness` may write it. GUCs are never read (R126).

### AM-20.7 Everything else (unchanged from 1.3.2, renumbered)

- **Proposals are bound to runs** (R100); **independence covers every content author** (R093); **revocation** (a)–(c) with fail-closed admin-API checks (R086); **MCP token verification** with `MCP_RESOURCE_URL` audiences and a custom `TokenVerifier`; **checkpoint tables** in schema `checkpoints` with `worker`-only DML (R122); **graph state is IDs only** (R091); **fault hooks** only in the `core.testing.faults` factory under `PROFILE=test` (R098); **server-side sessions**; **`X-Ops-Invocation` is a lookup key only**.

The retained 1.3.2 items, unchanged in substance:

3. **Proposals are bound to runs.** Every write or recovery function requires `proposal.run_id = handle.run_id` and the same tenant (R100).
4. **Independence covers every content author.** The proposal records `authored_by` (requester plus revision and manual-proposal authors), and the reviewer must not be in it (R093).
5. **Revocation** (replaces the 1.1 wording):
   - (a) Back-channel logout: the API hosts a hand-written OIDC Back-Channel Logout endpoint (validates iss, aud, iat, jti, events; no nonce; jti replay cache) that destroys sessions.
   - (b) **Every** decision, revision, cancel and manual-proposal mutation checks the user's enabled status through the Keycloak admin API.
     - It uses a local-only service account limited to `view-users`, whose secret is generated by the bootstrap.
     - The call has a 2 s timeout and uses a cached service-account token.
     - If Keycloak is down or slow, it **fails closed** with 503 `retryable`.
     - The user ID it checks is the token's `sub`, which T05 asserts equals the Keycloak user ID.
   - (c) A membership sync job (every 60 s) deactivates memberships of disabled users, and `grant_execution` reads membership.
   - Bounds:
     - a disabled user's next decision-class mutation gets 401;
     - a disabled requester or reviewer blocks grants within ≤60 s;
     - session-only reads end on back-channel logout or idle expiry.

   Tested by R086.
6. **MCP token verification.**
   - Keycloak "Hardcoded audience" mappers set `aud` to the **resource URLs** of mcp-read (`MCP_READ_RESOURCE_URL`) and mcp-write (`MCP_WRITE_RESOURCE_URL`) and to `incident-sim`; each is a parameter, not a hard-coded container name. asset-sim trusts only the mcp-read workload token and the tenant/asset context it forwards, and applies its own tenant filter; incident-sim trusts only mcp-write.
   - T05 fixes `KC_HOSTNAME`, so that `iss` is identical for host and container callers.
   - Both MCP servers use a custom `TokenVerifier` that checks iss, aud ∋ its own resource URL, azp ∈ its allowed workload clients, and exp.
   - Tests cover a missing `aud`, a wrong `aud`, and a browser token.
7. **Checkpoint tables.**
   - `migrator` runs `PostgresSaver.setup()` with `autocommit=True`, `row_factory=dict_row` and `options=-c search_path=checkpoints` (the saver has no schema parameter).
   - `worker` gets DML only on schema `checkpoints`, with `search_path=checkpoints,pg_temp` on its checkpoint connection.
   - `api` gets permission denied (R122).
8. **Graph state is IDs only.** Interrupt payloads and graph state carry IDs and hashes only (R091).
9. **Fault hooks are test-only.** They exist only in an app factory, shared as `core.testing.faults`, that refuses to start unless `PROFILE=test` (R098; first used in T10, completed in T13). The test clock is governed by AM-20.6, not by `PROFILE`.
10. **Browser sessions are server-side.** A Postgres `sessions` table holds an opaque random ID (stored hashed) in an HttpOnly cookie. authlib's OIDC state lives in that store, not in Starlette's signed-cookie `SessionMiddleware`.
11. **`X-Ops-Invocation` is a capability lookup key only.** It is never trusted as identity and never logged. The SDK warns that headers are client-supplied.

## AM-30 Protocol, libraries and versions (amends §2, §10, §19, §22, §29)

**Protocols and SDK:**
- MCP protocol revision **2026-07-28** (session-less; `io.modelcontextprotocol/protocolVersion` in `_meta` must match the `MCP-Protocol-Version` header).
- Tests check per-request version validation and mismatch rejection, not "negotiation".
- Imports: `from mcp.server.mcpserver import MCPServer, Context` and `from mcp import Client`.

**Versions observed on 2026-10-06** (exact pins live in `uv.lock`):

| Component | Version |
|---|---|
| mcp | 2.3.0 (pulls `mcp-types==2.3.0`, `httpx2`) |
| langgraph | 1.2.14 |
| langgraph-checkpoint-postgres | 3.1.2 |
| langchain-ollama | 1.1.0 |
| authlib | 1.8.0 |
| pgvector-python | 0.5.0 |
| Keycloak | **26.8.x** (pinned image digest) |
| kind | v0.33.0 (M15) |
| Ollama | installed 0.33.3; latest 0.35.1. Record the version actually used, and upgrade only with owner approval. |

**kind (M15):** use the default CNI (kindnet with kube-network-policies, since v0.24). Do not install Cilium.

**Citation fixes:** "not external exactly-once" and "temperature 0 does not guarantee identical outputs" are project reasoning. No S05 redirect was observed.

## AM-31 Model runtime profile (amends §12, §17)

- **Model:** `qwen3:8b`, selected by the model router (AM-16); the route, digest and prompt version are recorded per run. Record its digest.
- **Settings:** `ChatOllama(reasoning=False)` (maps to Ollama `think:false`), `num_ctx=16384`, `num_predict=1000`, `temperature=0`, 60 s timeout, `with_structured_output(method="json_schema")` **plus** application-side validation.
- **Warm-up:** a cold model load took 53 s in the round-4 dry run, against the 60 s timeout. The worker therefore issues a warm-up call (with `keep_alive`) at startup, before it accepts drafting jobs, and T02 measures cold vs warm latency.
- **Digest check:** at warm-up the worker compares the model digest (`/api/show`) with the pin in **`data/model-pins.json`** (`{model, digest, ollama_version, probed_at}`, written by T02) and **fails closed** on mismatch. Owned by T19 and tested by R127 [R5-S9, R6-B4].
- **Network exposure (owner decision):** Ollama is reachable only from loopback and the Docker/WSL subnet.
  - The owner applies the firewall restriction, using commands documented in `docs/runbooks/ollama-network.md` (T05). The agent does not change system settings.
  - Every other published port (Postgres, Keycloak, services) binds to `127.0.0.1`.
- **T02 probe** [R3-B11]:
  - Uses **at least 30 distinct inputs**, authored for the probe under `evals/probe/`. These are separate from the 10 development seeds and from the holdout.
  - Runs in an isolated environment (`uv run --isolated --with langchain-ollama==1.1.0 …`), with the dependency freeze saved next to the report.
  - Measures the **identical-repeat rate** (the same input 3× at temperature 0), which tells T25 whether repeated trials carry information.
  - The probe is a measurement, **not prompt tuning** [R4-E2]. It uses the delivered prompts unchanged:
    - `handoff/prompts/incident-draft-v1.md` (sha256 `e3c26da349dcb0a9bfafb6c786a06f15fece389c21fa63b1b64fef7659b6a942`);
    - `handoff/prompts/schema-repair-v1.md` (sha256 `8b6658eb0f08136699b78e7ab1d76972f88f4399db720e92e5be5335b0c7c343`).
  - T03 records both hashes externally together with the holdout seal.
  - Outputs are validated against the 1.0 `schemas/model-draft.schema.json`.
  - Each probe input carries a small synthetic evidence bundle, because the corpus doesn't exist yet.
  - Command form: `uv run --isolated --no-project --with langchain-ollama==1.1.0 …`. The dependency freeze is written via `importlib.metadata`, because uv environments have no pip.
  - Cold-start and warm latency are reported separately.
  - It records:
  - JSON-valid and schema-valid rates, both first-pass and after one repair, with Wilson 95% CIs;
  - p50/p95 latency;
  - peak VRAM;
  - whether any thinking content appears;
  - **cancellation behaviour:** cancel mid-generation, then check `ollama ps`/GPU and the next request's start latency.
- **There is no fixed pass threshold.** The owner reviews the measured rates and decides whether to proceed, change the model, or adjust prompts (R081). If thinking cannot be disabled, the probe fails.

## AM-40 UI states for v1 (amends §16)

The eight states are:
1. loading/queued
2. collecting context
3. retrieving/drafting
4. awaiting independent review (stale/expired disabled with a reason)
5. executing / outcome unknown
6. succeeded
7. failed / rejected / insufficient evidence / escalated / abandoned-unverified / cancelled, with its reason
8. session expired / disconnected-then-reconnected snapshot

ANSWERED is shown as a completed conversation answer within state 6's view, labelled "answered (no action)".

Each state has a Playwright assertion (R117). State 8's reconnect assertion lands with SSE in T27.

## AM-50 Evidence corpus and evaluation (amends §11, §20, §27)

**Corpus:**
- at least 12 authored documents of 300–900 words each, at least 6 assets, 2 tenants;
- superseded/expired versions, one injected-instruction document per tenant, and one conflicting-procedure pair;
- evidence IDs are per section, with per-section `sha256`;
- tenant slugs map to seeded UUIDs, and alert IDs are UUIDs with revisions;
- embeddings use `nomic-embed-text` with the `search_document:` and `search_query:` prefixes, with a test that they are applied.

**Scenario suite** (deterministic, R097):
- 30 of the 32 development cards become executable pytest scenarios, each asserting final application and destination state.
- DEV-013 (multi-replica checkpoints) and DEV-032 (upgrade) are deferred with M15.
- Cards join the suite as their capabilities land: the core cards after T22, SSE cards in T27, budget cards in T29, the restore card in T32.

**Model-quality evaluation** (real qwen3:8b):

| Element | Design |
|---|---|
| Development set | About 60 cases with gold labels and a groundedness rubric (T23) |
| Holdout, part 1 (T03) | About 25 **owner-authored** case intents and requests, written now, without AI assistance, before any prompt tuning. Uses the case schema `evals/holdout-case.schema.json`. |
| Holdout, part 2 (T41) | The owner gold-labels the sealed cases against the **frozen T17 corpus** (evidence IDs, expected outcome), then re-seals. |
| Holdout custody | Stored **off this machine** (or encrypted with a key the agent never sees) until a release-candidate run. Only the `sha256` and case count are committed. Each seal hash is **also recorded outside the local repo** before the next dependent task starts: either pushed to the remote, or emailed to the owner with the hash and date, since a local git history can be forged. Every holdout run is logged. |
| Conditions | A: manual baseline (human-authored proposal via `/manual-proposals`). B: RAG-only single call. C: orchestrated. B and C use identical model, prompt-version family, retrieval settings and `num_ctx`. Schema metrics apply to B and C only. **A is scored only with deterministic metrics** (citation validity, abstention correctness), because the owner wrote both A and the holdout. |
| Labelling | Groundedness labels for B and C are **blind**: outputs are anonymized and shuffled across conditions. About 20% are re-labelled later to report intra-rater kappa (R073). |
| Trials | 3 isolated trials per case for B and C |

**Statistics:**
- **Quality metrics:** report at **case level** (a case passes if at least 2 of 3 trials pass) with Wilson 95% CIs and denominators. Also report trial-level rates with a case-cluster bootstrap CI, because the 2-of-3 rule inflates rates (0.70 per trial → about 0.78 per case).
- **Safety metrics are any-trial:** a single unauthorized write, fabricated success or cross-tenant leak in any trial fails the case.
- **Comparisons:** paired exact McNemar tests on case-level outcomes. No ranking claim without p < 0.05.
- **Power at n≈25** [R3, computed]: exact McNemar power is about 0.15 for a 15-point difference and about 0.5–0.8 for 30 points. **Only differences of roughly 30 points or more are reliably detectable**, and the README says so.
- **Unauthorized writes** must be 0 observed. Report the rule-of-three upper bound (≈3/n, about 12% at n=25).

**`evals/quality-gates.json`**, validated against `evals/quality-gates.schema.json` (T23), lists entries of the form `{metric, condition, threshold, applies_to: "point"|"wilson_lower_95", blocking}`:
- The owner fills it in and commits it **before** the first holdout run.
- Safety gates (unauthorized writes, fabricated success, cross-tenant leakage) are blocking at 0 observed.
- Quality gates are owner-chosen.

**Labelling load estimate:** about 85 cases × 3 trials × 2 model conditions ≈ 510 outputs, plus 85 manual baselines. Use deterministic graders wherever possible (citations, schema, abstention); owner labels only groundedness.

**Solo-owner limitation:** §27's independent reviewer is replaced by owner authorship, off-machine custody and hash-locking. The README states this.

## AM-60 Task graph (amends §25, `handoff/tasks.json`)

`handoff/tasks.json` 1.3.4 has 47 tasks. IDs are stable since 1.2; new tasks are appended.

**1.3.4 changes** [ADR-0003]:
- T15 becomes mcp-read; new **T47** builds mcp-write (R030, R131). T16 keeps the read tools; recovery tools move to T47. T22 depends on T47. T08 runs both servers.
- T12 implements the admission router (R129); T20 the graph router node (R129); T19 the model router and run-manifest recording (R130). T25 reads the manifest.
- `docs/ARCHITECTURE.md` is the showcase map; T34 keeps it current and the README links it.

**1.3.3 changes** [R6]:
- Splits: T04 → T04 (workspace, lock, `scripts/check.py`, seed IDs, jsonschema) + **T42** (reference move, hash remap, manifest to provenance, zip-based `--manifest`). T05 → T05 (what T08 needs) + **T43** (remaining personas, `view-users` service account, bootstrap-admin deletion, topology doc) + **T44** (Ollama bridge, `docs/runbooks/ollama-network.md`). T07 → T07 (core contracts, state machine, job model, reason enum) + **T45** (AM-80 schema alignment, negative probes, checker) + **T46** (reference traceability and pure-core port).
- T08 depends on T05 and T07 only. T45 runs after T42 (both edit the checker). T19 depends on T44 and T02. T11 depends on T43.
- T09 owns the AM-20 rewrite in code (grants, functions, policies, test clock) with R124/R106/R126 and new R128 (every transition and event goes through a definer function).
- R127 (model digest pin) owned by T19; `data/model-pins.json` written by T02.
- The walking-skeleton debt list is recorded in SESSION_STATE.md before T08 starts [R6-B7].
- `provenance/handoff-1.0.zip` committed [R6-B1].

**1.3.1 changes** [R4]: E1–E6 applied to T01, T02, T03, T04 and T07; M00 order is now T01, T03, T02.

**1.3 changes** [R3]:
- T03 is split: T03 seals the holdout intents, and the new **T41** gold-labels them against the frozen corpus. T02 and T19 depend on T03; T25 depends on T41.
- T04 no longer depends on T02. T04 moves the reference to `reference/`, creates `data/seed-ids.json`, adds `jsonschema` to the dev group, and makes the checker skip venv and `node_modules` directories.
- T05 reads `data/seed-ids.json` and fixes the Keycloak topology.
- T07 ports the pure-core tests plus `reference/TRACEABILITY.md`, updates `verify_handoff.py`, and completes AM-80.
- T08 names its processes, uses real T05 tokens, and makes its schema Alembic revision 1.
- T17 moves to M05 ahead of T16. M05 becomes "MCP boundary and governed corpus".
- Requirement placement: R002 → T34; R031 → T04 (imports) and T15 (network); R046 co-owned by T22; R071 co-owned by T25; R098 co-owned by T10.
- Round-3 LATER items are attached as `review_notes`.

**1.2 changes:**

**New tasks:**
- T03 owner holdout authoring;
- T05 dev bootstrap (Compose dev profile, Keycloak realm and workload clients, secret generation, seed UUIDs);
- T06 early secret-free CI;
- T08 **walking skeleton**: fake model, real Postgres, real HTTP across api → worker → MCP → incident-sim, before hardening;
- T23 development eval set and rubric.

**Other changes:**
- Dependencies follow real data dependencies (round-2 edits).
- Oversized tasks are split.
- Requirements are re-homed (R022 → workflow, R023 → decisions, R014/R035 → web, R049 → execution).
- R066 is rewritten as the Docker-network requirement (v1). The cluster part is R112 (M15).
- Every requirement has a `suggested_test` path.
- `external_approval_required` is true for T03, T06, T31, T34, T39 and T40.

## AM-70 Reference code defects (do not port)

Do **not** port these behaviours:
- deterministic `action_key` (`service.py:176`);
- network or tool I/O inside the write transaction (`service.py:172`);
- catching only `UncertainOutcome` (`service.py:182`);
- stuck EXECUTING after a crash (`service.py:175-178`, `:213-216`);
- full proposal text in `interrupt()` (`integrations/langgraph_workflow.py:38`);
- plaintext token file (`scripts/init_demo.py:18-23`);
- `internal: true` network with a published port (`compose.yaml`).

Replace the weak reference tests (`test_duplicate_decision_and_execute`; no concurrent `decide`/`execute` test) with concurrent target tests.

## AM-80 Schema, example and fixture alignment (owned by T45)

The delivered `schemas/`, `schemas/examples/` and `data/handoff-fixtures/` still describe 1.0. T45 updates them and proves the result with `scripts/verify_handoff.py --contracts` plus new negative probes (R104).

**Checker changes** (T45; the zip-based `--manifest` is T42) [R3-B9]:
- Read `expected_payload_sha256` from the decision example.
- Meta-validate `schemas/tools/*.json` and `evals/*.schema.json`.
- Skip `.venv*`, `node_modules` and `reference/` build outputs in its `rglob` scans.
- Read and write all files with `encoding="utf-8"` (this machine's locale is cp1252).
- Reject `\r` in fixtures, schemas, examples and prompts, so hashes match across platforms [R4-E5].

**Negative probes:** before writing contract code, T45 commits **at least one negative example per AM-80 row**, each listed in `schemas/examples/index.json` with the reason it must fail. R104 passes only if every one fails for that stated reason.

`jsonschema` is a dev dependency (T04).

| Artifact | Required change |
|---|---|
| `event.schema.json` | Add `ESCALATED` and `ABANDONED_UNVERIFIED` and the AM-14 event types; payload `reason` and `outcome`; `action.confirmed` requires a receipt and SUCCEEDED; `action.late_evidence` requires `outcome` plus a receipt or tombstone; source rules |
| `tool-result.schema.json` | `status=outcome`; remove `unknown`; envelope/data agreement; `action_id` required on outcomes for authorized callers; `next_cursor`; `abort_incident` result shape |
| `model-draft.schema.json` | Add optional `question` (required for clarification; AM-10) |
| New: `feedback`, `manual-proposal`, `revision`, `cancel-response` schemas | Per §7 and AM-14. `cancel-response` reports whether a grant or dispatch already occurred. |
| `error.schema.json` | Codes `ASSET_ACTION_UNRESOLVED`, `ASSET_INCIDENT_EXISTS`, `GRANT_EXISTS` (409 on revision after grant), `SLOT_OCCUPIED`, `AUTHORITY_VIOLATION` |
| New: `evals/holdout-case.schema.json`, `evals/quality-gates.schema.json` | Defined in T03 and T23 respectively; meta-validated by the checker |
| `schemas/tools/*.json` | Create input schemas for all six tools |
| `action-outcome.schema.json` | `FAILED_NO_COMMIT.reason` (shared reason enum); mapping from ABORTED/REJECTED; tombstone object `{action_id, state, payload_sha256, reason, decided_at}` |
| New: `schemas/model-pins.schema.json` | `{model, digest, ollama_version, probed_at}` (AM-31) |
| New: `schemas/route.schema.json`, `schemas/run-manifest.schema.json` | The three route enums (AM-16); the per-run manifest `{run_id, model_route, model_digest, prompt_version, corpus_version, retrieval_mode}` |
| `event.schema.json` (addition) | New type `action.granted`; `source=destination` only for `action.confirmed/failed/conflict/late_evidence` |
| New: `schemas/job.schema.json` | The AM-15 job-type table as an enum with allowed tools and run states |
| `decision.schema.json` + examples | `expected_payload_sha256` |
| `examples/tool-get_incident_receipt-valid.json` | Uses `status=outcome` |
| `examples/draft-valid.json` / `tool-get_recent_alerts-valid.json` | Make the alerts consistent (the draft says "two warnings", the alerts example returns `[]`) |
| `examples/index.json` | Version 1.3.3; a stated reason for each negative example |
| `data/handoff-fixtures/` | Tenant UUID mapping; alert UUIDs + revisions; per-section hashes (expanded in T17) |
| `proposal.schema.json` | `start_at < end_at` and UTC-only offsets (enforced in code where JSON Schema cannot). `authored_by` sits **outside** the hashed payload, as a sibling of `payload`, stored and checked at decision time. Optional `supersedes_run_id` **inside** the hashed payload (AM-13). |

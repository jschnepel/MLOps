# OPS-BUILD-1.1 — Amendments to BUILD_SPEC.md

**Status:** Approved by the owner on 2026-10-06 ("amend + cut").
**Precedence:** This file overrides `BUILD_SPEC.md` (OPS-BUILD-1.0) wherever they conflict. Everything not amended here stays in force. ADRs in `docs/adr/` record the reasoning.
**Source:** the adversarial review in `docs/reviews/handoff-review-2026-10-06.md`. Review item numbers appear as `[R#n]`.

Each amendment is meant to be testable. Where a new acceptance requirement is created, its ID (R081+) appears in `handoff/acceptance-matrix.json`.

---

## AM-01 Repository layout (amends §5) → ADR-0001

Each independently deployed process gets its own top-level directory, each with its own `pyproject.toml`, `Dockerfile`, `tests/` and `README.md`:

| Directory | Process |
|---|---|
| `api/` | FastAPI: sessions, admission, decisions, SSE, health |
| `worker/` | Run-lease worker: LangGraph graph, LangChain draft node, MCP client |
| `mcp-server/` | Authenticated MCP server: read tools, guarded write, reconciliation lookup |
| `asset-sim/` | Synthetic asset/alert API (deterministic, injected clock) |
| `incident-sim/` | Synthetic incident destination with its own database and receipts |
| `web/` | React + TypeScript + Vite workspace (M10) |
| `core/` | Shared library (uv workspace member): domain, application use cases, adapters, contracts. **Not** a service. |

The original `src/operations_copilot/` reference stays in place as the reference until its 58 behaviours are re-expressed as `core/` tests (T04). After that it moves under `reference/`. It is never deleted.

## AM-02 Version 1 scope (amends §2, §25, §28) → ADR-0002

V1 is milestones M00–M14 of the **re-ordered** `handoff/tasks.json` (v1.1). The following move to the optional milestone M15 ("v1.1+") and do not block v1:
- kind/Helm deployment and NetworkPolicy tests in a cluster (R066 cluster part);
- paused-version upgrade rehearsal (R069);
- SBOM and provenance attestation (R076);
- fencing of distributed LangGraph checkpoint writes (R021);
- Slack (R079) and cloud (R080).

Also reduced for v1:
- **Observability:** an OTel collector and one trace backend, with redaction tests. Grafana, Loki and Prometheus are optional.
- **UI:** three panels (Conversation+Activity, Evidence, Approvals) showing the eight states listed in AM-40.
- **Database roles:** `migrator`, `api`, `worker`, `mcp_exec` (functions only, AM-20) and `incident` (separate database). RLS is tested on the `api` role.
- **No tenant-administration surface.** Memberships are seeded and changed through migrations or a CLI test fixture.

Evaluation moves to right after the review/outcome milestone (new M09) [R#17].

**Demo claims:**
- The three demos in §28 still apply.
- The recovery demo uses `docker kill` of a worker container around destination commit, not a pod kill.
- "Tested Kubernetes" is **not** claimed in v1.

## AM-10 Run state machine (amends §8)

New state **`ESCALATED`**:
- It is terminal for the conversation slot: it frees "one active investigation per conversation".
- It is **not** a claim of success or failure. Reconciliation jobs keep running and may append `action.confirmed` or `action.failed` events later. The run then moves `ESCALATED → SUCCEEDED | FAILED`, the only exit from a terminal-looking state, and it is allowed only with destination evidence.

| From | Added / changed transition |
|---|---|
| RETRIEVING | → AWAITING_INPUT when retrieval shows that required context is missing or ambiguous [R#9] |
| DRAFTING | → AWAITING_INPUT when the validated draft is `kind=abstain` with a clarification question (bounded: at most 2 clarification rounds per run) |
| AWAITING_APPROVAL | → BLOCKED_REVIEW on proposal expiry, evaluated **lazily** inside any decision/grant transaction **and** by a scheduled `expire_proposals` job every 60 s [R#9] |
| APPROVED | → QUEUED only via an explicit revision **before any execution grant exists** for the run |
| EXECUTING / OUTCOME_UNKNOWN | → ESCALATED on `CONFLICT` (same action key, different hash) — immediate [R#2] |
| OUTCOME_UNKNOWN | → ESCALATED when the escalation deadline (AM-13) passes without authoritative evidence [R#3] |
| ESCALATED | → SUCCEEDED / FAILED only on verified destination evidence |
| REJECTED, CANCELLED, ANSWERED, INSUFFICIENT_EVIDENCE, SUCCEEDED, FAILED | Terminal (explicit) |

The transition table is implemented as data in `core/` and enforced by one function. Any transition not in the table is rejected and logged (R082).

**Clock rule:** every expiry, freshness, lease and deadline comparison uses PostgreSQL `now()` inside the deciding transaction. Application clocks are used only for display. Tests inject time through a database-side override function, not the Python clock [R#9].

## AM-11 Proposal identity and grants (amends §6, §7, §10, §13) [R#7, R#8]

- **One ID per revision.** `proposal_id` identifies exactly one immutable revision; `(run_id, revision)` is unique. `run.active_proposal_id` points to the current one.
- `POST /api/v1/proposals/{proposal_id}/decisions` carries `expected_payload_sha256`. `create_incident(proposal_id)` and `get_incident_receipt(proposal_id)` therefore address one exact revision.
- **One active grant per run:** a partial unique index on `execution_grant(run_id) WHERE state <> 'ABORTED_NO_COMMIT'`. Once any grant exists for a run, `POST /runs/{id}/revisions` returns 409. A different incident needs a new run.
- `action_id` is a random UUIDv4 created when the grant is inserted. It is unique and reused for every retry and reconciliation.

## AM-12 Run-level lease and fence (amends §6, §8) [R#4, R#6]

- **Leases belong to runs, not jobs.** A new table `run_lease(run_id PK, owner, lease_until, fence bigint)` holds them. Jobs are wake-ups only.
- A worker must acquire the run lease (`fence := fence + 1`) before touching a run, whatever the job type. Every application mutation for that run checks `run_lease.fence = :fence AND lease_until > now()` in the same transaction.
- The invocation handle (§9) binds to the **run** fence.
- The heartbeat runs as an independent asyncio task: renew every 10 s, lease 30 s.
- **When renewal fails, the worker:**
  - (a) cancels in-flight model and tool calls;
  - (b) revokes its invocation handles;
  - (c) exits the run without further writes.
- The model call is bounded at 60 s (§12), and the heartbeat keeps the lease alive while it runs. A DB-backed `model_permit` semaphore (size 1 by default) enforces the global model concurrency of §17. Permits carry a lease too, so they are reclaimed if a worker dies.
- **Checkpoints, v1 (ADR-0002):**
  - LangGraph checkpoints are written only while the worker holds the run lease, through the standard `PostgresSaver`.
  - A stale worker *could* append a checkpoint after losing its lease (the "head hijack" [R#5]). This is mitigated, not prevented: every node rereads authoritative application state first, and the checkpoint is never authority.
  - R021 (fenced checkpoint writes via a `BaseCheckpointSaver` subclass that checks the run fence inside each `put`/`put_writes` transaction) stays **open** and is deferred to M15.
  - Multi-replica workers may run in v1. The README must state this limitation.

## AM-13 Execution protocol and crash windows (amends §13, §14) [R#1]

New record `action_attempt(action_id, attempt_no, state, fence, created_at, sent_at, resolved_at, outcome)`, with states `INTENT → SENT → RESOLVED`.

| Crash window | Recovery rule |
|---|---|
| (a) grant committed, no attempt row | Recovery inserts attempt `INTENT` with the **same** action_id, then proceeds as (b). |
| (b) attempt `INTENT`, request maybe not sent | Look up by action_id. Found → RESOLVED. Not found and dispatch deadline not passed and run not cancelled → redispatch with the **same** action_id and bytes. Not found and (deadline passed or cancelled) → call destination `abort`. |
| (c) attempt `SENT`, response lost | OUTCOME_UNKNOWN; reconcile by action_id (bounded backoff 1, 2, 4, 8 s + jitter, then scheduled jobs). |
| (d) receipt received, not persisted | Replay of lookup returns the same receipt; persisting it is idempotent. |

**New destination endpoint** `POST /internal/actions/{action_id}/abort`. It atomically records an authoritative `ABORTED_NO_COMMIT` tombstone if no incident exists for the key, and otherwise returns the existing receipt. After a tombstone, any later `POST /internal/incidents` with that key returns the tombstone and never commits. This is the only way to reach `FAILED` without a destination-side rejection.

**Defaults** (configurable; tests use injected DB time):

| Setting | Default |
|---|---|
| Dispatch deadline | 5 minutes after grant |
| Escalation deadline | 30 minutes in OUTCOME_UNKNOWN |
| Request-dedup replay window | 24 hours |
| Receipt retention | until explicit local teardown |

**The destination recomputes `sha256` over the received canonical bytes.** It never trusts a hash supplied by the caller.

**The destination authenticates the MCP executor** with a dedicated Keycloak client (`incident-sim` audience). Worker and API tokens are rejected with 403.

## AM-14 Events and SSE (amends §15) [R#9, R#20]

- **Sequence numbers.** The per-run `sequence` comes from `runs.next_event_seq`, incremented under the run row lock in the same transaction as the event insert. That makes it gap-free and commit-ordered, so SSE `Last-Event-ID` replay cannot skip events (R089).
- **Event types:** the §15 list plus `clarification.received`, `proposal.revised`, `review.blocked`, `run.answered`, `run.insufficient_evidence`, `run.rejected`, `action.conflict`, `run.escalated`, `explanation.ready`.
- **Who may assert outcomes.**
  - Only `source=application` or `source=destination` may emit `action.*`, `run.*` or `review.*`.
  - `model_summary` may emit only `explanation.ready`, and never with a status field.
  - `action.confirmed` requires a receipt object, and its status must equal `SUCCEEDED`.
  - These rules are enforced in schema (`if/then`) and in code.

## AM-15 Tool contracts (amends §10) [R#21]

- **Every tool gets an input JSON Schema** in `schemas/tools/`. Arguments that supply a role, tenant, actor, approval or destination are rejected.
- **The envelope must agree with the data:**
  - `status=ok` only for `SUCCEEDED`, or for read results with data;
  - `UNKNOWN` / `CONFLICT` / `FAILED_NO_COMMIT` use `status=outcome` and a required `data.action_id`;
  - transport errors after a grant are reported by the *caller* as `UNKNOWN`, with the action_id it already holds.
- `get_recent_alerts` returns `next_cursor` when `truncated=true`.
- The caller verifies that a `SUCCEEDED` result's hash equals the proposal hash before recording success. A mismatch becomes `CONFLICT`.

## AM-20 Authority boundaries (amends §6, §9, §13) [R#10–R#16]

1. **No table grants for the MCP role.** `mcp_exec` gets **no table privileges**, only `EXECUTE` on two `SECURITY DEFINER` functions owned by a non-login role:
   - `resolve_invocation(handle_sha256)` returns the run, tenant, allowed tools, and the fence or expiry check;
   - `grant_execution(handle_sha256, proposal_id)` performs the §13 final-gate transaction and returns `(action_id, canonical_bytes, payload_sha256)`.

   Test: as `mcp_exec`, `SELECT * FROM proposals` gives `permission denied` (R084).
2. **The tool allowlist is derived on the server**, by `resolve_invocation`, from `job.type` (set by the API or sweeper) plus the run state. For example, `create_incident` is allowed only when `job.type='execute'` and state is `APPROVED`. The worker does not choose the allowlist (R085).
3. **A proposal must belong to the handle's run.** `grant_execution` requires `proposal.run_id = handle.run_id` and the same tenant. Cross-run or cross-tenant IDs fail with zero rows written.
4. **Independence covers every content author.** The proposal records `authored_by`: the requester and every human who submitted a revision or manual proposal. The reviewer must not be in that set (R093).
5. **Session revocation.** Keycloak back-channel logout is enabled. The API also re-validates the user's IdP status at least every 5 minutes on mutating requests. Disabling a user in Keycloak means their next mutation gets 401 (R086).
6. **Keycloak audience mappers** add `ops-mcp` and `incident-sim` audiences. Tokens with no `aud` are rejected.
7. **Checkpoint tables** live in a `checkpoints` schema granted only to `worker`. Test: `api` gets permission denied.
8. **Interrupt payloads and graph state carry IDs and hashes only.** Never evidence text or proposal bodies (R091).
9. **Fault-injection hooks** exist only in an app factory that refuses to start unless `PROFILE=test`. They are absent in the default profile (R098).

## AM-30 MCP and library facts (amends §2, §10, §19, §22, §29) [R#25–R#30]

- **Protocol and SDK pins:**
  - MCP protocol revision **2026-07-28** (session-less; the protocol version travels per request in `_meta`). The server may also accept 2025-11-25 clients only if a test covers it.
  - Python SDK `mcp>=2.3,<3`, exact version locked in `uv.lock`.
  - Replace "negotiation" in §10 and §19 with: per-request protocol-version validation, mismatch rejection, and list/call over Streamable HTTP from an independent process.
- **SDK imports:** `from mcp.server.mcpserver import MCPServer, Context` and `from mcp import Client`. `integrations/mcp_tools.py` is historical and is not imported by target code.
- **Dependencies.** Declare `langchain-core`, `langchain-ollama`, `langgraph`, `langgraph-checkpoint-postgres`, `psycopg[binary,pool]`, `sqlalchemy`, `alembic`, `pgvector`, `authlib`, `jsonschema` (dev) in the owning member's `pyproject.toml`. Commit `uv.lock`.
- **kind (M15):** use kind's default CNI, which enforces NetworkPolicy via kube-network-policies since kind v0.24. Do not install Cilium.
- **Citation fixes:**
  - "Not external exactly-once" is project reasoning supported by S02's idempotency warning, not by S01.
  - "Temperature 0 does not guarantee identical outputs" is project reasoning.
  - The S05 note: no redirect was observed.

## AM-31 Model runtime profile (amends §12, §17) [R#29]

- **Model:** `qwen3:8b` (installed). Record its digest from `ollama show`.
- **Thinking off.** Request it via ChatOllama's reasoning control (`reasoning=False`, or Ollama `think:false` on the locked version). Verify that responses contain no thinking content. If thinking cannot be disabled, fail the probe; do not silently strip it.
- **Explicit `num_ctx`:** 16384, which must be at least the §17 input budget plus output. Output cap `num_predict` 1000.
- **M00 probe report** (`reports/model-probe-qwen3-8b.md`), from at least 30 schema-constrained calls on the development fixtures. It records:
  - the JSON-valid rate;
  - the schema-valid rate;
  - p50/p95 latency;
  - peak VRAM (`nvidia-smi`);
  - the model digest;
  - exact parameters.

  If the schema-valid rate is below 90%, raise it as an owner decision before M07 (R081).

## AM-40 UI states for v1 (amends §16)

The eight states are:
1. loading/queued
2. collecting context (clarification)
3. retrieving/drafting
4. awaiting independent review (including stale/expired disabled)
5. executing / outcome unknown
6. succeeded
7. failed / rejected / insufficient evidence / escalated, each with its reason
8. session expired / disconnected-then-reconnected snapshot

The other §16 states are covered by these eight or deferred.

## AM-50 Evidence corpus and evaluation (amends §11, §20, §27) [§3 of review]

- **Corpus:**
  - at least 12 authored documents of 300–900 words each, plus at least 6 assets across 2 tenants;
  - including superseded/expired versions, one injected-instruction document per tenant, and one conflicting-procedure pair;
  - evidence IDs are per section, with a per-section `sha256`;
  - fixtures map tenant slugs to seeded UUIDs, and alert IDs are UUIDs with revisions.
- **Two separate suites:**
  1. **Scenario suite** (deterministic, fake model): the 32 cards become executable pytest scenarios. Each oracle is an assertion on final application *and* destination state. Runs in CI on every PR (R097).
  2. **Model-quality evaluation** (real qwen3:8b), with conditions A manual / B RAG-only / C orchestrated:
     - about 60 development cases;
     - about 25 **owner-authored** holdout cases, written by the owner without AI assistance, stored outside the repo, with the `sha256` of the file committed before any run;
     - 3 isolated trials per case;
     - metrics: schema-valid rate, citation validity, abstention accuracy, owner-labelled groundedness;
     - every rate reported with a **Wilson 95% CI** and its denominator;
     - `evals/quality-gates.json` committed (with date) **before** the first holdout run;
     - the holdout is run once per release candidate.
- **Solo-owner rule:** §27's "independent holdout reviewer" is satisfied by owner authorship plus hash-locking. The README states this limitation.
- **Chunking:** sections are the unit. The 300–600-token chunk rule applies only to sections longer than 600 tokens.

## AM-60 Task graph (amends §25, `handoff/tasks.json`) [R#17–R#19]

- `handoff/tasks.json` v1.1 replaces the serial chain with a dependency graph. Each requirement sits in the milestone where it first becomes testable.
- Each task has its own `definition_of_done`.
- `external_approval_required` is `true` where §26/§27 require the owner:
  - holdout authorship;
  - CI secrets and pushes;
  - publication;
  - any model download.
- `handoff/BUILD_BACKLOG.md` is regenerated from it.

## AM-70 Reference code defects (do not port) [R#14, R#31–R#34]

The reference stays as historical behaviour evidence. Do **not** port these behaviours:
- deterministic `action_key` (`service.py:176`);
- network or tool I/O inside the write transaction (`service.py:172`);
- catching only `UncertainOutcome` (`service.py:182`);
- stuck EXECUTING after a crash (`service.py:175-178`, `:213-216`);
- full proposal text in `interrupt()` (`integrations/langgraph_workflow.py:38`);
- plaintext token file next to hashed tokens (`scripts/init_demo.py:18-23`);
- `internal: true` network with a published port (`compose.yaml`).

Weak reference tests are replaced by stronger target tests:
- `test_duplicate_decision_and_execute` cannot fail on a dedup bug;
- no concurrent `decide`/`execute` test exists.

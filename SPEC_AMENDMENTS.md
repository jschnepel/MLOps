# OPS-BUILD-1.2 — Amendments to BUILD_SPEC.md

**Status:** Approved by the owner on 2026-10-06. 1.1 ("amend + cut") was revised to 1.2 after the second adversarial review.
**Precedence:** This file overrides `BUILD_SPEC.md` (OPS-BUILD-1.0) wherever they conflict. Everything not amended here stays in force. ADRs in `docs/adr/` record the reasoning.

**Sources:**
- `docs/reviews/handoff-review-2026-10-06.md` (round 1, cited `[R1#n]`)
- `docs/reviews/plan-review-2026-10-06.md` (round 2, cited `[R2#n]`)

New acceptance requirements are R081–R117 in `handoff/acceptance-matrix.json`.

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
| `mcp-server/` | Authenticated MCP server: read tools, guarded write and recovery tools |
| `asset-sim/` | Synthetic asset/alert API (deterministic, injected clock) |
| `incident-sim/` | Synthetic incident destination with its own database |
| `web/` | React + TypeScript + Vite workspace |
| `core/` | Shared library (uv workspace member). **Not** a service. |

The original `src/operations_copilot/` reference stays until T07 re-expresses its 58 behaviours as `core/` tests. T07 then moves it, unchanged, to `reference/`.

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
- **Database roles:** `migrator`, `api`, `worker`, `mcp_exec` (functions only), `app_definer` (NOLOGIN, owns functions, does not own tables), and `incident` (separate database).
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

| From | Added / changed transition |
|---|---|
| RETRIEVING | → AWAITING_INPUT when required context is missing or ambiguous |
| DRAFTING | → AWAITING_INPUT on `kind=abstain` with a question, at most 2 clarification rounds; on a third round → INSUFFICIENT_EVIDENCE |
| AWAITING_APPROVAL | → BLOCKED_REVIEW on expiry: evaluated lazily inside any decision or grant transaction, plus by the scheduled `expire_proposals` job (60 s) |
| BLOCKED_REVIEW | Frees the conversation slot. → QUEUED on revision; → CANCELLED |
| APPROVED | → QUEUED only via revision **before the grant exists** |
| EXECUTING / OUTCOME_UNKNOWN | → ESCALATED on CONFLICT, or when the escalation deadline passes (AM-13) |
| ESCALATED | → SUCCEEDED / FAILED only on verified destination evidence |
| REJECTED, CANCELLED, ANSWERED, INSUFFICIENT_EVIDENCE, SUCCEEDED, FAILED | Terminal |

- **Enforcement:** the transition table is data in `core/`, and a single function enforces it (R082).
- **The ANSWERED path** (read-only answer, no proposal) has its own test (R114).

**Clock rule:**
- Every lease, expiry, freshness and deadline comparison uses `clock_timestamp()`, evaluated **after** the relevant row locks are acquired. Never use `now()`, which is the transaction start time.
- Tests inject time through the database function `app.current_time()`. It wraps `clock_timestamp()` plus a test-only offset.

## AM-11 Proposal identity and grants (amends §6, §7, §10, §13)

- **One ID per revision.** `proposal_id` identifies exactly one immutable revision; `(run_id, revision)` is unique. Decisions carry `expected_payload_sha256` (T07 renames the schema field).
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

**Lock order:** `run_lease → runs → proposals → execution_grant → action_attempt → events → outbox`. Every transaction and definer function follows it. A two-connection interleaving test and a concurrent stress test prove fencing and deadlock freedom (R107).

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

**Checkpoints (ADR-0002):**
- Invoke graphs with `durability="sync"`. The LangGraph default `"async"` persists while the next step runs.
- After each superstep, the worker stores the accepted `checkpoint_id` in `runs.checkpoint_id` under the fence. It always resumes with that explicit `checkpoint_id`, and any newer head is ignored (R108).
- Nodes re-execute from the start on resume, so every node before an `interrupt()` is idempotent and side-effect free.
- **V1 runs one worker replica.** Fencing still protects application writes, and the stored checkpoint ID protects the head.
- R021 (fencing `put`/`put_writes` themselves, enabling multi-replica) stays open in M15.

## AM-13 Execution ownership, attempt protocol and destination (amends §13, §14)

**Who does what:**
- The worker never contacts the destination.
- The MCP server is the only caller of incident-sim. It records every step through fenced `SECURITY DEFINER` functions (AM-20).
- The worker drives the process by calling MCP tools under an `execute` or `recover` job.

**Attempt protocol** (`action_attempt(action_id, attempt_no, state, …)`):
1. `grant_execution` performs the §13 final gate. It inserts the grant **and** attempt 1 in state `INTENT` in one transaction, then returns `(action_id, canonical_bytes, sha256)`.
2. `mark_sent(action_id)` commits `INTENT → SENT` **before** network I/O. So `INTENT` means the request was definitely not sent.
3. The MCP server POSTs to incident-sim.
4. `record_outcome(action_id, outcome)` commits `RESOLVED` with the verified receipt, tombstone or rejection. It also updates the run state and appends the event.

**Recovery** (`recover` job; tools allowed by AM-20.2):

| Attempt state | Rule |
|---|---|
| INTENT, before dispatch deadline, not cancelled | Redispatch with the same `action_id` and bytes (`create_incident` is idempotent per grant). |
| INTENT, after deadline or cancelled | `abort_incident`. |
| SENT, no response | OUTCOME_UNKNOWN. `get_incident_receipt` with backoff 1, 2, 4, 8 s + jitter, then scheduled jobs. When the dispatch deadline passes, call `abort_incident`: the destination returns either the existing receipt (→ SUCCEEDED) or a fresh tombstone (→ FAILED, `reason=aborted_no_commit`). |
| Destination unreachable | Keep retrying lookup or abort. When the escalation deadline passes, → ESCALATED (applies to INTENT and SENT). |
| Receipt received but not persisted | Lookup replays the same receipt; `record_outcome` is idempotent. |

**Cancellation:**
- In INTENT, cancellation leads to abort, a guaranteed no-commit.
- After SENT, cancellation also requests abort. The truthful outcome is whatever the destination returns: an existing receipt is reported as SUCCEEDED with a "cancellation arrived after dispatch" note. Nothing is ever claimed as undone.

**Worker transport timeout during `create_incident`** [R2#10]:
1. Take the run lease row lock (`FOR UPDATE`).
2. Bump the fence, which revokes the handles.
3. Read `execution_grant` by `run_id`.
4. If a grant exists, the run becomes OUTCOME_UNKNOWN with that `action_id` and enters recovery. If not, no grant can commit any more, because the fence changed.

Tested by R109.

**Destination (incident-sim):**
- A single table `action_key(action_id PK, payload_sha256, state ∈ {COMMITTED, ABORTED}, incident_id NULL, decided_at)`.
- Both `POST /internal/incidents` and `POST /internal/actions/{id}/abort` use `INSERT … ON CONFLICT (action_id) DO NOTHING` and then read the row. The first writer wins atomically.
- An incident row is inserted in the same transaction only when the key commits.
- **Rows are never deleted or expired**, not even tombstones.
- The destination recomputes `sha256` over the received bytes. A different hash under an existing key → CONFLICT.
- It accepts only the `incident-sim` audience workload token.

**Outcome vocabulary:**

| Layer | Values |
|---|---|
| Destination | `COMMITTED` / `ABORTED` |
| Tool outcome | `SUCCEEDED` / `FAILED_NO_COMMIT` / `UNKNOWN` / `CONFLICT` |
| Run | SUCCEEDED / FAILED / OUTCOME_UNKNOWN / ESCALATED |

`FAILED_NO_COMMIT` carries `reason ∈ {aborted_no_commit, rejected}`.

**Asset guard:** proposal freezing and grants refuse while another run in the same tenant has an unresolved action (EXECUTING, OUTCOME_UNKNOWN or ESCALATED) for the same asset and an overlapping interval (R110).

**Defaults** (configurable; tests use `app.current_time()`):

| Setting | Default |
|---|---|
| Dispatch deadline | 5 minutes after grant |
| Escalation deadline | 30 minutes after grant |
| Request-dedup replay window | 24 hours |
| Destination keys and receipts | Never expire |

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

| Tool | Callable by |
|---|---|
| `get_asset_status`, `get_recent_alerts` (absolute interval, `next_cursor`), `search_procedures` | read jobs |
| `create_incident(proposal_id)` | `execute` jobs; `recover` jobs for same-key redispatch |
| `get_incident_receipt(proposal_id)` | `recover` jobs only |
| `abort_incident(proposal_id)` | `recover` jobs only |

- Every tool has an input JSON Schema in `schemas/tools/`. Arguments that supply a role, tenant, actor, approval or destination are rejected.
- **The envelope must agree with the data:**
  - `status=ok` only for a read with data, or `SUCCEEDED`;
  - `status=outcome` for `UNKNOWN` / `CONFLICT` / `FAILED_NO_COMMIT`, with `data.action_id` required;
  - `status=error` only before any grant exists.
- The caller verifies that a `SUCCEEDED` receipt's hash equals the proposal hash. A mismatch becomes `CONFLICT`.

## AM-20 Authority boundaries (amends §6, §9, §13)

1. **Definer functions are the MCP role's only access.**
   - `mcp_exec` has no table privileges. It has `EXECUTE` only on `resolve_invocation(handle_sha256, client_azp)`, `grant_execution`, `mark_sent`, `record_outcome`, `lookup_action`, `request_abort`.
   - All are `SECURITY DEFINER`, owned by `app_definer` (NOLOGIN, **not** a table owner), with `SET search_path = app, pg_temp`.
   - Each migration creates the function, runs `REVOKE ALL ON FUNCTION … FROM PUBLIC` and `GRANT EXECUTE … TO mcp_exec` in the same transaction.
   - Application tables use `FORCE ROW LEVEL SECURITY`. Functions set `app.tenant_id` (transaction-local) from the resolved run before touching tenant rows.
   - Tests:
     - `mcp_exec` cannot `SELECT` any table (R084);
     - the definer path cannot read another tenant's rows (R106).
2. **The allowlist is derived on the server.** `resolve_invocation` derives allowed tools from `job.type` (set by the API or sweeper) and the run state, per the AM-15 table. It also checks that the handle's workload client equals the token's `azp` (R085).
3. **Proposals are bound to runs.** Every write or recovery function requires `proposal.run_id = handle.run_id` and the same tenant (R100).
4. **Independence covers every content author.** The proposal records `authored_by` (requester plus revision and manual-proposal authors), and the reviewer must not be in it (R093).
5. **Revocation** (replaces the 1.1 wording):
   - (a) Back-channel logout: the API hosts a hand-written OIDC Back-Channel Logout endpoint (validates iss, aud, iat, jti, events; no nonce; jti replay cache) that destroys sessions.
   - (b) **Every** decision, revision, cancel and manual-proposal mutation checks the user's enabled status through the Keycloak admin API. It uses a local-only service account limited to `view-users`, and its secret is generated by the bootstrap.
   - (c) A membership sync job (every 60 s) deactivates memberships of disabled users, and `grant_execution` reads membership.
   - Bounds:
     - a disabled user's next decision-class mutation gets 401;
     - a disabled requester or reviewer blocks grants within ≤60 s;
     - session-only reads end on back-channel logout or idle expiry.

   Tested by R086.
6. **MCP token verification.**
   - Keycloak "Hardcoded audience" mappers set `aud` to the **resource URL** of mcp-server (for example `http://mcp-server:8080/mcp`) and to `incident-sim`.
   - mcp-server uses a custom `TokenVerifier` that checks iss, aud ∋ resource URL, azp ∈ allowed workload clients, and exp.
   - Tests cover a missing `aud`, a wrong `aud`, and a browser token.
7. **Checkpoint tables.**
   - `migrator` runs `PostgresSaver.setup()` with `autocommit=True`, `row_factory=dict_row` and `options=-c search_path=checkpoints` (the saver has no schema parameter).
   - `worker` gets DML only on schema `checkpoints`, with `search_path=checkpoints,pg_temp` on its checkpoint connection.
   - `api` gets permission denied.
8. **Graph state is IDs only.** Interrupt payloads and graph state carry IDs and hashes only (R091).
9. **Fault hooks are test-only.** They exist only in an app factory that refuses to start unless `PROFILE=test` (R098; built in T13).
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

- **Model:** `qwen3:8b`. Record its digest.
- **Settings:** `ChatOllama(reasoning=False)` (maps to Ollama `think:false`), `num_ctx=16384`, `num_predict=1000`, `temperature=0`, 60 s timeout, `with_structured_output(method="json_schema")` **plus** application-side validation.
- **T02 probe**, at least 30 calls on development inputs. It records:
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
7. failed / rejected / insufficient evidence / escalated, with its reason
8. session expired / disconnected-then-reconnected snapshot

Each state has a Playwright assertion (R117).

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
| Holdout set | About 25 **owner-authored** cases, written **now** (T03) before any prompt tuning, without AI assistance |
| Holdout custody | Stored **off this machine** (or encrypted with a key the agent never sees) until a release-candidate run. Only its `sha256` and case count are committed. Every holdout run is logged. |
| Conditions | A: manual baseline (human-authored proposal via `/manual-proposals`). B: RAG-only single call. C: orchestrated. B and C use identical model, prompt-version family, retrieval settings and `num_ctx`. Schema metrics apply to B and C only. |
| Trials | 3 isolated trials per case for B and C |

**Statistics:**
- Report rates at **case level** (a case passes if at least 2 of 3 trials pass) with Wilson 95% CIs and denominators, plus trial-level rates with a case-cluster bootstrap CI.
- Compare conditions with paired McNemar tests on case-level outcomes.
- Make no ranking claim without p < 0.05. At n≈25, differences under about 15–20 points are expected to be undetectable, and the README says so.
- Unauthorized writes must be 0 observed. Report the rule-of-three upper bound (≈3/n).

**`evals/quality-gates.json`** lists entries of the form `{metric, condition, threshold, applies_to: "point"|"wilson_lower_95", blocking}`:
- The owner fills it in and commits it **before** the first holdout run.
- Safety gates (unauthorized writes, fabricated success, cross-tenant leakage) are blocking at 0 observed.
- Quality gates are owner-chosen.

**Labelling load estimate:** about 85 cases × 3 trials × 2 model conditions ≈ 510 outputs, plus 85 manual baselines. Use deterministic graders wherever possible (citations, schema, abstention); owner labels only groundedness.

**Solo-owner limitation:** §27's independent reviewer is replaced by owner authorship, off-machine custody and hash-locking. The README states this.

## AM-60 Task graph (amends §25, `handoff/tasks.json`)

`handoff/tasks.json` 1.2 has 40 tasks, renumbered.

**New tasks:**
- T03 owner holdout authoring;
- T05 dev bootstrap (Compose dev profile, Keycloak realm and workload clients, secret generation, seed UUIDs);
- T06 early secret-free CI;
- T08 **walking skeleton**: fake model, real Postgres, real HTTP across api → worker → mcp-server → incident-sim, before hardening;
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

## AM-80 Schema, example and fixture alignment (owned by T07)

The delivered `schemas/`, `schemas/examples/` and `data/handoff-fixtures/` still describe 1.0. T07 updates them and proves the result with `scripts/verify_handoff.py --contracts` plus new negative probes (R104).

| Artifact | Required change |
|---|---|
| `event.schema.json` | Add `ESCALATED` and the AM-14 event types; `action.confirmed` requires a receipt and SUCCEEDED; source rules |
| `tool-result.schema.json` | `status=outcome`; envelope/data agreement; `action_id` required on outcomes; `next_cursor`; `abort_incident` |
| `schemas/tools/*.json` | Create input schemas for all six tools |
| `action-outcome.schema.json` | `FAILED_NO_COMMIT.reason`; mapping from `ABORTED` |
| `decision.schema.json` + examples | `expected_payload_sha256` |
| `examples/tool-get_incident_receipt-valid.json` | Uses `status=outcome` |
| `examples/draft-valid.json` / `tool-get_recent_alerts-valid.json` | Make the alerts consistent (the draft says "two warnings", the alerts example returns `[]`) |
| `examples/index.json` | Version 1.2; a stated reason for each negative example |
| `data/handoff-fixtures/` | Tenant UUID mapping; alert UUIDs + revisions; per-section hashes (expanded in T17) |
| `proposal.schema.json` | `start_at < end_at` and UTC-only offsets (enforced in code where JSON Schema cannot); `authored_by` |

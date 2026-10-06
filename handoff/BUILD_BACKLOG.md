# Ordered AI implementation backlog (OPS-BUILD-1.1)

Generated from `handoff/tasks.json`. Read BUILD_SPEC.md, then SPEC_AMENDMENTS.md (which takes precedence). Tasks are planned; nothing here is marked complete.

## M00 — Baseline, environment and model probe

- [ ] **T01 Reproduce reference baseline on this machine** — In an isolated uv environment with the reference's web+test extras, run the 58-test suite and the recovery CLI on Windows. Record versions, results and any failures in reports/baseline/. Do not modify reference code. Requirements: R001, R002. Dependencies: none.
- [ ] **T02 Inventory environment and probe qwen3:8b** — Record hardware, Docker, Ollama and installed models. Run the AM-31 probe: >=30 schema-constrained calls with thinking disabled and explicit num_ctx; record JSON/schema validity, latency p50/p95, peak VRAM and model digest. Requirements: R081. Dependencies: T01.

## M01 — Workspace, contracts and toolchain

- [ ] **T03 Create uv workspace with per-service directories and locks** — Implement ADR-0001 layout (core/, api/, worker/, mcp-server/, asset-sim/, incident-sim/). Resolve versions from official sources, commit uv.lock, add ruff, mypy and pytest wiring and a single `make check` / script entry point. Requirements: R003. Dependencies: T02.
- [ ] **T04 Implement contracts, canonical bytes and state machine in core** — Pydantic contracts from schemas with AM-14/AM-15 fixes and tool input schemas; canonical JSON v1; transition table incl. ESCALATED as data with one enforcing function; port the 58 reference behaviours as core tests. Requirements: R004, R005, R082, R083. Dependencies: T03.

## M02 — PostgreSQL foundations and independent destination

- [ ] **T05 PostgreSQL migrations, roles, RLS and security-definer functions** — Alembic migrations for tenants, memberships, conversations, messages, runs (incl. next_event_seq), run_lease, jobs, events, outbox, proposals, decisions, execution_grant, action_attempt, idempotency. Roles migrator/api/worker/mcp_exec; RLS on api; checkpoints schema; resolve_invocation and grant_execution as SECURITY DEFINER. Requirements: R006, R007, R008, R009, R084. Dependencies: T04.
- [ ] **T06 Independent incident-sim destination with atomic receipts and abort** — Separate service + database: POST /internal/incidents (atomic incident+receipt, recomputed hash), GET /internal/actions/{id}, POST /internal/actions/{id}/abort tombstone; executor-audience auth; test-only fault hooks. Requirements: R010, R047, R049, R096. Dependencies: T04.

## M03 — Identity and durable admission API

- [ ] **T07 Keycloak OIDC with backend sessions and current membership** — Local Keycloak realm (5 personas, workload clients with audience mappers); authlib code+PKCE flow; opaque HttpOnly session, CSRF, origin checks; back-channel logout and periodic IdP status check; membership read from app tables. Requirements: R011, R012, R013, R014, R086. Dependencies: T05.
- [ ] **T08 Versioned durable admission API** — /api/v1 conversations, messages, runs; admission commits message+run+job+event in one transaction before 202; scoped Idempotency-Key (24 h window); one active run per conversation; relative interval resolved once with DB now(). Requirements: R015, R016, R017, R018. Dependencies: T07.

## M04 — Run leases, event journal and outbox

- [ ] **T09 Run-level lease, fence and independent heartbeat** — run_lease acquisition with fence increment; all run mutations fence-checked; heartbeat as independent task; on lease loss cancel model/tool calls and revoke handles; model_permit semaphore; sweeper reclaims expired leases. Requirements: R019, R020, R022, R087, R088. Dependencies: T08.
- [ ] **T10 Gap-free event journal, wake-ups and outbox** — Per-run sequence from runs.next_event_seq under row lock; decision/reply wake-up jobs committed atomically; sweeper re-enqueues lost wake-ups; transactional outbox with leased delivery loop (no external channel). Requirements: R023, R024, R089. Dependencies: T09.

## M05 — Authenticated MCP boundary

- [ ] **T11 Authenticated MCP server/client and invocation handles** — mcp-server on official SDK 2.x over Streamable HTTP pinned to protocol 2026-07-28; workload token audience ops-mcp; X-Ops-Invocation handle bound to run fence; allowlist derived server-side via resolve_invocation; independent-process client tests. Requirements: R025, R026, R027, R031, R085. Dependencies: T09, T07.
- [ ] **T12 Read tools, asset-sim and reconciliation-only receipt lookup** — asset-sim service; get_asset_status, get_recent_alerts (absolute interval, next_cursor), search_procedures stub over governed store; get_incident_receipt for reconciliation workload only; fail-closed result validation. Requirements: R028, R029, R030. Dependencies: T11, T06.

## M06 — Evidence corpus and retrieval

- [ ] **T13 Expanded corpus, governed ingestion and lexical baseline** — Author >=12 documents (300-900 words), >=6 assets, 2 tenants, incl. superseded, conflicting and injected-instruction sources; per-section IDs and hashes; idempotent ingestion; PostgreSQL full-text retrieval with access filtering. Requirements: R032, R033, R099. Dependencies: T12.
- [ ] **T14 Exact pgvector retrieval and comparison** — nomic-embed-text embeddings (record model, dimension, digest); exact search with the same access filters; comparison report against lexical on the same dev queries. Requirements: R034. Dependencies: T13.

## M07 — LangChain draft node and LangGraph workflow

- [ ] **T15 LangChain ChatOllama DraftGenerator** — Versioned prompts; ChatOllama with thinking disabled, num_ctx 16384, num_predict 1000, 60 s timeout; structural validation incl. citation membership; one bounded repair; explicit MODEL_MODE fake|ollama with no fallback. Requirements: R036, R037, R039, R040, R041. Dependencies: T02, T13.
- [ ] **T16 Explicit LangGraph workflow with durable pauses** — Nodes per BUILD_SPEC section 8 with retrieval before drafting; deterministic edges; clarification and approval interrupts carrying IDs/hashes only; nodes reread authoritative state; checkpoints in checkpoints schema. Requirements: R035, R038, R042, R091. Dependencies: T15, T10, T12.

## M08 — Independent review, grant and outcome recovery

- [ ] **T17 Immutable proposals, independent decisions and final grant** — Per-revision proposal IDs; decision endpoint with expected hash; first decision wins; author-set independence; lazy+scheduled expiry to BLOCKED_REVIEW; grant_execution final gate with one active grant per run and proposal/run binding. Requirements: R043, R044, R045, R046, R090, R092, R093, R100. Dependencies: T16.
- [ ] **T18 Execution, crash-window recovery and escalation** — action_attempt INTENT/SENT/RESOLVED; recovery for windows a-d; same-key redispatch or abort per AM-13; bounded reconciliation backoff; CONFLICT and expired unknown -> ESCALATED; receipt retention. Requirements: R048, R050, R051, R094, R095. Dependencies: T17, T12, T06.

## M09 — Scenario suite and model-quality evaluation

- [ ] **T19 Executable deterministic scenario suite** — Convert the 32 development scenario cards into pytest scenarios with oracles asserting final application and destination state; run on every PR. Requirements: R097. Dependencies: T18.
- [ ] **T20 Model-quality evaluation with owner-authored holdout** **[owner approval]** — ~60 dev cases; ~25 owner-authored holdout cases kept outside the repo with committed sha256; quality-gates.json committed before first holdout run; 3 isolated trials; conditions manual/RAG/orchestrated; Wilson 95% CIs. Requirements: R070, R071, R072, R073, R074. Dependencies: T18, T14.

## M10 — Web workspace

- [ ] **T21 React workspace: conversation, evidence and approvals** — Vite + React + TS; three panels; the eight AM-40 states; escaped/approved markdown; authorized evidence viewer; approval card bound to revision/hash; manual proposal path. Requirements: R052, R055, R056, R057. Dependencies: T18.
- [ ] **T22 Authenticated SSE replay and revocation** — Last-Event-ID replay from gap-free sequences; heartbeat; cursor reset snapshot; access recheck on every frame; identity change closes stream. Requirements: R053, R054. Dependencies: T21, T10.

## M11 — Observability and operating budgets

- [ ] **T23 OpenTelemetry tracing with redaction** — OTel SDK in api/worker/mcp-server; collector + one trace backend; bounded metric labels; redaction tests for tokens, handles and evidence text. Requirements: R058, R059, R060. Dependencies: T18.
- [ ] **T24 Budgets and degraded operation** — Queue/model/time/retry caps from BUILD_SPEC section 17; dependency outage behaviour with templated messages; capacity measurement on the owner's hardware. Requirements: R061, R062. Dependencies: T23.

## M12 — Containers, network isolation and CI

- [ ] **T25 Hardened images, Compose profiles and network isolation** — Multi-stage non-root images from uv.lock; compose profiles (test, demo); docker networks enforce model-to-destination and browser-to-internal denial; test-only fault factory; docker-kill worker recovery demo. Requirements: R063, R064, R065, R066, R067, R098. Dependencies: T18.
- [ ] **T26 GitHub Actions CI with trust separation** **[owner approval]** — PR workflow: ruff, mypy, unit, PostgreSQL integration, scenario suite, image build+scan; pinned action SHAs; least-privilege tokens; no secrets on PRs. Requirements: R075. Dependencies: T25.

## M13 — Retained-receipt restore

- [ ] **T27 Retained-receipt restore demonstration** — Restore an older app backup against the retained destination; reconcile by original action IDs; runbook with exact commands and observations. Requirements: R068. Dependencies: T25.

## M14 — Portfolio release

- [ ] **T28 Clean-machine reproduction and three recorded demos** — From a clean clone: setup, success demo, denial demo, recovery demo; deterministic mode shown separately. Requirements: R077. Dependencies: T19, T20, T22, T24, T26, T27.
- [ ] **T29 Release notes, MIT license and publication** **[owner approval]** — README rewrite for interviewers, ADR index, limitations (single-writer checkpoints, solo holdout), MIT LICENSE, push to github.com/jschnepel/MLOps. Requirements: R078. Dependencies: T28.

## M15 — Optional v1.1+ extensions (non-blocking) *(optional, non-blocking)*

- [ ] **T30 kind/Helm deployment with default CNI policy tests** — Helm chart and kind cluster using kind's default CNI with kube-network-policies; pod-level allow/deny and pod-kill tests. Requirements: R066. Dependencies: T25.
- [ ] **T31 Paused-version upgrade and rollback rehearsal** — Route paused v1 runs to compatible code across a workflow_version bump; rollback test. Requirements: R069. Dependencies: T27.
- [ ] **T32 SBOM and release provenance** — Generate SBOM and provenance attestations for released images; link to tested inputs. Requirements: R076. Dependencies: T26.
- [ ] **T33 Fenced distributed checkpoint writes** — BaseCheckpointSaver subclass that checks run fence inside each put/put_writes transaction; stale-worker head-hijack test. Requirements: R021. Dependencies: T16.
- [ ] **T34 Opt-in Slack adapter** **[owner approval]** — Verified callbacks, identity mapping, outbox delivery, same review/execute policy. Requirements: R079. Dependencies: T29.
- [ ] **T35 Approved budgeted cloud deployment** **[owner approval]** — Terraform/EKS only after owner cost and teardown approval. Requirements: R080. Dependencies: T34.

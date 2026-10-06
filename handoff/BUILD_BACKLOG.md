# Ordered AI implementation backlog (OPS-BUILD-1.2)

Generated from `handoff/tasks.json`. Read BUILD_SPEC.md, then SPEC_AMENDMENTS.md (which takes precedence). Nothing here is complete.

## M00 — Baseline, environment, model probe and sealed holdout

- [ ] **T01 Reproduce reference baseline on this machine** — Isolated uv venv with the reference web+test extras; run the 58 tests and the recovery CLI on Windows; save outputs under reports/baseline/. Do not modify reference code. Requirements: R001, R002. Depends on: none.
- [ ] **T02 Environment inventory and qwen3:8b probe** — Per AM-31: >=30 structured calls (reasoning=False, num_ctx=16384); first-pass and post-repair validity with Wilson CIs; latency; VRAM; thinking leakage; mid-generation cancellation behaviour via `ollama ps`/GPU. Requirements: R081. Depends on: T01.
- [ ] **T03 Owner authors and seals the holdout set** **[owner approval]** — Owner writes ~25 holdout cases without AI assistance, stores them off-machine or encrypted, commits only sha256 and count, and drafts quality-gates.json structure (AM-50). Requirements: R071. Depends on: none.

## M01 — Workspace, bootstrap, contracts and walking skeleton

- [ ] **T04 uv workspace with per-service directories and locks** — ADR-0001 layout (core/, api/, worker/, mcp-server/, asset-sim/, incident-sim/); resolve versions per AM-30; commit uv.lock; ruff, mypy, pytest via one command. Requirements: R003. Depends on: T02.
- [ ] **T05 Dev bootstrap: Compose dev profile, Keycloak realm, secrets, seed IDs** — Compose dev profile with PostgreSQL+pgvector and Keycloak 26.8.x (pinned digest); realm export with 5 personas, workload clients and hardcoded-audience mappers (mcp-server resource URL, incident-sim); view-users service account; Windows-friendly secret generation outside git; seeded tenant/persona UUIDs; host Ollama bridge. Requirements: R101, R102. Depends on: T04.
- [ ] **T06 Early secret-free CI** **[owner approval]** — GitHub Actions workflow for ruff, mypy and unit tests with pinned action SHAs and read-only token; requires the public repo to exist. Requirements: R103. Depends on: T04.
- [ ] **T07 Contracts, state machine, schema alignment and reference migration** — Pydantic contracts; canonical JSON v1; transition table incl. ESCALATED; apply every AM-80 schema/example/fixture change; port the 58 reference behaviours as core tests; move src/operations_copilot to reference/ unchanged. Requirements: R004, R005, R082, R083, R104. Depends on: T04.
- [ ] **T08 Walking skeleton across all services** — Fake model; real PostgreSQL and real HTTP: POST run -> job -> worker -> mcp-server (minimal auth) -> incident-sim -> receipt -> event. No hardening; proves wiring before depth. Requirements: R105. Depends on: T05, T07.

## M02 — PostgreSQL authority model and independent destination

- [ ] **T09 Migrations, roles, RLS and hardened definer functions** — Alembic schema (incl. run_lease, runs.next_event_seq, runs.checkpoint_id, execution_grant.run_id UNIQUE, action_attempt, sessions); roles per AM-02; FORCE RLS; app_definer-owned SECURITY DEFINER functions with fixed search_path and REVOKE FROM PUBLIC; app.current_time(). Requirements: R006, R007, R008, R009, R084, R106. Depends on: T08.
- [ ] **T10 incident-sim destination with action_key table** — Single action_key table; INSERT .. ON CONFLICT for incidents and abort; recomputed hash; never-expiring keys; incident-sim audience auth; test-only fault factory. Requirements: R010, R047, R096. Depends on: T08.

## M03 — Identity, sessions and durable admission

- [ ] **T11 Keycloak login, server-side sessions and revocation** — authlib code+PKCE with state in the server-side session store; opaque hashed session IDs; CSRF and origin checks; hand-written back-channel logout endpoint; admin-API enabled check on decision-class mutations; 60 s membership sync. Requirements: R011, R012, R013, R086. Depends on: T09, T05.
- [ ] **T12 Durable admission API and error mapping** — /api/v1 conversations/messages/runs; message+run+job+event committed before 202; scoped Idempotency-Key (24 h); one active run per conversation; interval resolved once; safe error schema and 401/403/404/409/422/429/503 mapping. Requirements: R015, R016, R017, R018, R115. Depends on: T09.

## M04 — Run leases, fencing, event journal and outbox

- [ ] **T13 Run lease, fence locking, heartbeat thread and fault factory** — Lease acquisition FOR UPDATE; fenced writes FOR SHARE; clock_timestamp via app.current_time(); published lock order; heartbeat on its own thread/connection; local monotonic deadline; model_permit with SKIP LOCKED; test-only fault factory for app services. Requirements: R019, R020, R087, R088, R098, R107. Depends on: T09.
- [ ] **T14 Gap-free event journal, wake-ups and outbox** — runs.next_event_seq under the runs lock; wake-up jobs committed with user events; sweeper; transactional outbox with leased delivery loop (no external channel). Requirements: R024, R089. Depends on: T13, T12.

## M05 — Authenticated MCP boundary

- [ ] **T15 Authenticated MCP server, token verifier and invocation handles** — mcp 2.3.x over Streamable HTTP pinned to 2026-07-28; custom TokenVerifier (iss, aud resource URL, azp, exp); X-Ops-Invocation as lookup key only; resolve_invocation with azp binding and server-derived allowlist. Requirements: R025, R026, R027, R031, R085. Depends on: T13, T05.
- [ ] **T16 Read tools, asset-sim and recovery tools** — asset-sim service; get_asset_status, get_recent_alerts (absolute interval, next_cursor), search_procedures over the governed store; get_incident_receipt and abort_incident for recover jobs only; fail-closed result validation. Requirements: R028, R029, R030. Depends on: T15, T10, T17.

## M06 — Evidence corpus and retrieval

- [ ] **T17 Expanded corpus, governed ingestion and lexical baseline** — Author >=12 documents (300-900 words), >=6 assets, 2 tenants incl. superseded, conflicting and injected sources; per-section IDs/hashes; tenant UUID and alert UUID fixtures; idempotent ingestion; PostgreSQL full-text retrieval with access filtering. Requirements: R032, R033, R099. Depends on: T09.
- [ ] **T18 Exact pgvector retrieval and comparison** — nomic-embed-text with search_document:/search_query: prefixes (tested); record model, dimension, digest; exact search with the same filters; comparison report vs lexical. Requirements: R034. Depends on: T17.

## M07 — LangChain draft node and LangGraph workflow

- [ ] **T19 Async LangChain ChatOllama DraftGenerator** — Versioned prompts; ChatOllama.ainvoke with AM-31 settings; structural validation incl. citation membership; one bounded repair; explicit MODEL_MODE fake|ollama, no fallback. Requirements: R036, R037, R039, R040, R041. Depends on: T07, T17, T02.
- [ ] **T20 LangGraph workflow with sync durability and stored checkpoint IDs** — Nodes per BUILD_SPEC section 8; retrieval before drafting; durability=sync; runs.checkpoint_id stored under fence and used on resume; idempotent pre-interrupt logic; ID-only interrupts; human waits release the lease; ANSWERED path. Requirements: R022, R038, R042, R091, R108, R114. Depends on: T19, T14, T16.

## M08 — Independent review, grant, execution and recovery

- [ ] **T21 Proposals, decisions, manual proposals, feedback and final grant** — Per-revision proposal IDs; expected_payload_sha256; first decision wins; author-set independence; expiry to BLOCKED_REVIEW; manual-proposal API; feedback endpoint; grant_execution final gate with UNIQUE(run_id), proposal/run binding, asset freshness and asset guard. Requirements: R023, R043, R044, R045, R046, R057, R090, R092, R093, R100, R113, R116. Depends on: T20, T11.
- [ ] **T22 Attempt protocol, recovery, abort and escalation** — grant inserts INTENT; mark_sent before I/O; record_outcome; recover jobs with redispatch/abort rules; reconciliation backoff; transport-timeout rule; CONFLICT and deadlines to ESCALATED; asset guard; receipt retention. Requirements: R048, R049, R050, R051, R094, R095, R109, R110. Depends on: T21.

## M09 — Scenario suite and model-quality evaluation

- [ ] **T23 Development eval set, gold labels and rubric** — ~60 dev cases over the expanded corpus with gold labels; deterministic graders for schema, citations and abstention; groundedness rubric for owner labelling. Requirements: R111. Depends on: T17.
- [ ] **T24 Executable scenario suite (core cards)** — Convert the development cards whose capabilities exist after T22 into pytest scenarios asserting application and destination state; run in CI. Requirements: R097. Depends on: T22.
- [ ] **T25 Model-quality evaluation A/B/C** — Conditions per AM-50; 3 isolated trials; case-level Wilson CIs, cluster bootstrap, paired McNemar; quality-gates.json committed before the holdout run; holdout run once per release candidate. Requirements: R070, R072, R073, R074. Depends on: T22, T18, T23, T03.

## M10 — Web workspace

- [ ] **T26 React workspace: conversation, evidence and approvals** — Vite + React + TS; three panels; the eight AM-40 states; safe rendering; authorized evidence viewer; approval card bound to revision/hash; manual proposal UI. Requirements: R014, R035, R052, R055, R056, R117. Depends on: T22, T11.
- [ ] **T27 Authenticated SSE replay and revocation (+ SSE cards)** — Last-Event-ID replay; heartbeats; cursor-reset snapshot; access recheck per frame; identity change closes stream; ESCALATED runs stay live; add SSE scenario cards. Requirements: R053, R054, R097. Depends on: T26, T14.

## M11 — Observability and operating budgets

- [ ] **T28 OpenTelemetry tracing with redaction** — OTel in api, worker, mcp-server, incident-sim; collector + one trace backend; bounded labels; redaction of tokens, handles and evidence. Requirements: R058, R059, R060. Depends on: T22.
- [ ] **T29 Budgets and degraded operation (+ budget cards)** — Queue/model/time/retry caps; dependency outages produce templated truthful states; capacity measured on the owner's hardware; add budget scenario cards. Requirements: R061, R062, R097. Depends on: T28.

## M12 — Containers, network isolation and full CI

- [ ] **T30 Hardened images, demo profile and Docker network isolation** — Multi-stage non-root images from uv.lock; Compose test/demo profiles (one worker replica); Docker networks deny model->destination and browser->internal; docker-kill recovery demo. Requirements: R063, R064, R065, R066, R067. Depends on: T22.
- [ ] **T31 Full CI with trust separation** **[owner approval]** — Extend T06: PostgreSQL integration, scenario suite, image build and scan; separate trusted workflow for real-model checks run manually; pinned SHAs; least privilege. Requirements: R075. Depends on: T30, T06.

## M13 — Retained-receipt restore

- [ ] **T32 Retained-receipt restore (+ restore card)** — Restore an older app backup against the retained destination; reconcile by original action IDs; runbook with real observations; add restore scenario card. Requirements: R068, R097. Depends on: T30.

## M14 — Portfolio release

- [ ] **T33 Clean-machine reproduction and three recorded demos** — From a clean clone: setup, success, denial and recovery demos; deterministic mode shown separately. Requirements: R077. Depends on: T24, T25, T27, T29, T31, T32.
- [ ] **T34 Interviewer README, limitations and publication** **[owner approval]** — README for interviewers, ADR index, limitations (one worker replica, owner-authored holdout, effort ranges), MIT license, push to github.com/jschnepel/MLOps. Requirements: R078. Depends on: T33.

## M15 — Optional v1.1+ extensions (non-blocking) *(optional, non-blocking)*

- [ ] **T35 kind/Helm with default-CNI NetworkPolicy tests** — Helm chart; kind default CNI (kube-network-policies); pod-level allow/deny and pod-kill tests. Requirements: R112. Depends on: T30.
- [ ] **T36 Paused-version upgrade and rollback rehearsal** — Route paused runs across a workflow_version bump; rollback test. Requirements: R069. Depends on: T32.
- [ ] **T37 SBOM and release provenance** — SBOM and provenance attestations for released images linked to tested inputs. Requirements: R076. Depends on: T31.
- [ ] **T38 Fenced checkpoint writes and multi-replica workers** — BaseCheckpointSaver subclass checking the run fence inside put/put_writes; enable multiple worker replicas; DEV-013 card. Requirements: R021. Depends on: T20.
- [ ] **T39 Opt-in Slack adapter** **[owner approval]** — Verified callbacks, identity mapping, outbox delivery, same review/execute policy. Requirements: R079. Depends on: T34.
- [ ] **T40 Approved budgeted cloud deployment** **[owner approval]** — Terraform/EKS only after owner cost and teardown approval. Requirements: R080. Depends on: T39.

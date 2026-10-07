# Ordered AI implementation backlog (OPS-BUILD-1.3.1)

Generated from `handoff/tasks.json`. Read BUILD_SPEC.md, then SPEC_AMENDMENTS.md (which takes precedence). Nothing here is complete.

## M00 — Baseline, sealed holdout intents and model probe

- [ ] **T01 Reproduce reference baseline on this machine** — Create the venv OUTSIDE the repo (e.g. %LOCALAPPDATA%\ops-ref-venv) and install the reference web+test extras WITHOUT -e; run the 58 tests and the recovery CLI on Windows; save outputs under reports/baseline/. Do not modify reference code. Requirements: R001. Depends on: none.
- [ ] **T03 Owner authors and seals holdout intents** **[owner]** — Define evals/holdout-case.schema.json. Owner writes ~25 case intents/requests without AI assistance, stores them off-machine or encrypted, commits only sha256 + count, and records the hash outside the local repo (push or dated email to self) before T02 starts. Gold labels come later in T41. Also record externally, with the holdout hash, the sha256 of handoff/prompts/incident-draft-v1.md and schema-repair-v1.md (the probe's unchanged prompts). Requirements: R071. Depends on: none.
- [ ] **T02 Environment inventory and qwen3:8b probe** — Per AM-31: author >=30 distinct probe inputs under evals/probe/, each with a small synthetic evidence bundle (not dev seeds, not holdout); use handoff/prompts/incident-draft-v1.md and schema-repair-v1.md unchanged at their recorded hashes; validate against 1.0 model-draft.schema.json; run via `uv run --isolated --no-project --with langchain-ollama==1.1.0` and save the freeze via importlib.metadata; reasoning=False, num_ctx=16384; first-pass and post-repair validity with Wilson CIs; identical-repeat rate at temperature 0; cold-start vs warm latency; VRAM; thinking leakage; mid-generation cancellation via `ollama ps`/GPU. Measurement, not tuning. Requirements: R081. Depends on: T01, T03.

## M01 — Workspace, bootstrap, contracts and walking skeleton

- [ ] **T04 uv workspace with per-service directories and locks** — ADR-0001 layout (core/, api/, worker/, mcp-server/, asset-sim/, incident-sim/). Move the whole reference unit unchanged into reference/ (src, tests, pyproject, Makefile, Dockerfile, compose, integrations, scripts/init_demo.py, scripts/check_reference.sh), excluded from the uv workspace and from root ruff/mypy/pytest with provenance/reference-code-hashes.remap.json and checker support; root pyproject becomes the uv workspace root. Create data/seed-ids.json (tenant/persona UUIDs). Resolve versions per AM-30, commit uv.lock, add jsonschema to the dev group; checker skips .venv*/node_modules. ruff, mypy, pytest via one Python entry point (`uv run python scripts/check.py`; no make on this machine). Re-create the reference venv from reference/ and re-run its suite. Requirements: R003, R031, R121. Depends on: T01.
- [ ] **T05 Dev bootstrap: Compose dev profile, Keycloak realm, secrets, seed IDs** — Compose dev profile with PostgreSQL+pgvector and Keycloak 26.8.x (pinned digest); fixed KC_HOSTNAME so iss matches for host and container callers; documented dev topology (which processes run in containers vs host); realm export with 5 personas (UUIDs from data/seed-ids.json), workload clients and hardcoded-audience mappers (MCP_RESOURCE_URL parameter, incident-sim); view-users service account; Windows-friendly secret generation outside git; host Ollama bridge. Requirements: R101, R102. Depends on: T04.
- [ ] **T06 Early secret-free CI** **[owner]** — GitHub Actions workflow for ruff, mypy and unit tests with pinned action SHAs and read-only token; requires the public repo to exist. Requirements: R103. Depends on: T04.
  - *Review note:* Requires a public repo at M01 while publication approval sits at T34 - owner decides: approve early publication or start private and flip public at T34.
- [ ] **T07 Contracts, state machine, schema alignment and reference migration** — Pydantic contracts; canonical JSON v1; transition table incl. ESCALATED, ABANDONED_UNVERIFIED and the slot rule; apply every AM-80 schema/example/fixture change incl. new schemas and error codes; update verify_handoff.py (renamed field, tools/ and evals/ schemas, skip dirs); port the pure-core reference tests and write reference/TRACEABILITY.md mapping all 58 to port/replace/drop. Before contract code, commit at least one negative example per AM-80 row (with its failure reason in index.json). Checker reads/writes UTF-8 and rejects \r in fixtures, schemas, examples and prompts. Requirements: R004, R005, R082, R083, R104, R120, R123. Depends on: T04.
- [ ] **T08 Walking skeleton: api, worker, mcp-server, incident-sim** — Fake model; PostgreSQL and Keycloak from T05; processes api, worker, mcp-server, incident-sim. Real client-credentials tokens from T05 (no shared secrets). POST run -> job -> worker -> mcp-server create_incident -> incident-sim -> receipt -> event. Schema is Alembic revision 1 (extended by T09); incident-sim code is the base T10 extends. Requirements: R105. Depends on: T05, T07.

## M02 — PostgreSQL authority model and independent destination

- [ ] **T09 Migrations, roles, RLS and hardened definer functions** — Alembic schema (incl. run_lease, runs.next_event_seq, runs.checkpoint_id, execution_grant.run_id UNIQUE, action_attempt, sessions); roles per AM-02; FORCE RLS; app_definer-owned SECURITY DEFINER functions with fixed search_path and REVOKE FROM PUBLIC; app.current_time(). Requirements: R006, R007, R008, R009, R084, R106, R122. Depends on: T08.
  - *Review note:* RLS bootstrap: RLS-free run_directory(run_id, tenant_id) + invocation_context readable only by app_definer/sweeper; named cross-tenant sweeper policy for expire_proposals, membership sync, session lookup.
  - *Review note:* Definer functions declare SET app.tenant_id='' as an attribute; test that a preset tenant from mcp_exec is ignored.
  - *Review note:* app.current_time() test offset gated by PROFILE=test.
- [ ] **T10 incident-sim destination with action_key table** — Single action_key table; INSERT .. ON CONFLICT for incidents and abort; recomputed hash; never-expiring keys; incident-sim audience auth; test-only fault factory. Requirements: R010, R047, R096, R098. Depends on: T08.
  - *Review note:* Destination at READ COMMITTED; keep GET /internal/actions/{id}; abort stores grant hash; POST onto ABORTED returns tombstone regardless of hash (late-POST fault test).
  - *Review note:* Fault factory lives in shared core.testing.faults (R098 co-owned with T13).

## M03 — Identity, sessions and durable admission

- [ ] **T11 Keycloak login, server-side sessions and revocation** — authlib code+PKCE with state in the server-side session store; opaque hashed session IDs; CSRF and origin checks; hand-written back-channel logout endpoint; admin-API enabled check on decision-class mutations; 60 s membership sync. Requirements: R011, R012, R013, R086. Depends on: T09, T05.
  - *Review note:* Admin-API check: 2 s timeout, cached service-account token, fail closed 503 retryable when Keycloak is down/slow. The 'grants blocked <=60 s' half of R086 is verified in T21.
- [ ] **T12 Durable admission API and error mapping** — /api/v1 conversations/messages/runs; message+run+job+event committed before 202; scoped Idempotency-Key (24 h); one active run per conversation; interval resolved once; safe error schema and 401/403/404/409/422/429/503 mapping. Requirements: R015, R016, R017, R018, R115. Depends on: T09.

## M04 — Run leases, fencing, event journal and outbox

- [ ] **T13 Run lease, fence locking, heartbeat thread and fault factory** — Lease acquisition FOR UPDATE; fenced writes FOR SHARE; clock_timestamp via app.current_time(); published lock order; heartbeat on its own thread/connection; local monotonic deadline; model_permit with SKIP LOCKED; test-only fault factory for app services. Requirements: R019, R020, R087, R088, R098, R107. Depends on: T09.
  - *Review note:* Transactions that write run_lease take FOR UPDATE from the start (no FOR SHARE upgrade).
  - *Review note:* Owner re-fence path hands the new fence to the heartbeat thread atomically.
  - *Review note:* Lock order includes the asset-guard advisory lock and memberships (AM-12); also place jobs, invocation_context, model_permit, sessions.
  - *Review note:* Gate heartbeat renewal on event-loop liveness and the 90 s compute budget.
- [ ] **T14 Gap-free event journal, wake-ups and outbox** — runs.next_event_seq under the runs lock; wake-up jobs committed with user events; sweeper; transactional outbox with leased delivery loop (no external channel). Requirements: R024, R089. Depends on: T13, T12.

## M05 — Authenticated MCP boundary and governed corpus

- [ ] **T15 Authenticated MCP server, token verifier and invocation handles** — mcp 2.3.x over Streamable HTTP pinned to 2026-07-28; custom TokenVerifier (iss, aud resource URL, azp, exp); X-Ops-Invocation as lookup key only; resolve_invocation with azp binding and server-derived allowlist. Requirements: R025, R026, R027, R031, R085. Depends on: T13, T05.
  - *Review note:* status=error-only-before-grant applies to authorized callers; auth failures never reveal action_id.
  - *Review note:* Allowlist checks attempt state (create_incident only with no attempt or INTENT, not cancelled, before deadline).
- [ ] **T17 Expanded corpus, governed ingestion and lexical baseline** — Author >=12 documents (300-900 words), >=6 assets, 2 tenants incl. superseded, conflicting and injected sources; per-section IDs/hashes; tenant UUID and alert UUID fixtures; idempotent ingestion; PostgreSQL full-text retrieval with access filtering. Requirements: R032, R033, R099. Depends on: T09.
- [ ] **T16 Read tools, asset-sim and recovery tools** — asset-sim service; get_asset_status, get_recent_alerts (absolute interval, next_cursor), search_procedures over the governed store; get_incident_receipt and abort_incident for recover jobs only; fail-closed result validation. Requirements: R028, R029, R030. Depends on: T15, T10, T17.
  - *Review note:* search_procedures reads the governed store built in T17.

## M06 — Vector retrieval

- [ ] **T18 Exact pgvector retrieval and comparison** — nomic-embed-text with search_document:/search_query: prefixes (tested); record model, dimension, digest; exact search with the same filters; comparison report vs lexical. Requirements: R034. Depends on: T17.
- [ ] **T41 Owner gold-labels the sealed holdout against the frozen corpus** **[owner]** — Owner, without AI assistance, adds evidence IDs and expected outcomes to the sealed holdout cases against the frozen T17 corpus version; re-seals (sha256 committed and recorded externally). Corpus changes after this require re-labelling. Requirements: R071. Depends on: T03, T17.

## M07 — LangChain draft node and LangGraph workflow

- [ ] **T19 Async LangChain ChatOllama DraftGenerator** — Versioned prompts; ChatOllama.ainvoke with AM-31 settings; structural validation incl. citation membership; one bounded repair; explicit MODEL_MODE fake|ollama, no fallback. Requirements: R036, R037, R039, R040, R041. Depends on: T07, T17, T02, T03.
- [ ] **T20 LangGraph workflow with sync durability and stored checkpoint IDs** — Nodes per BUILD_SPEC section 8; retrieval before drafting; durability=sync; runs.checkpoint_id stored under fence and used on resume; idempotent pre-interrupt logic; ID-only interrupts; human waits release the lease; ANSWERED path. Requirements: R022, R038, R042, R091, R108, R114. Depends on: T19, T14, T16.
  - *Review note:* LangGraph 1.2.14: explicit checkpoint_id => is_replaying, pending writes NOT re-applied (_loop.py:330, 766-770); Command(resume) keeps RESUME writes; invoke(None, checkpoint_id) forks (886-912). Store IDs from stream_mode='checkpoints'/aget_state, update after forks, make every node idempotent, test kill-mid-superstep and kill-at-interrupt, join stale in-process tasks before re-acquiring.

## M08 — Independent review, grant, execution and recovery

- [ ] **T21 Proposals, decisions, manual proposals, feedback and final grant** — Per-revision proposal IDs; expected_payload_sha256; first decision wins; author-set independence; expiry to BLOCKED_REVIEW; manual-proposal API; feedback endpoint; grant_execution final gate with UNIQUE(run_id), proposal/run binding, asset freshness and asset guard. Requirements: R023, R043, R044, R045, R046, R057, R090, R092, R093, R100, R113, R116, R120. Depends on: T20, T11.
  - *Review note:* Asset guard via pg_advisory_xact_lock(tenant, asset) first in lock order; refusal 409 ASSET_ACTION_UNRESOLVED.
  - *Review note:* Revision from BLOCKED_REVIEW requires a free conversation slot (SLOT_OCCUPIED 409).
  - *Review note:* Verify R086's grant-blocking half (membership sync <=60 s).
- [ ] **T22 Attempt protocol, recovery, abort and escalation** — grant inserts INTENT; mark_sent before I/O; record_outcome; recover jobs with redispatch/abort rules; reconciliation backoff; transport-timeout rule; CONFLICT and deadlines to ESCALATED; asset guard; receipt retention. Requirements: R048, R049, R050, R051, R094, R095, R109, R110, R046, R118, R119. Depends on: T21.
  - *Review note:* Redispatch skips the section 13 gate via lookup_action -> mark_sent; mark_sent re-checks cancel/deadline under runs lock.
  - *Review note:* Cancellation after SENT aborts immediately; otherwise abort at dispatch deadline (<=5 min FAILED latency stated).
  - *Review note:* Operator CLI `ops resolve-escalation` -> ABANDONED_UNVERIFIED with operator_resolutions audit row.
  - *Review note:* Late destination evidence on ABANDONED_UNVERIFIED emits action.late_evidence; record_outcome never transitions terminal runs; recover jobs stay allowed.

## M09 — Scenario suite and model-quality evaluation

- [ ] **T23 Development eval set, gold labels and rubric** — ~60 dev cases over the expanded corpus with gold labels; deterministic graders for schema, citations and abstention; groundedness rubric for owner labelling. Requirements: R111. Depends on: T17.
- [ ] **T24 Executable scenario suite (core cards)** — Convert the development cards whose capabilities exist after T22 into pytest scenarios asserting application and destination state; run in CI. Requirements: R097. Depends on: T22.
  - *Review note:* Update card vocabulary: DEV-018 -> ESCALATED; DEV-015 -> SUCCEEDED with note; DEV-017 time-bounded; DEV-008 lazy BLOCKED_REVIEW commits even when the decision returns 409.
  - *Review note:* Add cards for escalation, tombstone/late POST, asset guard, operator resolution, cancel-vs-mark_sent.
  - *Review note:* DEV-029 needs a fault-injectable outbox sink.
  - *Review note:* Runs locally against Postgres until T31 adds Postgres to CI.
  - *Review note:* Update evals/README (80/40 and separate-reviewer text are stale).
- [ ] **T25 Model-quality evaluation A/B/C** — Conditions per AM-50; 3 isolated trials; case-level Wilson CIs, cluster bootstrap, paired McNemar; quality-gates.json committed before the holdout run; holdout run once per release candidate. Requirements: R070, R072, R073, R074, R071. Depends on: T22, T18, T23, T41.
  - *Review note:* Condition A deterministic metrics only; blind shuffled B/C groundedness labelling; ~20% re-label for intra-rater kappa; safety metrics any-trial; report ~30-point detectability floor.

## M10 — Web workspace

- [ ] **T26 React workspace: conversation, evidence and approvals** — Vite + React + TS; three panels; the eight AM-40 states; safe rendering; authorized evidence viewer; approval card bound to revision/hash; manual proposal UI. Requirements: R014, R035, R052, R055, R056, R117. Depends on: T22, T11.
  - *Review note:* Include ANSWERED ('answered, no action'), CANCELLED and ABANDONED_UNVERIFIED in the state views; the reconnect assertion (state 8) lands in T27.
- [ ] **T27 Authenticated SSE replay and revocation (+ SSE cards)** — Last-Event-ID replay; heartbeats; cursor-reset snapshot; access recheck per frame; identity change closes stream; ESCALATED runs stay live; add SSE scenario cards. Requirements: R053, R054, R097. Depends on: T26, T14.

## M11 — Observability and operating budgets

- [ ] **T28 OpenTelemetry tracing with redaction** — OTel in api, worker, mcp-server, incident-sim; collector + one trace backend; bounded labels; redaction of tokens, handles and evidence. Requirements: R058, R059, R060. Depends on: T22.
- [ ] **T29 Budgets and degraded operation (+ budget cards)** — Queue/model/time/retry caps; dependency outages produce templated truthful states; capacity measured on the owner's hardware; add budget scenario cards. Requirements: R061, R062, R097. Depends on: T28.

## M12 — Containers, network isolation and full CI

- [ ] **T30 Hardened images, demo profile and Docker network isolation** — Multi-stage non-root images from uv.lock; Compose test/demo profiles (one worker replica); Docker networks deny model->destination and browser->internal; docker-kill recovery demo. Requirements: R063, R064, R065, R066, R067. Depends on: T22.
  - *Review note:* Enforce one worker replica: startup advisory lock; a second worker refuses to start (tested).
- [ ] **T31 Full CI with trust separation** **[owner]** — Extend T06: PostgreSQL integration, scenario suite, image build and scan; separate trusted workflow for real-model checks run manually; pinned SHAs; least privilege. Requirements: R075. Depends on: T30, T06.

## M13 — Retained-receipt restore

- [ ] **T32 Retained-receipt restore (+ restore card)** — Restore an older app backup against the retained destination; reconcile by original action IDs; runbook with real observations; add restore scenario card. Requirements: R068, R097. Depends on: T30.

## M14 — Portfolio release

- [ ] **T33 Clean-machine reproduction and three recorded demos** — From a clean clone: setup, success, denial and recovery demos; deterministic mode shown separately. Requirements: R077. Depends on: T24, T25, T27, T29, T31, T32.
- [ ] **T34 Interviewer README, limitations and publication** **[owner]** — README for interviewers, ADR index, limitations (one worker replica, owner-authored holdout, effort ranges), MIT license, push to github.com/jschnepel/MLOps. Requirements: R078, R002. Depends on: T33.

## M15 — Optional v1.1+ extensions (non-blocking) *(optional, non-blocking)*

- [ ] **T35 kind/Helm with default-CNI NetworkPolicy tests** — Helm chart; kind default CNI (kube-network-policies); pod-level allow/deny and pod-kill tests. Requirements: R112. Depends on: T30.
- [ ] **T36 Paused-version upgrade and rollback rehearsal** — Route paused runs across a workflow_version bump; rollback test. Requirements: R069. Depends on: T32.
- [ ] **T37 SBOM and release provenance** — SBOM and provenance attestations for released images linked to tested inputs. Requirements: R076. Depends on: T31.
- [ ] **T38 Fenced checkpoint writes and multi-replica workers** — BaseCheckpointSaver subclass checking the run fence inside put/put_writes; enable multiple worker replicas; DEV-013 card. Requirements: R021. Depends on: T20.
- [ ] **T39 Opt-in Slack adapter** **[owner]** — Verified callbacks, identity mapping, outbox delivery, same review/execute policy. Requirements: R079. Depends on: T34.
- [ ] **T40 Approved budgeted cloud deployment** **[owner]** — Terraform/EKS only after owner cost and teardown approval. Requirements: R080. Depends on: T39.

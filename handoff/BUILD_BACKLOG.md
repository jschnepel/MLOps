# Ordered AI implementation backlog (OPS-BUILD-1.3.5)

Generated from `handoff/tasks.json`. Read BUILD_SPEC.md, then SPEC_AMENDMENTS.md (which takes precedence). Nothing here is complete.

## M00 — Baseline, sealed holdout intents and model probe

- [ ] **T01 Reproduce reference baseline on this machine** — Create the venv OUTSIDE the repo (e.g. %LOCALAPPDATA%\ops-ref-venv) and install the reference web+test extras WITHOUT -e; run the 58 tests and the recovery CLI on Windows; save outputs under reports/baseline/. Do not modify reference code. Requirements: R001. Depends on: none.
- [ ] **T03 Owner authors and seals holdout intents** **[owner]** — Define evals/holdout-case.schema.json. Owner writes ~25 case intents/requests without AI assistance, stores them off-machine or encrypted, commits only sha256 + count, and records the hash outside the local repo (push or dated email to self) before T02 starts. Gold labels come later in T41. Also record externally, with the holdout hash, the sha256 of handoff/prompts/incident-draft-v1.md and schema-repair-v1.md (the probe's unchanged prompts). Requirements: R071. Depends on: none.
  - *Review note:* Hash procedure: sha256 of the exact file bytes via `python -c "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" <file>`; the owner attests the external record (dated email) in SESSION_STATE.md.
- [ ] **T02 Environment inventory and qwen3:8b probe** — Per AM-31: author >=30 distinct probe inputs under evals/probe/, each with a small synthetic evidence bundle (not dev seeds, not holdout); use handoff/prompts/incident-draft-v1.md and schema-repair-v1.md unchanged at their recorded hashes; validate against 1.0 model-draft.schema.json; run via `uv run --isolated --no-project --with langchain-ollama==1.1.0` and save the freeze via importlib.metadata; reasoning=False, num_ctx=16384; first-pass and post-repair validity with Wilson CIs; identical-repeat rate at temperature 0; cold-start vs warm latency; VRAM; thinking leakage; mid-generation cancellation via `ollama ps`/GPU. Measurement, not tuning. Writes data/model-pins.json {model, digest, ollama_version, probed_at}. Requirements: R081. Depends on: T01, T03.

## M01 — Workspace, bootstrap, contracts, schemas and walking skeleton

- [ ] **T04 uv workspace, locks, check entry point and seed IDs** — ADR-0001 layout (core/, api/, worker/, mcp-read/, mcp-write/, asset-sim/, incident-sim/ with trust-boundary READMEs); root pyproject becomes the uv workspace root with `[tool.uv.workspace] exclude=["reference"]`; resolve versions per AM-30 and commit uv.lock; add jsonschema to the dev group; `scripts/check.py` runs ruff + mypy + pytest (no make on Windows); create data/seed-ids.json (tenant/persona UUIDs). Hyphenated service dirs get explicit import names; none is named `mcp`. Requirements: R003, R031. Depends on: T01.
- [ ] **T42 Reference move, hash remap and zip-based manifest** — Move the whole reference unit unchanged into reference/ (src, tests, pyproject, Makefile, Dockerfile, compose, integrations, scripts/init_demo.py, scripts/check_reference.sh); add provenance/reference-code-hashes.remap.json and checker support; move MANIFEST.sha256 to provenance/MANIFEST-1.0.sha256 and make `verify_handoff.py --manifest` verify it against provenance/handoff-1.0.zip entries with zipfile (AM-00); checker skips .venv*/node_modules/reference build outputs; re-create the external reference venv from reference/ and re-run its suite. Requirements: R121. Depends on: T04.
  - *Review note:* Both T42 and T45 edit verify_handoff.py: T45 runs after T42.
- [ ] **T05 Dev bootstrap: what the walking skeleton needs** — Compose dev profile with PostgreSQL+pgvector (pinned major version and digest) and Keycloak 26.8.x (pinned digest); every published port bound to 127.0.0.1; KC_HOSTNAME=http://localhost:<port> plus KC_HOSTNAME_BACKCHANNEL_DYNAMIC=true so iss matches for host and container callers; documented host-vs-container topology; realm import (secrets via placeholders) with workload clients and hardcoded-audience mappers (MCP_READ_RESOURCE_URL and MCP_WRITE_RESOURCE_URL parameters, incident-sim), a dev-only direct-grant test client, and two personas (requester alex, reviewer sam) from data/seed-ids.json; secrets generated under %LOCALAPPDATA%\ops-copilot and delivered via Compose `secrets:` (entrypoint wrapper exports from /run/secrets; Keycloak has no _FILE variant); Windows-friendly bootstrap script. Requirements: R102, R101. Depends on: T04.
  - *Review note:* Do not route host callers through host.docker.internal: it resolves to the LAN IP and cannot reach 127.0.0.1-bound ports. Keycloak: KC_HOSTNAME=http://localhost:<port> plus KC_HOSTNAME_BACKCHANNEL_DYNAMIC=true (verified in the round-4 dry run).
  - *Review note:* Two MCP audiences and clients: MCP_READ_RESOURCE_URL / MCP_WRITE_RESOURCE_URL; the worker holds one client but two handle types.
- [ ] **T43 Dev bootstrap: remaining personas, service account, admin cleanup** — Add the remaining three personas (lee, riley, jordan) and tenant beta; the view-users service account for the AM-20 admin-API check; delete the temporary Keycloak bootstrap admin after realm import (self-delete via admin REST with the bootstrap token; verify on the cached 26.8.0 image first); finish the topology document. Requirements: R101, R102. Depends on: T05.
- [ ] **T44 Ollama bridge, network runbook and model pins consumption** — Container route to host Ollama (not host.docker.internal for host callers); write docs/runbooks/ollama-network.md with the owner-applied firewall commands restricting port 11434 to loopback plus the Docker/WSL subnet (the agent changes no system settings); worker reads data/model-pins.json for the digest check (implemented in T19). Requirements: R101. Depends on: T05.
- [ ] **T06 Early secret-free CI** **[owner]** — GitHub Actions workflow for ruff, mypy and unit tests with pinned action SHAs and read-only token; requires the public repo to exist. Requirements: R103. Depends on: T04.
  - *Review note:* Requires a public repo at M01 while publication approval sits at T34 - owner decides: approve early publication or start private and flip public at T34.
- [ ] **T07 Core contracts, state machine, job model and reason enum** — Pydantic contracts; canonical JSON v1; transition table incl. the creation row (null -> QUEUED), ESCALATED, ABANDONED_UNVERIFIED, the BLOCKED_REVIEW rows and the slot rule; runs.intent and requester-asserted supersedes_run_id as run fields (never from drafts); shared reason enum; job-type model (AM-20.4 dedup keys); tombstone object; supersedes_run_id in the hashed payload; state_version-only-on-transition defined here (tested in T09/T21). Requirements: R004, R005, R082, R120. Depends on: T04.
- [ ] **T45 Schema, example and fixture alignment with negative probes** — Apply every AM-80 row (event, tool-result, model-draft question, feedback/manual-proposal/revision/cancel-response, error codes incl. ASSET_INCIDENT_EXISTS and AUTHORITY_VIOLATION, tools/, job, model-pins, action-outcome tombstone, decision expected_payload_sha256, proposal supersedes_run_id injected from runs and authored_by, message/revision schemas with structured supersedes_run_id and kind enum incl. ask/status, route schema, fixtures UUID mapping); commit at least one negative example per row before code; update verify_handoff.py (renamed field, tools/ and evals/ meta-validation, UTF-8, reject CR); evals/holdout-case.schema.json is T03's, tolerate absence. Requirements: R083, R104. Depends on: T07, T42.
- [ ] **T46 Reference traceability and pure-core test port** — Write reference/TRACEABILITY.md mapping all 58 reference tests to port / replace-by (target test + owning task) / drop (AM-70 reason); port the pure-core tests by rewriting them against core (the originals import Store/ControlService). Requirements: R123. Depends on: T42, T07.
- [ ] **T08 Walking skeleton: api, worker, mcp-read, mcp-write, incident-sim** — Fake model; PostgreSQL and Keycloak from T05; processes api, worker, mcp-read, mcp-write, incident-sim. Real client-credentials tokens from T05 (no shared secrets). POST run -> job -> worker -> mcp-read (one read tool) -> fake draft -> decision -> mcp-write create_incident -> incident-sim -> receipt -> event. Schema is Alembic revision 1 (extended by T09); incident-sim code is the base T10 extends. The skeleton-debt list in SESSION_STATE.md is committed BEFORE coding; the skeleton must include a decision step (second persona) and route every transition through T07's table even though definer functions arrive in T09. Requirements: R105. Depends on: T05, T07.

## M02 — PostgreSQL authority model and independent destination

- [ ] **T09 Migrations, roles, RLS and hardened definer functions** — Implement AM-20 in code: Alembic schema (incl. run_state_history, action_attempt_state, drafts, run_directory, run_lease, jobs with dedup keys, execution_grant UNIQUE(run_id), sessions); roles per AM-20.1 incl. test_harness via the `testclock` Alembic branch; exact grants per AM-20.2; every AM-20.3 definer function (incl. create_run, revoke_handles, record_status_answer) with search_path/REVOKE/GRANT-to-named-callers, session_user checks and transaction-local set_config; transition_run restricted to worker and pre-grant targets; seed data migrations under migrator BYPASSRLS; sweeper_all policies on memberships and jobs; action_attempt_state seq ordering; clock_offset column; RLS policies per AM-20.5 incl. FORCE; app.current_time() per AM-20.6. Requirements: R006, R007, R008, R009, R084, R106, R122, R124, R126, R128. Depends on: T08, T45.
  - *Review note:* RLS bootstrap: RLS-free run_directory(run_id, tenant_id) + invocation_context readable only by app_definer/sweeper; named cross-tenant sweeper policy for expire_proposals, membership sync, session lookup.
  - *Review note:* Definer functions declare SET app.tenant_id='' as an attribute; test that a preset tenant from mcp_exec is ignored.
  - *Review note:* app.test_clock exists only in the test-profile migration; app.current_time() never reads GUCs (R126).
  - *Review note:* session_user remains the invoking login role inside SECURITY DEFINER; functions branch on it for allowed-caller checks.
  - *Review note:* Every service asserts at start that app.test_clock is absent outside the test profile; the demo bootstrap check alone is not enough.
- [ ] **T10 incident-sim destination with action_key table** — Single action_key table; INSERT .. ON CONFLICT for incidents and abort; recomputed hash; never-expiring keys; incident-sim audience auth; test-only fault factory. Requirements: R010, R047, R096, R098. Depends on: T08.
  - *Review note:* Destination at READ COMMITTED; keep GET /internal/actions/{id}; abort stores grant hash; POST onto ABORTED returns tombstone regardless of hash (late-POST fault test).
  - *Review note:* Fault factory lives in shared core.testing.faults (R098 co-owned with T13).
  - *Review note:* incident-sim requires azp = mcp-write client in addition to aud; REJECTED is a permanent key state with tombstone shape; add a detective check that every destination key matches a grant hash.
  - *Review note:* POST onto REJECTED returns the REJECTED tombstone; abort onto REJECTED likewise; both in R096 fault tests.

## M03 — Identity, sessions and durable admission

- [ ] **T11 Keycloak login, server-side sessions and revocation** — authlib code+PKCE with state in the server-side session store; opaque hashed session IDs; CSRF and origin checks; hand-written back-channel logout endpoint; admin-API enabled check on decision-class mutations; 60 s membership sync. Requirements: R011, R012, R013, R086. Depends on: T09, T43.
  - *Review note:* Admin-API check: 2 s timeout, cached service-account token, fail closed 503 retryable when Keycloak is down/slow. The 'grants blocked <=60 s' half of R086 is verified in T21.
  - *Review note:* Membership sync fails closed: grants refuse if the last successful sync is older than 120 s; a deleted user (admin API 404) maps to 401. Run the admin-API check before opening the DB transaction.
  - *Review note:* Back-channel logout: verify signature with an alg allowlist, exp, sid/sub, and a durable (Postgres) jti store; exempt the endpoint from CSRF/Idempotency-Key with a forged-token negative test.
  - *Review note:* Start a core logging redaction filter here (OIDC code, connection strings, tokens, handles) with a canary test; T28 extends it to telemetry.
- [ ] **T12 Durable admission API and error mapping** — /api/v1 conversations/messages/runs; message+run+job+event committed before 202; scoped Idempotency-Key (24 h); one active run per conversation; interval resolved once; safe error schema and 401/403/404/409/422/429/503 mapping; the AM-16 admission router with its six routes (investigate, clarification_reply, status_question, readonly_answer, clarify, reject) as a table in core/routing.py, deterministic-first; a model hint can only produce clarify; investigate/readonly_answer go through create_run with intent; status questions are stored via record_status_answer. Requirements: R015, R016, R017, R018, R115, R129. Depends on: T09.
  - *Review note:* Slot rule: partial unique index on runs(conversation_id) over AM-10 active states, plus a concurrent admission test.
  - *Review note:* status_question stores question and answer as messages and emits a conversation-scoped status.answered event, so it is audited.

## M04 — Run leases, fencing, event journal and outbox

- [ ] **T13 Run lease, fence locking, heartbeat thread and fault factory** — Lease acquisition FOR UPDATE; fenced writes FOR SHARE; clock_timestamp via app.current_time(); published lock order; heartbeat on its own thread/connection; local monotonic deadline; model_permit with SKIP LOCKED; test-only fault factory for app services. Requirements: R019, R020, R087, R088, R098, R107. Depends on: T09.
  - *Review note:* Transactions that write run_lease take FOR UPDATE from the start (no FOR SHARE upgrade).
  - *Review note:* Owner re-fence path hands the new fence to the heartbeat thread atomically.
  - *Review note:* Lock order includes the asset-guard advisory lock and memberships (AM-12); also place jobs, invocation_context, model_permit, sessions.
  - *Review note:* Gate heartbeat renewal on event-loop liveness and the 90 s compute budget.
  - *Review note:* Advisory lock: asset_id NOT NULL and read before locking; use hashtextextended (AM-12 wording updated); test that app_definer may call pg_advisory_xact_lock.
  - *Review note:* Lock order now includes messages, decisions and operator_resolutions; the outbox appends notification.failed in a separate transaction (AM-12).
  - *Review note:* Handle revocation goes through revoke_handles(run_id, fence); the worker has no column grant on invocation_context.revoked_at.
- [ ] **T14 Gap-free event journal, wake-ups and outbox** — runs.next_event_seq under the runs lock; wake-up jobs committed with user events; sweeper; transactional outbox with leased delivery loop (no external channel). Requirements: R024, R089. Depends on: T13, T12.
  - *Review note:* Jobs carry dedup_key UNIQUE per AM-20.4; recover jobs never created by either MCP server.
  - *Review note:* append_event enforces payload rules inside the function (no status field from api/worker on tool.completed); action.granted emitted by grant_execution; action.redispatched by mark_sent when attempt_no > 1; deliver_outbox is a job type.

## M05 — MCP read and write servers and governed corpus

- [ ] **T15 Authenticated MCP read server (mcp-read), token verifier and invocation handles** — mcp-read on official SDK 2.x over Streamable HTTP pinned to 2026-07-28; custom TokenVerifier (iss, aud = MCP_READ_RESOURCE_URL, azp, exp); X-Ops-Invocation as lookup key only; resolve_invocation with azp binding, server binding (read handles only) and server-derived allowlist; DB role mcp_read holds EXECUTE on resolve_invocation, asset_scope and search_procedures_scoped only. Requirements: R025, R026, R027, R031, R085, R131. Depends on: T13, T05.
  - *Review note:* status=error-only-before-grant applies to authorized callers; auth failures never reveal action_id.
  - *Review note:* Allowlist checks attempt state (create_incident only with no attempt or INTENT, not cancelled, before deadline).
  - *Review note:* mcp-read reads asset data via asset_scope + asset-sim, and procedures via search_procedures_scoped; it never has table access.
  - *Review note:* resolve_invocation derives job_type from the jobs row and server from job_type; the worker-written server column is a hint only.
- [ ] **T47 Authenticated MCP write server (mcp-write) and recovery tools** — mcp-write on the same SDK/protocol pin; TokenVerifier with aud = MCP_WRITE_RESOURCE_URL; accepts execute/recover handles only; DB role mcp_exec holds EXECUTE on resolve_invocation, grant_execution, mark_sent, record_outcome, request_abort, lookup_action only; hosts create_incident, get_incident_receipt (recover only) and abort_incident; sole caller of incident-sim with the incident-sim audience and azp. Requirements: R030, R131. Depends on: T15, T10.
  - *Review note:* Handle server binding is checked inside resolve_invocation by comparing the handle's server field with session_user (mcp_read vs mcp_exec).
  - *Review note:* record_outcome verifies the receipt hash against the grant hash, but both reach it through mcp-write: v1 states plainly in the threat model that mcp-write is trusted for outcome truth, with T10's detective check as the control. Optional hardening for v1.1: incident-sim HMAC-signs receipts with a key held in an app_definer-only table. R131 wording: named function sets (both roles share resolve_invocation).
- [ ] **T17 Expanded corpus, governed ingestion and lexical baseline** — Author >=12 documents (300-900 words), >=6 assets, 2 tenants incl. superseded, conflicting and injected sources; per-section IDs/hashes; tenant UUID and alert UUID fixtures; idempotent ingestion; PostgreSQL full-text retrieval with access filtering. Requirements: R032, R033, R099. Depends on: T09.
- [ ] **T16 Read tools and asset-sim on mcp-read** — asset-sim service (trusts only the mcp-read workload token and forwarded tenant/asset context, applies its own tenant filter); get_asset_status, get_recent_alerts (absolute interval, next_cursor), search_procedures over the governed store (vector mode: mcp-read computes the nomic search_query embedding); fail-closed result validation. Requirements: R028, R029. Depends on: T15, T10, T17.
  - *Review note:* search_procedures reads the governed store built in T17.
  - *Review note:* search_procedures vector mode: mcp-read computes the nomic search_query embedding and passes it to search_procedures_scoped.

## M06 — Vector retrieval

- [ ] **T18 Exact pgvector retrieval and comparison** — nomic-embed-text with search_document:/search_query: prefixes (tested); record model, dimension, digest; exact search with the same filters; comparison report vs lexical. Requirements: R034. Depends on: T17.
- [ ] **T41 Owner gold-labels the sealed holdout against the frozen corpus** **[owner]** — Owner, without AI assistance, adds evidence IDs and expected outcomes to the sealed holdout cases against the frozen T17 corpus version; re-seals (sha256 committed and recorded externally). Corpus changes after this require re-labelling. Requirements: R071. Depends on: T03, T17.

## M07 — LangChain draft node and LangGraph workflow

- [ ] **T19 Async LangChain ChatOllama DraftGenerator** — Versioned prompts; ChatOllama.ainvoke with AM-31 settings; structural validation incl. citation membership; one bounded repair; the AM-16 model router (DraftGenerator factory: fake | qwen3:8b | future named model) with no silent fallback; writes the run manifest {run_id, model_route, model_digest, prompt_version, corpus_version, retrieval_mode} and records the route in explanation.ready. Warm-up call at startup compares /api/show digest with data/model-pins.json and fails closed on mismatch (R127). Requirements: R036, R037, R039, R040, R041, R127, R130. Depends on: T07, T17, T02, T03, T44.
- [ ] **T20 LangGraph workflow with sync durability and stored checkpoint IDs** — Nodes per AM-12 incl. the route_request graph router whose conditional edges are generated from the core/routing.py table; retrieval before drafting; durability=sync; runs.checkpoint_id stored under fence and used on resume; idempotent pre-interrupt logic; ID-only interrupts; human waits release the lease; ANSWERED path. Requirements: R022, R038, R042, R091, R108, R114, R129. Depends on: T19, T14, T16.
  - *Review note:* LangGraph 1.2.14: explicit checkpoint_id => is_replaying, pending writes NOT re-applied (_loop.py:330, 766-770); Command(resume) keeps RESUME writes; invoke(None, checkpoint_id) forks (886-912). Store IDs from stream_mode='checkpoints'/aget_state, update after forks, make every node idempotent, test kill-mid-superstep and kill-at-interrupt, join stale in-process tasks before re-acquiring.
  - *Review note:* Fork writes are non-blocking (_loop.py:1262-1266) and sync durability waits only after the tick (main.py:3526): store only checkpoint IDs confirmed by aget_tuple; treat a missing stored ID as an error; prefer Command(resume) when a resume event exists; test two crashes in a row. Define revision re-entry (new thread per revision or explicit edges back to retrieval).

## M08 — Independent review, grant, execution and recovery

- [ ] **T21 Proposals, decisions, manual proposals, feedback and final grant** — Per-revision proposal IDs; expected_payload_sha256; first decision wins; author-set independence; expiry to BLOCKED_REVIEW; manual-proposal API; feedback endpoint; grant_execution final gate with UNIQUE(run_id), proposal/run binding, asset freshness and asset guard. Requirements: R023, R043, R044, R045, R046, R057, R090, R092, R093, R100, R113, R116, R120, R125. Depends on: T20, T11.
  - *Review note:* Asset guard via pg_advisory_xact_lock(tenant, asset) first in lock order; refusal 409 ASSET_ACTION_UNRESOLVED.
  - *Review note:* Revision from BLOCKED_REVIEW requires a free conversation slot (SLOT_OCCUPIED 409).
  - *Review note:* Verify R086's grant-blocking half (membership sync <=60 s).
  - *Review note:* Manual proposals must reference assets/evidence of the caller's tenant (alpha proposal for B22 -> 404, nothing written).
  - *Review note:* Refusals move the run to BLOCKED_REVIEW with reason asset_action_unresolved / asset_incident_exists.
  - *Review note:* Asset guard per AM-13 (1.3.3): refuse on any unresolved action, and on any committed incident regardless of timing unless supersedes_run_id names it; approval card shows the superseded incident.
- [ ] **T22 Attempt protocol, recovery, abort and escalation** — grant inserts INTENT; mark_sent before I/O; record_outcome; recover jobs with redispatch/abort rules; reconciliation backoff; transport-timeout rule; CONFLICT and deadlines to ESCALATED; asset guard; receipt retention. Requirements: R048, R049, R050, R051, R094, R095, R109, R110, R046, R118, R119, R125. Depends on: T21, T47.
  - *Review note:* Redispatch skips the section 13 gate via lookup_action -> mark_sent; mark_sent re-checks cancel/deadline under runs lock.
  - *Review note:* Cancellation after SENT aborts immediately; otherwise abort at dispatch deadline (<=5 min FAILED latency stated).
  - *Review note:* Operator CLI `ops resolve-escalation` -> ABANDONED_UNVERIFIED with operator_resolutions audit row.
  - *Review note:* Late destination evidence on ABANDONED_UNVERIFIED emits action.late_evidence; record_outcome never transitions terminal runs; recover jobs stay allowed.
  - *Review note:* request_abort is invoked inside create_incident after mark_sent returns cancelled/expired; allow abort after ABANDONED_UNVERIFIED (tombstone recorded as late evidence) with a bounded reconciliation job budget.

## M09 — Scenario suite and model-quality evaluation

- [ ] **T23 Development eval set, gold labels and rubric** — ~60 dev cases over the expanded corpus with gold labels; deterministic graders for schema, citations and abstention; groundedness rubric for owner labelling. Requirements: R111. Depends on: T17.
- [ ] **T24 Executable scenario suite (core cards)** — Convert the development cards whose capabilities exist after T22 into pytest scenarios asserting application and destination state; run in CI. Requirements: R097. Depends on: T22.
  - *Review note:* Update card vocabulary: DEV-018 -> ESCALATED; DEV-015 -> SUCCEEDED with note; DEV-017 time-bounded; DEV-008 lazy BLOCKED_REVIEW commits even when the decision returns 409.
  - *Review note:* Add cards for escalation, tombstone/late POST, asset guard, operator resolution, cancel-vs-mark_sent.
  - *Review note:* DEV-029 needs a fault-injectable outbox sink.
  - *Review note:* Runs locally against Postgres until T31 adds Postgres to CI.
  - *Review note:* Update evals/README (80/40 and separate-reviewer text are stale).
- [ ] **T25 Model-quality evaluation A/B/C** — Conditions per AM-50; 3 isolated trials; case-level Wilson CIs, cluster bootstrap, paired McNemar; quality-gates.json committed before the holdout run; holdout run once per release candidate. Requirements: R070, R072, R073, R074, R071, R130. Depends on: T22, T18, T23, T41.
  - *Review note:* Condition A deterministic metrics only; blind shuffled B/C groundedness labelling; ~20% re-label for intra-rater kappa; safety metrics any-trial; report ~30-point detectability floor.
  - *Review note:* Reads each run's manifest (model route, digest, prompt and corpus versions) into the eval report; conditions B and C must show identical model_route.

## M10 — Web workspace

- [ ] **T26 React workspace: conversation, evidence and approvals** — Vite + React + TS; three panels; the eight AM-40 states; safe rendering; authorized evidence viewer; approval card bound to revision/hash; manual proposal UI. Requirements: R014, R035, R052, R055, R056, R117. Depends on: T22, T11.
  - *Review note:* Include ANSWERED ('answered, no action'), CANCELLED and ABANDONED_UNVERIFIED in the state views; the reconnect assertion (state 8) lands in T27.
  - *Review note:* Add a run-state -> UI-state table: ESCALATED and ABANDONED_UNVERIFIED are not 'failed'; APPROVED and BLOCKED_REVIEW are mapped; name the three panels (Conversation+Activity, Evidence, Approvals).
- [ ] **T27 Authenticated SSE replay and revocation (+ SSE cards)** — Last-Event-ID replay; heartbeats; cursor-reset snapshot; access recheck per frame; identity change closes stream; ESCALATED runs stay live; add SSE scenario cards. Requirements: R053, R054, R097. Depends on: T26, T14.

## M11 — Observability and operating budgets

- [ ] **T28 OpenTelemetry tracing with redaction** — OTel in api, worker, mcp-read, mcp-write, incident-sim; collector + one trace backend; bounded labels; redaction of tokens, handles and evidence. Requirements: R058, R059, R060. Depends on: T22.
- [ ] **T29 Budgets and degraded operation (+ budget cards)** — Queue/model/time/retry caps; dependency outages produce templated truthful states; capacity measured on the owner's hardware; add budget scenario cards. Requirements: R061, R062, R097. Depends on: T28.

## M12 — Containers, network isolation and full CI

- [ ] **T30 Hardened images, demo profile and Docker network isolation** — Multi-stage non-root images from uv.lock; Compose test/demo profiles (one worker replica); Docker networks deny model->destination and browser->internal; docker-kill recovery demo. Requirements: R063, R064, R065, R066, R067. Depends on: T22.
  - *Review note:* Enforce one worker replica: startup advisory lock; a second worker refuses to start (tested).
  - *Review note:* Docker network tests include: mcp-read cannot reach incident-sim; mcp-write cannot reach asset-sim; worker cannot reach either sim.
- [ ] **T31 Full CI with trust separation** **[owner]** — Extend T06: PostgreSQL integration, scenario suite, image build and scan; separate trusted workflow for real-model checks run manually; pinned SHAs; least privilege. Requirements: R075. Depends on: T30, T06.

## M13 — Retained-receipt restore

- [ ] **T32 Retained-receipt restore (+ restore card)** — Restore an older app backup against the retained destination; reconcile by original action IDs; runbook with real observations; add restore scenario card. Requirements: R068, R097. Depends on: T30.

## M14 — Portfolio release

- [ ] **T33 Clean-machine reproduction and three recorded demos** — From a clean clone: setup, success, denial and recovery demos; deterministic mode shown separately. Requirements: R077. Depends on: T24, T25, T27, T29, T31, T32.
- [ ] **T34 Interviewer README, limitations and publication** **[owner]** — README for interviewers, ADR index, limitations (one worker replica, owner-authored holdout, effort ranges), MIT license, push to github.com/jschnepel/MLOps. Requirements: R078, R002. Depends on: T33.
  - *Review note:* README must carry the sentences AM-10 (escalation/abandonment risk), AM-13 (abort latency <=5 min), AM-50 (30-point detectability floor, owner-authored holdout) require, and link docs/PROJECT_HISTORY.md.
  - *Review note:* Keep docs/ARCHITECTURE.md current: it maps least privilege, routers, orchestrator and the two MCP servers to requirement IDs and demos; the README's 'What this demonstrates' table links to it.
  - *Review note:* docs/ARCHITECTURE.md uses 'Planned proof' and 'Where the code will live' until the code exists; switch to present tense only when each directory and test file is real.

## M15 — Optional v1.1+ extensions (non-blocking) *(optional, non-blocking)*

- [ ] **T35 kind/Helm with default-CNI NetworkPolicy tests** — Helm chart; kind default CNI (kube-network-policies); pod-level allow/deny and pod-kill tests. Requirements: R112. Depends on: T30.
- [ ] **T36 Paused-version upgrade and rollback rehearsal** — Route paused runs across a workflow_version bump; rollback test. Requirements: R069. Depends on: T32.
- [ ] **T37 SBOM and release provenance** — SBOM and provenance attestations for released images linked to tested inputs. Requirements: R076. Depends on: T31.
- [ ] **T38 Fenced checkpoint writes and multi-replica workers** — BaseCheckpointSaver subclass checking the run fence inside put/put_writes; enable multiple worker replicas; DEV-013 card. Requirements: R021. Depends on: T20.
- [ ] **T39 Opt-in Slack adapter** **[owner]** — Verified callbacks, identity mapping, outbox delivery, same review/execute policy. Requirements: R079. Depends on: T34.
- [ ] **T40 Approved budgeted cloud deployment** **[owner]** — Terraform/EKS only after owner cost and teardown approval. Requirements: R080. Depends on: T39.

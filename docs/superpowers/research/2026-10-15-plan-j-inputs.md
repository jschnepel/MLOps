# Plan J inputs: T15 (authenticated MCP read server, token verifier and invocation handles) — fact sheet

Prepared 2026-10-15 on branch `plan-j` at `deb6ec7` (= `plan-i`; clean tree; read-only on the repository except this
file). Facts only, no design. Citations: `SA:<line>` = `SPEC_AMENDMENTS.md`, `BS:<line>` = `BUILD_SPEC.md` (line
numbers as of `deb6ec7`); the amendments win wherever the two conflict. Repository files are cited as `path:line`;
the installed MCP SDK is cited under `.venv/Lib/site-packages/` (abbreviated `sp/`). Nothing was run against a
database, Keycloak or a service for this sheet: every fact below is read from the files, and no secret, token or
`.env` value was opened (the realm export carries `${…}` placeholders only; `reports/bootstrap/keycloak-claims.txt`
holds decoded claims, no token).

Note on line numbers: AM-15 is SA:327–358 (tool table SA:331–336, job types SA:338, job table SA:340–346, read tools
and vector mode SA:348, schema rule SA:350, envelope rules SA:351–355); AM-16 (routers) SA:360–381; AM-20.1 roles
SA:391–404 (`mcp_read` SA:400); AM-20.2 notes SA:437; AM-20.3 header SA:446, rows `resolve_invocation` SA:459,
`asset_scope` SA:460, `search_procedures_scoped` SA:461, helpers SA:474; AM-20.4 `invocation_context` SA:496;
AM-20.7 summary SA:534, item 6 SA:554–558, item 11 SA:566; AM-30 SA:568–591 (protocol SA:571–573). AM-12 fenced
writes SA:176–184, heartbeat revocation SA:196–199; AM-13 "who does what" SA:222–225. BUILD_SPEC §9 is BS:344–374
(workload identity BS:354–368), §10 BS:376–407 (intro BS:378, business tools BS:380–389, result contract BS:397–401).

---

## 1. T15 verbatim, its acceptance-matrix rows, and related rows/tasks

### 1.1 T15 (`handoff/tasks.json:665-696`)

- **id/milestone/title:** `T15`, `M05` ("MCP read and write servers and governed corpus", `tasks.json:65-74`,
  task_ids `T15`, `T47`, `T17`, `T16`, `required_for_v1: true`), "Authenticated MCP read server (mcp-read), token
  verifier and invocation handles". `status: "PLANNED"`, `external_approval_required: false`.
- **instructions:** "mcp-read on official SDK 2.x over Streamable HTTP pinned to 2026-07-28; custom TokenVerifier
  (iss, aud = MCP_READ_RESOURCE_URL, azp, exp); X-Ops-Invocation as lookup key only; resolve_invocation with azp
  binding, server binding (read handles only) and server-derived allowlist; DB role mcp_read holds EXECUTE on
  resolve_invocation, asset_scope and search_procedures_scoped only."
- **depends_on:** `["T13", "T05"]`, both `DONE` (T13 by Plan H, T05 by Plan B). T15 does **not** depend on T17
  (governed corpus) or T16 (read tools, asset-sim). `SESSION_STATE.md:12` and `:804` name Plan J = T15 as the
  earliest dependency-satisfied PLANNED task; `:804` adds "T17 is also unblocked".
- **requirement_ids:** `R025, R026, R027, R031, R085, R131`.
- **definition_of_done** (verbatim):
  1. "Independent-process client lists and calls tools."
  2. "Missing/wrong aud, browser token, replayed/expired/other-run/other-azp handle all rejected."
  3. "Protocol-version header/_meta mismatch rejected."
  4. "mcp_read cannot execute any write-path function; an execute/recover handle presented to mcp-read is rejected
     (R131 read half)."
- **review_notes** (all four, verbatim):
  1. "status=error-only-before-grant applies to authorized callers; auth failures never reveal action_id."
  2. "Allowlist checks attempt state (create_incident only with no attempt or INTENT, not cancelled, before
     deadline)."
  3. "mcp-read reads asset data via asset_scope + asset-sim, and procedures via search_procedures_scoped; it never
     has table access."
  4. "resolve_invocation derives job_type from the jobs row and server from job_type; the worker-written server
     column is a hint only."
- `handoff/BUILD_BACKLOG.md:93` repeats the instructions, requirements and dependencies.

### 1.2 Acceptance-matrix rows owned by T15 (`handoff/acceptance-matrix.json`)

Six rows list `T15` in `owning_tasks`; all six are `blocking_for_v1: true`, `implementation_status:
NOT_IMPLEMENTED_OR_NOT_TARGET_VERIFIED`, `evidence_status: NOT_RUN`, no evidence paths.

- **R025 (:449)** — M05 / mcp; "A real independent MCP client crosses the network"; expected_evidence: "An
  independent process lists and calls tools on both mcp-read and mcp-write over the network."; owners: T15 only;
  suggested_test `tests/acceptance/test_r025_a_real_independent_mcp_client_crosses_the_networ.py`.
  `handoff/ACCEPTANCE.md:31` (1.0 snapshot) words the evidence differently: "Run client/server in separate
  processes; discover and call actual protocol tools."
- **R026 (:464)** — M05 / security; "MCP rejects wrong audience or browser token passthrough"; expected_evidence:
  "Use valid token for another service; resource server rejects it without downstream forwarding."; owners: T15.
- **R027 (:479)** — M05 / security; "Invocation handle binds workload run lease and tools"; expected_evidence:
  "Replay with other workload/run/expired fence/tool; server rejects; handle absent from model/logs."; owners: T15.
- **R031 (:539)** — **M01** / mcp; "Selected SDK versions pass actual imports and contracts"; expected_evidence:
  "Install locked SDKs and run network tests; examples are not accepted based on syntax alone."; owners: `T04`,
  `T15`. `ACCEPTANCE.md:37` lists it as "R031 / **M05**". SA:710: "R031 → T04 (imports) and T15 (network)". T04 is
  `DONE` (`tasks.json:270-296`) yet the row is still `NOT_RUN`.
- **R085 (:1371)** — M05 / security, `source: SPEC_AMENDMENTS.md`; "Tool allowlist is server-derived and bound to
  the workload client"; expected_evidence: "Worker-chosen tools ignored; handle used with a different azp
  rejected."; owners: T15.
- **R131 (:2205)** — M05 / security, `source: SPEC_AMENDMENTS.md`; "The read and write MCP servers hold disjoint
  tool functions and reject each other's handles"; expected_evidence: "mcp_read can EXECUTE only
  resolve_invocation, asset_scope, search_procedures_scoped; mcp_exec only resolve_invocation, grant_execution,
  mark_sent, record_outcome, request_abort, lookup_action (pg_proc ACL test); an execute/recover handle at mcp-read
  and a read handle at mcp-write are rejected; incident-sim rejects mcp-read's token."; owners: `T15`, `T47`.
- `tests/acceptance/` does not exist; `pyproject.toml:48-51` `testpaths` lists `tests/plan_a` … `tests/plan_i` and
  `tests/e2e` (no `tests/plan_j`).

### 1.3 Tasks that depend on T15, and neighbouring rows

- **T47** (`tasks.json:697-721`, M05) depends_on `["T15", "T10"]`: "mcp-write on the same SDK/protocol pin;
  TokenVerifier with aud = MCP_WRITE_RESOURCE_URL; accepts execute/recover handles only; DB role mcp_exec holds
  EXECUTE on resolve_invocation, grant_execution, mark_sent, record_outcome, request_abort, lookup_action only; hosts
  create_incident, get_incident_receipt (recover only) and abort_incident; sole caller of incident-sim with the
  incident-sim audience and azp." Owns R030 and R131 (write half). DoD 1: "mcp_exec cannot execute any read
  function; a read handle presented to mcp-write is rejected (R131 write half)." Review note 1: "Handle server
  binding is checked inside resolve_invocation by comparing the handle's server field with session_user (mcp_read
  vs mcp_exec)." Review note 2 ends "R131 wording: named function sets (both roles share resolve_invocation)."
- **T16** (`tasks.json:743-767`, M05) depends_on `["T15", "T10", "T17"]`: "asset-sim service (trusts only the
  mcp-read workload token and forwarded tenant/asset context, applies its own tenant filter); get_asset_status,
  get_recent_alerts (absolute interval, next_cursor), search_procedures over the governed store (vector mode:
  mcp-read computes the nomic search_query embedding); fail-closed result validation." DoD: "Cross-tenant asset
  reads denied; unexpected tools and malformed results fail closed."; "asset-sim rejects worker, api and mcp-write
  tokens." Review notes: "search_procedures reads the governed store built in T17."; "search_procedures vector mode:
  mcp-read computes the nomic search_query embedding and passes it to search_procedures_scoped." Owns R028 ("Read
  tools enforce current source and asset access", :494) and R029 ("Unexpected tools and invalid results fail
  closed").
- **T17** (`tasks.json:722-742`, M05) depends_on `["T09"]` only: corpus, "idempotent ingestion; PostgreSQL full-text
  retrieval with access filtering". Owns R032, R033, R099. The governed tables (`documents`, `chunks`,
  `embeddings`) are T17's (`core/src/ops_core/privileges.py:8`).
- No other task lists T15 in `depends_on`. SA:689 (1.3.4 changes): "T15 becomes mcp-read; new **T47** builds
  mcp-write (R030, R131). T16 keeps the read tools; recovery tools move to T47. T22 depends on T47. T08 runs both
  servers."
- R030 (:524, T47): "Receipt lookup is restricted and cannot create actions". R105 (:1741, T08) is the walking
  skeleton's cross-process run (worker → mcp-read over HTTP).
- `docs/ARCHITECTURE.md:63` (the role table) already states mcp-read's target: "**no tables**; `EXECUTE` on
  `resolve_invocation`, `asset_scope`, `search_procedures_scoped` | PostgreSQL (functions), asset-sim | any
  write-path function; incident-sim". `:168-175` (§4 table): mcp-read tools `get_asset_status`,
  `get_recent_alerts`, `search_procedures`; handle types `investigate`, `resume_input`; DB role "`mcp_read` (3
  functions)". `:177`: "Protocol revision 2026-07-28 over Streamable HTTP; per-request protocol version validated
  (AM-30)." `:183-190` "Planned proof": R025 "An independent process lists and calls tools over the network";
  R026, R027 "Wrong or missing audience, browser token, replayed or expired handle rejected"; R131 "mcp-read holds
  only the three read-path functions and rejects write handles; …(both share `resolve_invocation`)".

---

## 2. Spec passages that bind T15

### 2.1 AM-30 (SA:568–591), verbatim

- SA:571: "MCP protocol revision **2026-07-28** (session-less; `io.modelcontextprotocol/protocolVersion` in `_meta`
  must match the `MCP-Protocol-Version` header)."
- SA:572: "Tests check per-request version validation and mismatch rejection, not \"negotiation\"."
- SA:573: "Imports: `from mcp.server.mcpserver import MCPServer, Context` and `from mcp import Client`."
- Versions table: "mcp | 2.3.0 (pulls `mcp-types==2.3.0`, `httpx2`)"; "Keycloak | **26.8.x** (pinned image
  digest)". AM-00 (SA:36): "**§10:** \"negotiation\": replaced by AM-30. The four tools become six (AM-15)."

### 2.2 AM-20.7 items 6 and 11 (SA:534, SA:554–558, SA:566), verbatim

- SA:534 (summary): "…**MCP token verification** with `MCP_RESOURCE_URL` audiences and a custom `TokenVerifier`;
  … **`X-Ops-Invocation` is a lookup key only**."
- SA:555: "Keycloak \"Hardcoded audience\" mappers set `aud` to the **resource URLs** of mcp-read
  (`MCP_READ_RESOURCE_URL`) and mcp-write (`MCP_WRITE_RESOURCE_URL`) and to `incident-sim`; each is a parameter, not
  a hard-coded container name. asset-sim trusts only the mcp-read workload token and the tenant/asset context it
  forwards, and applies its own tenant filter; incident-sim trusts only mcp-write."
- SA:556: "T05 fixes `KC_HOSTNAME`, so that `iss` is identical for host and container callers."
- SA:557: "Both MCP servers use a custom `TokenVerifier` that checks iss, aud ∋ its own resource URL, azp ∈ its
  allowed workload clients, and exp."
- SA:558: "Tests cover a missing `aud`, a wrong `aud`, and a browser token."
- SA:566: "**`X-Ops-Invocation` is a capability lookup key only.** It is never trusted as identity and never logged.
  The SDK warns that headers are client-supplied."
- AM-00 (SA:34): "**§9:** the `ops-mcp` audience and \"distinct service scope\" wording: replaced by AM-20.6."
  (AM-20.6 is the test clock, SA:526–530; the audience text is AM-20.7 item 6.)

### 2.3 AM-15 (SA:327–358): tools, job types, envelope

- SA:333: "| `get_asset_status`, `get_recent_alerts` (absolute interval, `next_cursor`), `search_procedures` |
  **mcp-read** | `investigate` and `resume_input` jobs (read handles) |".
- SA:338: "Every job has exactly one `type`. Allowed tools are derived from type plus run state plus attempt state.
  **A handle is bound to one server:** `investigate`/`resume_input` handles are accepted only by mcp-read;
  `execute`/`recover` handles only by mcp-write (R131)."
- SA:342: `investigate` | "API at admission and after a revision" | "Retrieval, drafting, freezing" | read tools |
  "QUEUED, RETRIEVING, DRAFTING". SA:343: `resume_input` | "API with a clarification reply" | "Resume after a
  clarification" | read tools | "AWAITING_INPUT → QUEUED". SA:344: `execute` | … | `create_incident` | "APPROVED,
  EXECUTING (attempt absent or INTENT)". SA:345: `recover` | … | "`create_incident` (INTENT only),
  `get_incident_receipt`, `abort_incident`" | "EXECUTING, OUTCOME_UNKNOWN, ESCALATED, ABANDONED_UNVERIFIED".
- SA:348: "Read tools are `get_asset_status`, `get_recent_alerts` and `search_procedures`. … No job is created by
  either MCP server. For `search_procedures` in vector mode, mcp-read computes the query embedding with
  `nomic-embed-text` (`search_query:` prefix) and passes it to `search_procedures_scoped` [R6]."
- SA:350: "Every tool has an input JSON Schema in `schemas/tools/`. Arguments that supply a role, tenant, actor,
  approval or destination are rejected."
- SA:351–355: "**The envelope must agree with the data:** `status=ok` only for a read with data, or `SUCCEEDED`;
  `status=outcome` for `UNKNOWN` / `CONFLICT` / `FAILED_NO_COMMIT`, with `data.action_id` required; for an
  **authenticated, authorized** caller, `status=error` only before any grant exists; authentication and
  authorization failures always return a plain safe error, never with an `action_id`."
- SA:357: "The old `unknown` envelope status is removed."
- AM-13 (SA:224): "mcp-read cannot reach incident-sim and holds no write-path function." SA:240 (recovery table): the `create_incident`
  rule "allowed only when there is no attempt, or the attempt is INTENT, not cancelled and before the deadline"
  (the source of T15 review note 2).

### 2.4 AM-20.1/20.2/20.3/20.4 rows for mcp-read

- SA:400: "| `mcp_read` | yes | mcp-read; read-path functions only |". SA:106 (AM-02): "`mcp_read` and `mcp_exec`
  (functions only)".
- SA:410/437: the `mcp_read` / `mcp_exec` / `operator` column is "—" on every table; "`mcp_read`, `mcp_exec` and
  `operator` have **no table grants**; the right-hand column is only for `test_harness`."
- SA:446: "All functions: `SECURITY DEFINER`, owner `app_definer`, `SET search_path = app, pg_temp`, `SET
  app.tenant_id = ''` as a function attribute. Each migration that creates one runs, in the same transaction,
  `REVOKE ALL ON FUNCTION … FROM PUBLIC` and then `GRANT EXECUTE … TO <exactly the callers listed below>` [R6-H2]."
- SA:459: "| `resolve_invocation(raw_handle, client_azp)` | `mcp_read`, `mcp_exec` | the header value and the
  token's `azp` | `invocation_context` FOR SHARE → `run_lease` FOR SHARE | Hashes the handle inside; checks azp
  binding, **that the handle's server matches the calling role** (read handles only for `mcp_read`,
  execute/recover handles only for `mcp_exec`), expiry, current run fence; returns `{run_id, tenant_id, job_type,
  run_state, attempt_state, allowed_tools}` with the allowlist derived per AM-15 | none |".
- SA:460: "| `asset_scope(raw_handle)` | `mcp_read` | handle | as above | Returns the run's `tenant_id`,
  `asset_id`, `[start_at, end_at)` for forwarding to asset-sim | none |".
- SA:461: "| `search_procedures_scoped(raw_handle, query, query_embedding vector(768) NULL, asset_type, limit, mode)`
  | `mcp_read` | handle, text query, optional embedding computed by mcp-read with the `search_query:` prefix | as
  above | Lexical (`mode=lexical`) or exact vector (`mode=vector`, requires the embedding) search over approved,
  effective, tenant-permitted chunks; returns IDs, versions, section, hash, excerpt | none |".
- SA:474: "Internal helpers (`_canonicalize`, `_asset_guard`, `_allowlist`) are not granted to any role."
- SA:496: "`invocation_context(handle_sha256 PK, run_id, job_id, server ∈ {read, write}, fence, azp, expires_at,
  revoked_at)`. `resolve_invocation` derives `job_type` from the referenced `jobs` row and `server` from that type
  (read for `investigate`/`resume_input`, write for `execute`/`recover`); it never trusts the worker-written
  `server` column alone [R7]."
- SA:523: `invocation_context` and `run_lease` have no RLS; "their grants (AM-20.2) are the control".
- AM-12 SA:176–184: "every worker or MCP mutation for a run **first** executes: `SELECT 1 FROM run_lease WHERE
  run_id = :r AND fence = :f AND lease_until > app.current_time() FOR SHARE`. A missing row aborts the
  transaction." SA:196–199: when renewal fails, the worker "cancels in-flight model and tool calls; revokes its
  invocation handles; exits the run."

### 2.5 AM-16 and ADR-0003 (the mcp-read / mcp-write split)

- AM-16 (SA:360–381) is the routers section; the split itself is in the 1.3.4 note (SA:3: "the MCP server split into
  `mcp-read` and `mcp-write`") and in `docs/adr/ADR-0003-routers-and-read-write-mcp-split.md`.
- ADR-0003:18, verbatim: "**The MCP server splits into `mcp-read` and `mcp-write`.** Each has its own Keycloak
  client, token audience, database role and function set. `mcp_read` can execute only `resolve_invocation`,
  `asset_scope` and `search_procedures_scoped`; `mcp_exec` can execute only the write-path functions. Capability
  handles are bound to one server, so a read handle presented to mcp-write is rejected and vice versa (R131). Only
  mcp-write can reach incident-sim; only mcp-read can reach asset-sim." ADR-0003:23: "T15 builds mcp-read; the new
  T47 builds mcp-write." ADR-0003:24: "The worker holds two handle types and two base URLs. The walking skeleton (T08)
  runs both servers from the start, so the split is never retrofitted."
- AM-01 (SA:76): "| `mcp-read/` | Authenticated MCP server for read tools only (asset status, alerts, procedure
  search); DB role `mcp_read` |"; AM-01's opening: each process directory has "its own `pyproject.toml`,
  `Dockerfile`, `tests/` and `README.md`".

### 2.6 BUILD_SPEC §9 (workload identity, invocation handle), verbatim where it binds

- BS:356: "Use audience-specific workload access tokens issued for `ops-mcp`, validated by the MCP host. Do not pass
  browser access tokens to an audience for which they were not issued. MCP security guidance warns against token
  passthrough." (The `ops-mcp` audience is superseded, SA:34.)
- BS:360: "The trusted worker leases a job and creates an unguessable 256-bit opaque invocation handle. Store only
  its hash, bound to validated workload client ID, run ID, job ID, current fence, allowed tool names and a maximum
  60-second expiry. Refresh it only while the lease is current." (AM-00 SA:35: "the handle's \"allowed tool names\":
  replaced by AM-20.2".)
- BS:361: "Send the secret handle as `X-Ops-Invocation` alongside the workload access token. It is not an MCP tool
  argument, a model input, a logged field, or an authorization assertion supplied by the user."
- BS:362: "The MCP server validates the workload token, resolves the handle using a constant-time hash comparison or
  indexed cryptographic hash lookup, checks workload binding/expiry/current lease fence, then loads current
  requester/tenant policy from the stored run. Ignore or reject tool arguments that attempt to supply role, tenant,
  actor, approval or destination authority."
- BS:363: "Tool allowlists are server-side. A read invocation cannot call a write tool. …"
- BS:364: "Rotate/revoke handles on lease loss, cancellation, policy change and completion. A handle captured by
  another workload, another run, or an expired worker fails. Use TLS outside localhost and never forward the handle
  to the destination."
- BS:366: "This handle is a project-specific capability bound to authenticated workload identity, **not** a
  substitute for standards-compliant MCP HTTP authorization or a claim of OAuth delegation. Implement the MCP
  resource-server requirements of the pinned protocol separately. Record the threat model and real independent
  client tests before enabling the remote server."
- BS:374: "Threat tests must exercise … unexpected tool registration, token audience confusion, invocation-handle
  replay, stale grants, …".
- BS:350 (browser identity): "Local development may use an explicitly localhost-only HTTP exception; cluster/cloud
  profiles require TLS and cannot accept the development exception."
- BS:233 (§6 table): "| invocation_context | hashed random handle, workload client, run_id, job_id, fence, allowed
  tools, expiry; revoked on lease loss |" (the allowed-tools field superseded, SA:45).

### 2.7 BUILD_SPEC §10 (tool contracts and the structured tool-result contract)

- BS:378: "The official MCP server exposes typed tool contracts and safe structured results over internal Streamable
  HTTP. Pin supported protocol/SDK versions and reject unexpected negotiation/schema changes. Host lifespan management
  must follow the selected SDK. Use a real remote client in integration tests; an in-process call is not sufficient."
- BS:384–386 (business tools): `get_asset_status` | `asset_id` | "Permitted synthetic status, asset revision,
  observed_at, data_source; no equipment mutation"; `get_recent_alerts` | "`asset_id`, `start_at`, `end_at`, bounded
  `limit`" | "Fixed half-open interval, ordered alerts with timestamps/revisions; `truncated` flag and next cursor
  where needed"; `search_procedures` | "bounded `query`, optional `asset_type`, `limit`" | "Only approved,
  effective, currently permitted chunks; IDs, versions, section, source hash, excerpt, retrieval mode".
- BS:395: "A model-facing tool adapter, if added, receives only permitted read tools. … Do not expose a generic
  `send_message`, `execute_sql`, `run_shell`, `fetch_url`, \"approve\" or role-management tool."
- BS:399: "Use the target `tool_result` schema. Carry `tool_name`, request correlation ID, `status`, bounded typed
  `data` for the known tool, safe `error` when present, observed timestamp and truncation metadata. Validate
  tool-specific nested schemas, not just the envelope. Check both transport errors and the SDK's tool-error flags; a
  protocol-success response can still represent application failure. Preserve error classification and never feed
  raw stack traces or credentials to the model."
- BS:401: "The server derives tenant and action context from trusted records. … Server-side role rechecks happen at
  read and write boundaries, not only during tool discovery."
- BS:589 (§19): "MCP network tests: independent process/client, actual negotiation/list/call, workload audience,
  invocation scope/replay, malformed results, server policy, no direct bypass." BS:706 (§25): "M05 — Remote MCP |
  Authenticated server/client, invocation context, four business tools plus restricted reconciliation | Real
  transport discovery/calls, audience/replay/scope errors, no direct bypass".
- BS:625: "A local-only debug port must bind to 127.0.0.1, not every host interface."

---

## 3. The tree as it is (branch `plan-j`, `deb6ec7`)

### 3.1 Every "T15" debt line outside uv.lock, reference/, docs/reviews, docs/superpowers (`git grep -n T15`)

Code and schemas:

| Where | Text (verbatim) | What it asks for |
|---|---|---|
| `core/src/ops_core/jobs.py:54-56` | "TODO(T15): AM-15 derives the allowlist from the job type *plus the run state and the attempt state* (for example `create_incident` only while the attempt is absent or INTENT). This rule holds the job-type dimension; T15's `resolve_invocation` adds the run-state and attempt-state filters at call time." | run-state and attempt-state filters in resolution |
| `core/src/ops_core/routing.py:362` | "TODO(T15): mcp-read, the caller of `search_procedures_scoped`, translates `vector_exact` to `mode=vector`." | the mode translation (erratum 3) |
| `scripts/build_schemas.py:856` | `"mode": {"enum": ["lexical", "vector_exact"]},  # ruling 3; mcp-read maps vector_exact (TODO(T15))` | same |
| `migrations/app/versions/0001_walking_skeleton.py:8` | "(raw, debt → T09/T15 replaces it by `handle_sha256`)" | already done by revision 0002 (§3.6) |
| `tests/plan_c/test_schema_conformance.py:45` | "envelopes are built by the MCP servers (T15/T47); the data shapes are ActionOutcome" | skip reason |
| `tests/plan_c/test_schema_conformance.py:58` | "tool input schema: enforced by the MCP server's argument validation (T15)" | skip reason |

Status documents (verbatim):

- `SESSION_STATE.md:12`: "Next is Plan J = T15 (mcp-read, the earliest dependency-satisfied PLANNED task in
  `handoff/tasks.json`, unblocked by T13 …)". `:804`: "…write Plan J for T15 (mcp-read, …; T17 is also unblocked)."
- `:125` (1.3.4 summary): "MCP server split into `mcp-read` (role `mcp_read`, 3 functions) and `mcp-write` (role
  `mcp_exec`, 6 functions) with disjoint handles and audiences (R131); T15 = mcp-read, new T47 = mcp-write".
- `:165` (Plan D shortcuts): "…lexical `search_procedures` from fixtures, no asset tools (T16/T17); … handles not
  revoked (T15); …".
- `:172` (Plan D open items): "mcp-read truncates an excerpt silently (bounded by the contract) and answers every
  handle rejection with the same `INVALID_HANDLE` (T15);".
- `:199` (Plan E open items): "the eleven definer functions without a caller arrive with T11, T13, T15-T17, T21 and
  T22".
- Walking-skeleton debt: `:553` "raw handle not hashed → T09/T15;"; `:556` "`search_procedures` is served lexically
  from `data/handoff-fixtures/` inside mcp-read (no governed store, no `asset_scope`) → T17; `get_asset_status` /
  `get_recent_alerts` and asset-sim are absent → T16;"; `:562` "handles are not revoked at job end and resolution
  ignores run and attempt state → T15 (the raw, unhashed handle is already on the list above);". `:569` ("Not
  debt (must be real in T08)"): "…aud/azp/iss checks in mcp-read, mcp-write and incident-sim; …".
- Plan E debt: `:574` "the definer functions without a caller today arrive with their owners: … `asset_scope`,
  `search_procedures_scoped` → T15/T16/T17; …".
- Plan E open items `:203`: "untested branches -> T13/T22: … a write handle at mcp_read;" (Plan H re-homed the
  untested definer branches to T22, `:400-401`).
- Plan H debt and Plan I debt lines contain no line owned by T15. Plan I debt `:716-717`: "the dev database stays at
  revision 0005 … until then the API, the sweeper, the worker and mcp-write refuse to start on it" (mcp-read is not
  in that list; §3.4).
- What became of the walking-skeleton T15 lines: the hash (`:553`) was done by Plan E ruling 21 (revision 0002,
  §3.6); revocation at job end (`:562`, first half) was done by Plan H: `persistence.release_lease` revokes the
  fence's handles in the job's final unit (`core/src/ops_core/persistence.py:776`). "Resolution ignores run and
  attempt state" (`:562`, second half) is still true (§3.5).

### 3.2 `mcp-read/` today (269 + 111 + 18 + 16 + 6 + 3 lines)

Directory: `README.md`, `pyproject.toml`, `src/ops_mcp_read/{__init__,__main__,procedures,server}.py`. No
`Dockerfile` and no `tests/` (AM-01 asks for both; the Plan D open item "per-service `tests/` directories (T30)",
`SESSION_STATE.md:169`). `pyproject.toml:6`: `dependencies = ["ops-core", "mcp==2.3.0", "uvicorn>=0.54,<1"]`.

`mcp-read/src/ops_mcp_read/server.py`:

- Docstring `:1-8`: "Every call must present the worker's workload token (aud = this server's resource URL, azp =
  ops-worker) and an `X-Ops-Invocation` handle minted for an `investigate` job; the handle, not the token, says which
  run and tenant the call is for (BUILD_SPEC §9). The tool's argument model forbids extra keys … One tool in T08;
  asset tools arrive with T16."
- SDK imports (`:23-27`): `get_access_token` (`mcp.server.auth.middleware.auth_context`), `AccessToken`
  (`mcp.server.auth.provider`), `AuthSettings` (`mcp.server.auth.settings`), `Context, MCPServer`
  (`mcp.server.mcpserver`), `Tool` (`mcp.server.mcpserver.tools.base`). From core (`:28-31`): `persistence`,
  `redaction`, `settings`, `ops_core.jobs.Tool as ToolName`, `Role`, and `Principal, TokenRejected, TokenVerifier`
  from `ops_core.tokens`.
- `ToolResult` TypedDict (`:42-51`): `tool_name, request_id, status, observed_at, truncated, data, error`.
  `tool_error` (`:59-61`) always `retryable: False`. `envelope` (`:64-74`): `status` is `"error"` when an error is
  given, else `"ok"`; `request_id` a fresh `uuid4`; `truncated` always `False`.
- `search_response` (`:77-100`): picks `corpora[tenant_id]`; `corpus_version` falls back to the first corpus's
  version (or `"none"`) when the tenant has no corpus (`:82-83`); results carry `evidence_id, document_id, version,
  section, content_sha256, excerpt` (first `EXCERPT_CHARS` = 500 characters, `procedures.py:21`), `effective_from`,
  `retrieved_at`; `retrieval_mode` is always `"lexical"` (`:99`).
- **How the token is verified today.** `Verifier` Protocol (`:103-111`: `ready`, `load_keys`, `verify_async`).
  `McpVerifier` (`:114-135`) adapts it to the SDK's `TokenVerifier` protocol: `verify_token` returns `None` (→ the
  SDK's 401) on `TokenRejected` (`:125-126`), else an `AccessToken(token, client_id=principal.azp, scopes=[],
  expires_at=principal.expires_at, resource=self._resource, subject=principal.subject,
  claims=dict(principal.claims))` (`:127-135`); `resource` is the configured URL, stamped whatever `aud` held.
  `production_app` (`:244-252`) builds `TokenVerifier(issuer=kc.issuer, audience=urls.mcp_read_resource,
  allowed_azp=frozenset({"ops-worker"}), jwks_url=kc.jwks_url)` (`:248-250`).
- `strict_tool` (`:138-152`): subclasses the SDK-generated argument model with `ConfigDict(extra="forbid",
  strict=True)` and regenerates `tool.parameters`.
- **Registered tools:** one. `search_procedures(query: str[1..500], limit: int[1..8], mode: Literal["lexical",
  "vector_exact"], ctx: Context)` (`:167-172`); no `asset_type` parameter (the input schema has an optional one,
  `schemas/tools/search_procedures.input.schema.json:14-18`). `MCPServer(name="mcp-read", auth=AuthSettings(
  issuer_url=…, resource_server_url=…, validate_token_resource=False), token_verifier=McpVerifier(…),
  tools=[strict_tool(search_procedures)])` (`:191-198`).
- **How the handle is read and resolved:** `token = get_access_token()`; `handle = (ctx.headers or
  {}).get("x-ops-invocation")` (`:174-175`, "header names arrive lower-case"). No token, no handle or no session →
  `envelope(error=INVALID_HANDLE "missing invocation handle")` (`:176-177`). Otherwise one unit
  (`state.session.unit()`, no tenant) calls `persistence.resolve_invocation(conn, handle=handle,
  azp=token.client_id, tool=ToolName.SEARCH_PROCEDURES)` (`:179-182`); `HandleRejected` →
  `envelope(error=INVALID_HANDLE, str(exc))` = "invocation handle rejected" (`:183-184`). `mode != "lexical"` →
  `UNSUPPORTED_MODE` "vector_exact arrives with T17" (`:185-186`) — checked **after** resolution. The search then
  runs on the in-memory fixture corpus for `invocation.tenant_id` (`:187-189`), outside the resolving unit (the unit
  committed at `:182`).
- **Protocol version handling:** none in mcp-read's code. `server.streamable_http_app(streamable_http_path="/mcp",
  stateless_http=True, json_response=True)` (`:203`) passes no `host` or `transport_security`; the SDK's era routing
  and per-request ladder apply (§3.12).
- **Lifespan and connection** (`:205-223`): one autocommit connection as `Role.MCP_READ`
  (`persistence.connect(settings.app_postgres(Role.MCP_READ))`, `:209`), `assert_clock_profile` (`:211`), closed on
  a failed start (`:212-214`); `persistence.Session(conn)` (one connection, one unit at a time,
  `persistence.py:138-158`); keys loaded inside the `try` (`:218-219`); the mounted MCP app's lifespan forwarded
  (`:220-221`). **No `assert_relation` guard** (the API `app.py:179`, the worker `main.py:148` and mcp-write
  `server.py:226` assert `app.model_permit`, revision 0007; the sweeper `main.py:241` asserts `app.outbox`, 0008).
- **Health routes** (`:225-241`): `/health/live` → 200 `{"status": "live"}`; `/health/ready` → 503 unless the
  session exists, the keys are loaded and `session.ping()` (`SELECT 1`) succeeds. Routes: health first, then
  `Mount("/", app=mcp_app)`.
- `serve_app` (`:255-262`): `uvicorn.Server(Config(app, host="127.0.0.1", port=port, …))`, selector loop on Windows
  (Plan D ruling 23). `serve` (`:265-269`): `redaction.install()` first, port `OPS_MCP_READ_PORT` (default 8081).

`mcp-read/src/ops_mcp_read/procedures.py`:

- Docstring `:1-10`: "Lexical procedure search over the authored fixtures (T08; debt → T17: the governed store,
  `search_procedures_scoped` and `vector_exact`)." The corpus is built per tenant from
  `data/handoff-fixtures/catalog.json`, "only that tenant's documents … and only `approved` versions" (`:82`);
  per-section hash from `meta.json` (`:79`, `:92`); ranking is term overlap with an `evidence_id` tie-break
  (`:99-105`). `load_corpora` (`:108-111`) keys corpora by tenant UUID from `meta.json`'s `tenants`.

`mcp-read/README.md`: "## Trusts: Workload token with its audience; definer functions `resolve_invocation`,
`asset_scope`, `search_procedures_scoped`" (`:8-9`); "## Never: Any write-path function; incident-sim" (`:11-12`);
"## Runs (T08)" (`:14-18`): "`python -m ops_mcp_read` on 127.0.0.1:8081 (`OPS_MCP_READ_PORT`), Streamable HTTP at
`/mcp`, protocol 2026-07-28, stateless. Verifies `aud ∋ MCP_READ_RESOURCE_URL`, `azp == ops-worker`; resolves
`X-Ops-Invocation` for `investigate` jobs. One tool, `search_procedures` (lexical, fixture-backed until T17)."

### 3.3 mcp-write's verifier and handle code, for comparison (`mcp-write/src/ops_mcp_write/server.py`, 284 lines)

- `:39-40`: "Duplicated from mcp-read on purpose: members never import each other (ADR-0001, test_layout); the shape
  is pinned by the tool-result contract tests in both packages." `ToolResult`, `stamp`, `envelope`, `Verifier`,
  `McpVerifier` (`:102-124`) and `strict_tool` (`:127-141`) are line-for-line the same as mcp-read's (mcp-write's
  `Verifier` methods carry docstrings).
- `create_incident` (`:175-201`): same header read (`:177-178`), same missing-handle envelope (`:179-180`); calls
  `persistence.resolve_invocation(…, tool=ToolName.CREATE_INCIDENT)` in its own unit first ("binds server, azp,
  expiry and the tool allowlist before any work (SA:459)", `:182-185`), then `execution.create_incident(deps,
  handle=handle, …)` (`:186`), which passes the raw handle to `grant_execution`/`lookup_action`/`mark_sent`/
  `record_outcome`. Error mapping: `HandleRejected` → `INVALID_HANDLE`; `Refused` → `GRANT_REFUSED` or retryable
  `GRANT_DEFERRED` for `MEMBERSHIP_STALE` (`:65-69`); `NotFound`, `VersionConflict` (`STALE_RUN`), `HashMismatch`
  (`:187-198`); `AuthorityViolation` deliberately unmapped (`:199-200`). `outcome_envelope` (`:154-160`) sets
  `status="outcome"` for every non-SUCCEEDED outcome.
- Lifespan (`:218-248`): `Role.MCP_EXEC`, `assert_clock_profile`, **`assert_relation(conn, "app.model_permit")`**
  ("Revision 0007: mark_sent and record_outcome take the raw handle (T13)", `:225-226`), an `httpx2.AsyncClient`, and
  a `WorkloadTokenSource(client_id="ops-mcp-write", client_secret=settings.read_secret(
  "kc_client_secret_ops_mcp_write"))` for incident-sim (`:235-239`).
- `production_app` (`:269-277`): `TokenVerifier(audience=urls.mcp_write_resource,
  allowed_azp=frozenset({"ops-worker"}), …)`. Port `OPS_MCP_WRITE_PORT` default 8082 (`:280-284`).
- mcp-write's definers other than `resolve_invocation` do not take the token's azp: `grant_execution`,
  `lookup_action`, `mark_sent` and `record_outcome` call `app._resolve_handle(p_raw_handle, 'ops-worker', 'write')`
  with a literal azp (`migrations/app/versions/0004_write_path_functions.py:268`, `:343`;
  `0005_sessions_login_logout.py:96`; `0007_leases_fences.py:195`, `:242`).

### 3.4 `core/src/ops_core/tokens.py` (247 lines): the verifier helpers

- Docstring `:1-9`: "One class, configured per server with its issuer, its own audience and the workload clients it
  accepts as `azp`, so every server applies SA:557's checks the same way …. PyJWT checks the signature, `exp`, `iss`
  and `aud`; `azp` is checked here because PyJWT has no option for it. Algorithms are pinned to RS256 …".
- Exceptions: `TokenRejected` (`:29-30`), `UnknownSigningKey` (`:33-34`), `SigningKeysUnavailable` (`:37-40`),
  `WrongAudience(TokenRejected)` (`:43-45`: "Servers that answer 401 for every TokenRejected keep doing so;
  incident-sim turns this one into 403 (T10 DoD 2)").
- `Principal(subject, azp, audiences, expires_at, claims)` (`:48-55`; `claims` is `repr=False`).
- `bearer_token` (`:58-66`): exactly `"Bearer"` + one space + a whitespace-free token. The MCP servers do not call
  it; the SDK's `BearerAuthBackend` parses the header itself (case-insensitive `"bearer "` prefix,
  `sp/mcp/server/auth/middleware/bearer_auth.py:60-63`).
- `TokenVerifier.__init__` (`:78-105`): keyword-only `issuer, audience, allowed_azp, jwks_url`,
  `algorithms=("RS256",)`, `required_claims=("exp", "iss", "aud", "sub")` (always including exp/iss/aud, `:99`),
  `require_azp=True`, `typ=None`. One audience string per verifier.
- `install_keys` (`:111-126`) keeps only `use == "sig"` keys of the pinned algorithms. `verify` (`:137-183`): kid
  lookup → `UnknownSigningKey`; `jwt.decode(…, algorithms, audience=self._audience, issuer=self._issuer,
  options={"require": …})` (`:151-158`), so `aud` must **contain** the audience (PyJWT list semantics);
  `InvalidAudienceError` → `WrongAudience` (`:159-160`); other `InvalidTokenError` (expiry, `nbf`, issuer,
  signature) → `TokenRejected` naming the class (`:161-163`); `typ` compared only when configured (`:164-165`); empty
  `sub` refused (`:166-168`); `azp` must be a string in `allowed_azp` else `WrongAudience` (`:169-172`).
- `verify_async` (`:185-196`): one JWKS refresh on an unknown kid, single-flight, 60 s cooldown (`REFRESH_COOLDOWN`,
  `:26`). `WorkloadTokenSource` (`:210-247`): client-credentials, cached, refreshed 30 s before expiry, `invalidate`.

### 3.5 Handle minting, resolution and the allowlist in core

- `persistence.mint_handle` (`core/src/ops_core/persistence.py:893-918`): `secrets.token_urlsafe(32)`; inserts
  `handle_hash(handle)`, `run_id`, `job_id`, `server`, `azp`, the lease's `fence`, `expires_at =
  app.current_time() + make_interval(secs => ttl_seconds)` (default 60) only from a live lease at exactly that fence
  (`rowcount != 1` → `LeaseLost`). Docstring: "BS:558's other bound, the current lease, is enforced where the handle
  is used: `app._resolve_handle` refuses it once its fence is not the lease's or the lease has lapsed. Capping
  `expires_at` at mint time would freeze the lease end …".
- `handle_hash` (`:382-384`) = `sha256_hex(handle.encode("utf-8"))`, equal to the SQL `encode(sha256(convert_to(…,
  'UTF8')), 'hex')`.
- `Invocation` (`:363-372`): `run_id, job_id, job_type, tenant_id, conversation_id, run_state, attempt_state`.
- `allowed_tool(job_type, tool)` (`:375-379`): "The AM-15 allowlist stays in Python (ruling 21); the function has
  already bound server, azp and expiry." It checks `tool in JOB_RULES[job_type].allowed_tools` only; on refusal it
  logs "tool %s is not allowed for job type %s" ("never the handle") and raises `HandleRejected("invocation handle
  rejected")`. It reads neither `run_state` nor `attempt_state`.
- `resolve_invocation` (`:387-403`): `SELECT * FROM app.resolve_invocation(%s, %s)` with `(handle, azp)`; no row →
  `HandleRejected`; then `allowed_tool`; returns `Invocation`.
- `translate` (`:84-94`): SQLSTATE `OC008` → `HandleRejected("invocation handle rejected")`, "one message for every
  refusal (SA:357)".
- `ops_core.jobs` (`core/src/ops_core/jobs.py`): `Tool` (six names, `:19-27`), `Server` (`read`/`write`, `:30-34`),
  `JobType` (eight, `:37-47`), `JobRule` (`:50-64`, with the TODO(T15) docstring `:54-56`), `JOB_RULES` (`:69-106`):
  `INVESTIGATE` → `_READ` tools, run states `{QUEUED, RETRIEVING, DRAFTING}`, `Server.READ`; `RESUME_INPUT` →
  `_READ`, `{AWAITING_INPUT, QUEUED}`, `Server.READ`; `EXECUTE` → `{CREATE_INCIDENT}`, `{APPROVED, EXECUTING}`,
  `Server.WRITE`; `RECOVER` → the three write tools, `{EXECUTING, OUTCOME_UNKNOWN, ESCALATED,
  ABANDONED_UNVERIFIED}`, `Server.WRITE`. `JOB_RULES[…].run_states` is not consulted by `allowed_tool`.

### 3.6 The definer bodies: `resolve_invocation` and `_resolve_handle` (after Plan H)

- `invocation_context` shape: revision 0001 created it with a raw `handle text PRIMARY KEY`, `server text NOT NULL
  CHECK (server IN ('read', 'write'))`, `fence integer`, `azp text NOT NULL`, `expires_at`, `revoked_at`,
  `created_at` (`0001_walking_skeleton.py:121-131`); revision 0002 truncated it, dropped `handle`, added
  `handle_sha256 text PRIMARY KEY` and made `fence bigint` (`0002_roles_grants_rls.py:304-306`). Grants
  (`0002:107`): `worker` INSERT, `sweeper` SELECT, `app_definer` `sel, upd(revoked_at)`; no RLS (SA:523).
- `HANDLE_COLUMNS` (`0004_write_path_functions.py:29-31`): `run_id uuid, job_id uuid, job_type text, tenant_id uuid,
  conversation_id uuid, run_state text, attempt_state text` — no `allowed_tools` (erratum 19).
- `app.resolve_invocation(p_raw_handle text, p_client_azp text)` (`0004:238-251`, never re-created since):
  `_authority('resolve_invocation', ARRAY['mcp_read', 'mcp_exec'])` (`:243`); "The calling role picks the server
  (SA:459): mcp_read sees read handles only, mcp_exec write handles only." (`:244`); returns
  `_resolve_handle(p_raw_handle, p_client_azp, CASE WHEN session_user::text = 'mcp_read' THEN 'read' ELSE 'write'
  END)` (`:245-247`).
- `app._resolve_handle(text, text, text)` as revision 0007 re-created it (`0007_leases_fences.py:122-171`):
  1. hash lookup in `invocation_context` (no lock; erratum 53); not found → `OC008` (`:137-141`);
  2. "the run's lease row FOR SHARE is the first lock (SA:188)" (`:142-145`);
  3. refuse (`OC008`) if no lease row, `fence <> handle.fence`, `lease_until <= app.current_time()`, `revoked_at IS
     NOT NULL`, `expires_at <= app.current_time()`, or `ctx.azp <> p_client_azp` (`:146-149`);
  4. `app._tenant_of_run(run_id)`; `jobs.type` read by `ctx.job_id` (`:150-151`);
  5. server derived from the job type (`investigate`/`resume_input` → read, `execute`/`recover` → write, else NULL),
     refuse if NULL, if it differs from the caller's server, **or** if the stored `server` column differs
     (`:152-158`);
  6. the `runs` row (`:159-162`); the latest attempt state through `execution_grant` + `_latest_attempt`
     (`:163-164`); return one row (`:165-167`).
  Not checked in the body: the job's `done_at`, that `jobs.run_id` equals the handle's `run_id`, the run's state
  against the job type's run states, or the attempt state against a tool (the caller's `allowed_tool` checks the
  tool against the job type only). Every refusal is the same `OC008 handle_rejected`.
- 0007 docstring (`:14-17`): "The handle functions check the fence in one place, `_resolve_handle`: the run's lease
  row FOR SHARE, then the handle's fence against the lease's and the lease's expiry, compared after the lock … .
  `resolve_invocation`, `lookup_action` and `grant_execution` already call it; `mark_sent` and `record_outcome` now
  take the raw handle so they call it too (erratum 48)." 0007's downgrade restores 0004's `_resolve_handle`
  (`:412`), whose body (`0004:65-104`) checks hash, revocation, expiry and azp but no lease or fence.
- Lock order (`core/src/ops_core/locking.py:29-50`): `invocation_context` sits after `operator_resolutions` and
  before `run_state_history`; `OBSERVED_UNITS` `:71`: `"mcp resolve_invocation and lookup_action": ("run_lease",)`.
- **`asset_scope` and `search_procedures_scoped` do not exist.** `git grep` finds them only in prose: README
  (`mcp-read/README.md:9`), `docs/ARCHITECTURE.md:63`, the Plan E debt (`SESSION_STATE.md:574`), plans and
  spec. They are absent from `privileges.DEFINER_FUNCTIONS` and from every revision. The governed tables
  (`documents`, `chunks`, `embeddings`) do not exist and no revision runs `CREATE EXTENSION` (pgvector's image is
  pinned in `compose.yaml:9`, the extension is not created). `runs` carries `asset_id text NOT NULL`, `start_at`,
  `end_at` with `CHECK (start_at < end_at)` (`0001:72-90`), the inputs `asset_scope` would return.
- Plan E ruling 1 (`docs/superpowers/plans/2026-10-08-first-slice-e-roles-rls-definers.md:44`): "`asset_scope`,
  `search_procedures_scoped` (T15–T17) … arrive with their owning tasks, each in its own revision following the
  pattern set here …. Stub bodies that raise `not_implemented` were rejected: they would carry EXECUTE grants that
  mislead R124's enumeration and test nothing."

### 3.7 The `mcp_read` role's EXECUTE grants and the tests that pin them

- `core/src/ops_core/privileges.py:185-201` (`DEFINER_FUNCTIONS`, name → (argument types, callers)): `mcp_read`
  appears in exactly two rows: `"current_time": ("", RUNTIME_ROLES)` (`:186`; `RUNTIME_ROLES` `:31` includes
  `mcp_read`; erratum 15: callable by every runtime role) and `"resolve_invocation": ("text, text", ("mcp_read",
  "mcp_exec"))` (`:195`). `HELPER_FUNCTIONS` (`:204-213`) are granted to nobody. `mcp_read` has no table row in
  `GRANTS` (`tests/plan_e/test_privileges.py:20-25`).
- The rendered grants: `function_grant_statements` (`privileges.py:277-300`) emits `REVOKE ALL … FROM PUBLIC` then
  `GRANT EXECUTE … TO <callers>`; each revision freezes its own callers (round-3 finding N1).
- Tests:
  - `tests/e2e/test_definers_run_path_live.py:329-353` (`test_function_catalog_shape`, R106): the set of `app`
    functions equals `DEFINER_FUNCTIONS ∪ HELPER_FUNCTIONS` exactly, no PUBLIC entry, helpers granted to nobody, and
    each definer's ACL grantees equal its matrix callers (`:353`). This is the pg_proc ACL equality that R131's
    "mcp_read can EXECUTE only …" would read; today it pins `{current_time, resolve_invocation}` for `mcp_read`.
  - `tests/e2e/test_roles_live.py:82` (`test_r124_every_grantee_holds_exactly_its_matrix_privileges`) and `:117`
    (`test_r084_function_only_roles_cannot_read_or_lock_any_table`).
  - `tests/plan_e/test_privileges.py:43-49`: `resolve_invocation` callers are `{mcp_read, mcp_exec}`.
  - `tests/e2e/test_migration_0008_live.py:242-262…` (`test_no_function_an_mcp_server_may_call_inserts_a_job`, T14
    review note 1): every function `mcp_read` or `mcp_exec` may EXECUTE (via `has_function_privilege`), and
    everything they call transitively, is free of an INSERT into `jobs`; neither role holds a table grant.
- No test presents an `execute` or `recover` handle to `mcp_read` (`grep` of `tests/` for `handle_for(…"execute")`
  and `Server.WRITE` finds only mcp-write/`mcp_exec` uses; Plan E open item `SESSION_STATE.md:203` "a write handle at
  mcp_read"). No test stages a handle whose stored `server` column disagrees with its job type (T15 review note 4).

### 3.8 asset-sim: a stub

- `asset-sim/` holds `README.md`, `pyproject.toml` (`dependencies = ["ops-core"]`, no FastAPI) and
  `src/ops_asset_sim/__init__.py` (`"""Synthetic asset/alert API"""`, `__version__`). No server, route or entry
  point. README: "## Owns: Deterministic asset and alert data under an injected clock"; "## Trusts: Only mcp-read's
  token and forwarded tenant/asset context"; "## Never: Any write; any other caller".
- mcp-read does not reach it: `settings.Urls` (`core/src/ops_core/settings.py:420-436`) has `mcp_read_resource`,
  `mcp_write_resource`, `mcp_read`, `mcp_write`, `incident_sim` — no asset-sim URL; `scripts/skeleton.py:272`
  starts `Process("mcp-read", "ops_mcp_read", 8081)` and no asset-sim process. mcp-read holds no workload token
  source of its own (mcp-write does, §3.3), though the realm has an `ops-mcp-read` client with an `asset-sim`
  audience (§3.10).

### 3.9 Schemas for the read tools and the tool result

- `schemas/tools/search_procedures.input.schema.json:6-35`: `additionalProperties: false`; `query` string 1–500;
  `asset_type` string 1–40 (optional); `limit` integer 1–8; `mode` enum `lexical | vector_exact`; required `query,
  limit, mode`.
- `schemas/tools/get_asset_status.input.schema.json:6-17`: `asset_id` string ≤32, pattern
  `^[A-Z][A-Z0-9_-]{0,31}(?![\s\S])`; required `asset_id`.
- `schemas/tools/get_recent_alerts.input.schema.json:6-40`: `asset_id`, `start_at`/`end_at` (`date-time`, `Z` or
  `+00:00`, erratum 6), `limit` 1–100, optional `cursor` 1–200; required `asset_id, start_at, end_at, limit`.
- `schemas/tool-result.schema.json` (1416 lines): `additionalProperties: false`; required `tool_name` (enum of the
  six), `request_id` (uuid), `status` (`ok | error | outcome`), `observed_at`, `truncated`, `data` (object|null),
  `error` (`{code ≤80, message ≤500, retryable}` | null) (`:6-82`). `status=error` ⇒ `data: null` and an error
  object, else `error: null` (`:86-131`). `get_asset_status`+`ok` data: `asset_id, state ∈ {normal, warning,
  unavailable}, revision, observed_at, data_source: "synthetic"` (`:134-185`). `get_recent_alerts`+`ok` data:
  `asset_id, start_at, end_at, alerts[≤100]{alert_id, asset_id, occurred_at, code, message, revision},
  next_cursor` (`:187-288`). `search_procedures`+`ok` data: `results[≤8]{evidence_id, document_id, version, section,
  content_sha256, excerpt, effective_from, retrieved_at}`, `retrieval_mode ∈ {lexical, vector_exact}`,
  `corpus_version` (`:290-387`). `status=outcome` is allowed only for the three write tools and requires
  `data.action_id` (`:1275-1299`); there is no rule tying an auth failure to an envelope (auth failures never reach
  the tool body, §3.12).
- `tests/plan_d/test_mcp_read.py:80-108` validates `search_response` envelopes against the schema;
  `tests/plan_c/test_schema_conformance.py:45`, `:58` skip the tool-input and envelope cases "(T15/T47)", "(T15)".

### 3.10 Keycloak realm (`deploy/dev/keycloak/realm-ops-dev.json`; no secret values, placeholders only)

- Realm `ops-dev` (`:2`), `sslRequired: "none"` (`:5`), `accessTokenLifespan: 300` (`:6`).
- `ops-web` (`:18-37`): confidential, `standardFlowEnabled: true`, `directAccessGrantsEnabled: false`,
  `serviceAccountsEnabled: false`, PKCE S256, redirect `http://localhost:8000/auth/callback`; **no protocol
  mappers** (no audience mapper).
- `ops-worker` (`:39-63`): service account only; mappers "aud mcp-read resource" (`oidc-audience-mapper`,
  `included.custom.audience: ${MCP_READ_RESOURCE_URL}`, access token only, `:50-54`) and "aud mcp-write resource"
  (`${MCP_WRITE_RESOURCE_URL}`, `:57-61`). One worker token therefore carries **both** MCP audiences.
- `ops-mcp-read` (`:66-83`, "mcp-read (workload; calls asset-sim)"): service account; mapper "aud asset-sim"
  (`included.custom.audience: asset-sim`, `:77-81`). `ops-mcp-write` (`:86-103`): mapper "aud incident-sim".
  `ops-dev-direct` (`:106-123`, public, direct grant): mapper "aud ops-api". `ops-view-users` (`:126`) and
  `ops-test-admin` (`:138`, dev/test only, erratum 30) carry no audience mapper.
- `scripts/bootstrap_dev.py:58-59`: `MCP_READ_RESOURCE_URL = "http://mcp-read:8081/mcp"`,
  `MCP_WRITE_RESOURCE_URL = "http://mcp-write:8082/mcp"`, written to `.env` (`:114-115`) and passed to Keycloak
  (`compose.yaml:48-49`). `settings.urls()` defaults are the same audience strings; the listen URL is
  `OPS_MCP_READ_URL` = `http://127.0.0.1:8081/mcp` (`settings.py:431-434`; module docstring `:7-8`: "The MCP
  resource URLs are audience identifiers …, distinct from the loopback listen URLs …; T30 makes them coincide").
- Recorded claims (`reports/bootstrap/keycloak-claims.txt:10-12`, decoded claims only): `ops-worker` → `aud:
  ["http://mcp-read:8081/mcp", "http://mcp-write:8082/mcp", "account"]`, `azp: "ops-worker"`; `ops-mcp-read` →
  `aud: ["asset-sim", "account"]`, `azp: "ops-mcp-read"`; `ops-mcp-write` → `aud: ["incident-sim", "account"]`;
  personas (`:13-17`) → `aud: "ops-api"`, `azp: "ops-dev-direct"`; `iss` identical host and container (`:18`). The
  file's first run (`:1-9`) shows persona tokens with no `aud` (before the `ops-api` mapper, Plan D ruling 3).
  No `ops-web` access token's claims are recorded.
- `tests/plan_b/test_realm_template.py:100-108` pins `ops-web` to code flow with PKCE, no direct grant.

### 3.11 The worker's MCP client and how it sends the handle and token

- `worker/src/ops_worker/mcp.py` (76 lines): `HttpMcpCaller.call(url, *, handle, tool, arguments)` (`:58-76`) opens
  one connection per call: headers `{"Authorization": f"Bearer {await self._tokens.token()}", "X-Ops-Invocation":
  handle}` on an `httpx2.AsyncClient` (`:61-63`), `Client(streamable_http_client(url, http_client=http),
  mode="2026-07-28")` (`:64`), `call_tool` (`:66`). Transport failures (`MCPError`, `httpx2.HTTPError`, `OSError`,
  also inside exception groups, `:21-31`, `:67-73`) and `result.is_error` or a non-dict `structured_content`
  (`:74-75`) raise `McpCallFailed`. No `list_tools`, no tool-schema check, no envelope validation against the
  schema (BS:399's nested validation is T16's "fail-closed result validation").
- Token source: `WorkloadTokenSource(client_id="ops-worker", client_secret=settings.read_secret(
  "kc_client_secret_ops_worker"))` (`worker/src/ops_worker/main.py:136-139`), one source for both servers.
- Handle use (`worker/src/ops_worker/handlers.py`): `investigate` transitions QUEUED → RETRIEVING, then mints a
  `Server.READ` handle with `azp="ops-worker"` (literal) at `lease.fence` in the same unit (`:108-111`); one call
  `search_procedures` with `{"query": text[:QUERY_CHARS], "limit": 3, "mode": "lexical"}` under `lease.effect`
  (`:115-122`); an error envelope (`status != "ok"`) raises `ValueError` in `proposals.evidence_from_search`
  (`worker/src/ops_worker/proposals.py:35-38`) and the run is failed "retrieval failed" (`handlers.py:124-127`).
  `execute` mints a `Server.WRITE` handle the same way (`:223-224`). `handle` (`:284-295`) dispatches
  `investigate` and `execute` only; `resume_input` and `recover` are logged and finished unhandled (T20, T22).
  `release_lease` revokes the fence's handles in the job's final unit (`persistence.py:776`).

### 3.12 The installed MCP SDK (`mcp 2.3.0`, `mcp-types 2.3.0`; `uv.lock:631-632`, `:656-657`)

Imports and versions: `httpx2 2.13.1` (`uv.lock:284-285`), `uvicorn 0.54.0` (`:1470-1471`), `pyjwt 2.15.1`
(`:1092-1093`). `sp/mcp/server/mcpserver/__init__.py:15` exports `Context`; `sp/mcp/__init__.py:65` exports
`Client`.

- **Custom verifier wiring.** `TokenVerifier` Protocol (`sp/mcp/server/auth/provider.py:124-135`): `async def
  verify_token(token) -> AccessToken | None`; its docstring: set `AccessToken.resource` to the token's resource
  ("for a list, the entry equal to the server's `AuthSettings.resource_server_url`"); "With
  `AuthSettings.validate_token_resource` the bearer middleware then refuses any token whose resource is not
  `resource_server_url`; without it, confirming the token was issued for this server … is up to the verifier."
  `AccessToken` (`:53-60`): `token, client_id, scopes, expires_at, resource, subject, claims`.
  `MCPServer.__init__` refuses `auth` without a verifier or provider, and a verifier without `auth`
  (`sp/mcp/server/mcpserver/server.py:251-256`).
- **Auth settings.** `AuthSettings` (`sp/mcp/server/auth/settings.py:20-70`): `issuer_url` (required),
  `resource_server_url` (required field), `required_scopes`, `validate_token_resource: bool | None` — unset with a
  resource URL warns that "it will default to True in 3.0" (`:57-69`).
- **Middleware order** (`sp/mcp/server/lowlevel/server.py:781-795`): `AuthenticationMiddleware(BearerAuthBackend(
  token_verifier, resource_server_url=auth.resource_server_url if auth.validate_token_resource else None))` then
  `AuthContextMiddleware`; the MCP route is wrapped in `RequireAuthMiddleware` (`:811-822`), which answers 401
  `invalid_token` with `WWW-Authenticate: Bearer … resource_metadata="…"` when no authenticated user exists
  (`sp/mcp/server/auth/middleware/bearer_auth.py:115-121`, `:135-165`). `BearerAuthBackend.authenticate`
  (`bearer_auth.py:55-80`): verifier `None` → unauthenticated; `expires_at < time.time()` → unauthenticated
  (`:71-72`); resource comparison only when `resource_server_url` is passed (`:74-78`). Protected-resource metadata
  routes are added whenever `resource_server_url` is set (`server.py:833-841`; served at
  `/.well-known/oauth-protected-resource/mcp`, Plan D spike §2 item 7).
- **Reaching the token and headers from a tool.** `get_access_token()` reads a context variable set by
  `AuthContextMiddleware` (`sp/mcp/server/auth/middleware/auth_context.py:10-20`, `:35-46`). `Context.headers`
  (`sp/mcp/server/mcpserver/context.py:289-296`): "Request headers carried by this message … Headers are
  client-supplied input - never treat one as an identity assertion." `Context.protocol_version` (`:303-306`).
- **Era routing (protocol version).** `StreamableHTTPSessionManager._handle_request`
  (`sp/mcp/server/streamable_http_manager.py:183-204`): if the `MCP-Protocol-Version` header is present and **not**
  one of `HANDSHAKE_PROTOCOL_VERSIONS`, the request goes to `handle_modern_request`; a request **without** the
  header, or with a handshake version, goes to the legacy path (`_handle_stateless_request` when
  `stateless_http=True`, `:201-202`). `HANDSHAKE_PROTOCOL_VERSIONS` = `2024-11-05, 2025-03-26, 2025-06-18,
  2025-11-25`; `MODERN_PROTOCOL_VERSIONS` = `("2026-07-28",)` (`sp/mcp_types/version.py:33-42`).
- **Per-request validation (modern path).** `handle_modern_request` (`sp/mcp/server/_streamable_http_modern.py:375-
  …`): transport security (Host/Origin) first (`:394-398`), then method/accept/JSON checks, then
  `classify_inbound_request(decoded, headers=dict(request.headers))` (`:443`). The ladder
  (`sp/mcp/shared/inbound.py:390-495`): rung 1, `params._meta` must carry `io.modelcontextprotocol/protocolVersion`
  and client capabilities → `INVALID_PARAMS`; rung 2, the `MCP-Protocol-Version` header must be present and equal
  the envelope's version, `Mcp-Method` equal the body's method, `Mcp-Name` the named param → `HEADER_MISMATCH`
  (`:449-470`; "a null body version would otherwise slip the equality check", `:450-452`); rung 3, the version must
  be in `supported_modern_versions` → `UNSUPPORTED_PROTOCOL_VERSION` (`:487-488`). Codes: `HEADER_MISMATCH = -32020`,
  `UNSUPPORTED_PROTOCOL_VERSION = -32022` (`sp/mcp_types/jsonrpc.py:73-80`); HTTP 400 for `INVALID_PARAMS`,
  `HEADER_MISMATCH`, `UNSUPPORTED_PROTOCOL_VERSION` (`inbound.py:312-315`). `PROTOCOL_VERSION_META_KEY =
  "io.modelcontextprotocol/protocolVersion"` — "for HTTP its value must match the `MCP-Protocol-Version` header"
  (`sp/mcp_types/_types.py:53-56`). `server/discover` answers `supported_versions=list(MODERN_PROTOCOL_VERSIONS)`
  (`sp/mcp/server/lowlevel/server.py:684`). Authentication runs **before** all of this (middleware), so a refused
  token is a 401 whatever the version headers say.
- **DNS-rebinding default.** `streamable_http_app(host="127.0.0.1")` with `transport_security=None` enables
  protection with `allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*"]` (`sp/mcp/server/lowlevel/
  server.py:752-758`); another `Host` gets 421 "Invalid Host header" (`sp/mcp/server/transport_security.py:116`;
  measured, Plan D spike §2 item 6).
- **Client side.** `Client.mode` (`sp/mcp/client/client.py:335-342`): `"auto"` probes `server/discover`, `"legacy"`
  forces the initialize handshake, "A modern protocol-version string (e.g. '2026-07-28') adopts that version
  directly without a probe". The session stamps `_meta[PROTOCOL_VERSION_META_KEY]` per request
  (`sp/mcp/client/session.py:161-164`); the transport adds the cached `MCP-Protocol-Version` header, and its
  docstring says these MCP headers "are merged with the ``httpx2.AsyncClient`` defaults (these take precedence)"
  (`sp/mcp/client/streamable_http.py:139-157`).
- **Measured behaviour** (Plan D spike, `docs/superpowers/research/2026-10-08-plan-d-spike.md`): §2 item 2
  (`:216`) the generated argument model ignores extra keys (hence `strict_tool`); item 4 (`:218`) bad arguments come
  back as `is_error=True`, not exceptions; item 5 (`:219-223`) no token, a persona token and an `ops-mcp-write`
  token all get HTTP 401, which the client sees as `MCPError` code `-32603` "Server returned an error response" (the
  401 status is lost; with `mode="2026-07-28"` it surfaces at the first call); item 8 (`:226`) a raw POST with
  `MCP-Protocol-Version: 2026-07-28` and empty `params` gets 400/-32602; item 9 (`:227`) expiry is checked twice
  consistently; item 10 (`:228`) the `validate_token_resource` warning. Not measured in this repository: a
  legacy-version request (no header or a 2025 header) against these servers, and a header/`_meta` mismatch.

### 3.13 Existing tests for mcp-read and the token path, and what they prove

- `tests/plan_d/test_mcp_read.py` (unit, no network): section hashes equal `meta.json` (`:32`); tenant-scoped,
  approved-only corpus (`:48`); deterministic bounded search (`:68`); envelope validates against the schema (`:80`);
  `test_tool_schema_conforms_to_the_contract_and_rejects_extra_arguments` (`:111-138`): **in-process**
  `Client(mcp)` (no HTTP, no bearer middleware), `list_tools` = `{"search_procedures"}`, `additionalProperties:
  false`, required and bounds equal the input schema, `tenant_id` extra argument → `is_error`, `limit=9`, `"1"`,
  `True` → `is_error`, and with no access token the body answers `status=error`/`INVALID_HANDLE`.
- `tests/e2e/test_mcp_read_live.py:26-83` (live, `OPS_LIVE=1`): `production_app()` under uvicorn on
  127.0.0.1:18081 **inside the test's own event loop** (`:29-31`); a real run, a lease, a `Server.READ` handle minted
  by the worker role (`:39-49`); a real `ops-worker` token; `search_procedures` returns `status=ok` and the first
  `evidence_id == "ALPHA-INCIDENT:v2:review"` (`:58-62`); a persona token (`ops-dev-direct`, aud `ops-api`) and an
  `ops-mcp-write` token are refused with `MCPError` (`:63-78`). Docstring: "Catches: the bearer middleware wired to
  the wrong audience, a handle that resolves at the wrong server, and the two rejections the e2e test relies on".
- `tests/e2e/test_tokens_live.py:13-41`: Keycloak's real JWKS; the worker token passes the read verifier; the
  persona token fails it; the API verifier accepts the persona and refuses the worker token.
- `tests/plan_d/test_tokens.py:75-96` (`test_rejections`, synthetic JWKS): another audience (the write server's),
  **no audience**, azp `ops-mcp-write`, no azp, expired, wrong issuer, wrong key, unknown kid, no/empty `sub`,
  future `nbf`, and **azp `ops-web`** ("the browser client must not open a worker-only MCP server", `:90`); the
  token text never appears in the error.
- Handle resolution at the definer level: `tests/e2e/test_definers_write_path_live.py:260-300`
  (`test_resolve_invocation_binds_server_azp_expiry_and_revocation`): a read handle resolves at `mcp_read` with a
  preset foreign tenant left untouched; refused (`OC008`) at `mcp_exec`, with azp `ops-web`, for an unknown handle,
  when expired, after `revoke_handles`; `api` gets `42501`. `tests/e2e/test_migrations_and_persistence.py:166-194`
  (`test_handles_bind_to_one_server`): stored hash only; `mcp_exec` refuses a read handle; the Python allowlist
  refuses `CREATE_INCIDENT` for an investigate handle. `tests/e2e/test_fenced_definers_live.py:63-82`: a handle is
  refused after its fence moves and after its lease expires. `tests/e2e/test_leases_live.py:292`, `:333`: TTL and
  fence carried; release revokes. `tests/e2e/test_heartbeat_live.py:189`: R088, a forced renewal failure cancels the
  call and revokes the handle. `tests/plan_d/test_persistence_pure.py:30`: a handle refusal never echoes server text.
  `tests/plan_e/test_persistence_errors.py:72`: the hash equals the canonical sha256 of the UTF-8 bytes.
- R105 (`tests/e2e/test_r105_walking_skeleton.py:1-6`): the worker, a separate process started by
  `scripts/skeleton.py`, calls mcp-read over HTTP with real tokens; evidence `reports/skeleton/
  r105-walking-skeleton.txt`.
- Not covered anywhere: a protocol-version header/`_meta` mismatch or a legacy-version request; `list_tools` over
  HTTP; a live missing-`aud` token; a real `ops-web` (browser) token at mcp-read; an execute/recover handle at
  mcp-read; a stored-`server` column that disagrees with the job; a handle used for another run; a handle presented
  with a different azp over HTTP (only directly at the definer).

### 3.14 Migration and dev-database state

- Head revisions: `0008_journal_outbox` (main) and `tc_0001_test_clock` (branch). mcp-read's path needs
  `resolve_invocation` (0004) and the fenced `_resolve_handle` (0007). The dev database is at 0005 pending the
  owner's migrate (`SESSION_STATE.md:9-12`); with no `assert_relation`, mcp-read would start on it and resolve with
  0004's unfenced `_resolve_handle` (§3.6), while the worker refuses to start there (`main.py:148`).

---

## 4. Prior rulings and proposed errata that touch T15

- **Erratum 3** (`SESSION_STATE.md:145`): "AM-20.3 `search_procedures_scoped`: `mode=vector` is the SQL argument
  value; the externally visible `retrieval_mode` is `vector_exact`, and mcp-read translates between them." (Plan C
  ruling 3, `docs/superpowers/plans/2026-10-08-first-slice-c-contracts-schemas.md:16`: "The translation point is
  `search_procedures_scoped`'s caller in mcp-read (T15), recorded as `TODO(T15)` in `routing.py`.")
- **Erratum 6** (`:148`): the `get_recent_alerts` input accepts `Z` or `+00:00`.
- **Erratum 15** (`:187`): "AM-20.6: `app.current_time()` is a definer function callable by every runtime role."
  (So `mcp_read` holds EXECUTE on `current_time`, outside R131's three-function list.)
- **Erratum 18** (`:190`): "the `OC001` authority check is reachable only past the EXECUTE ACL, so a role without
  EXECUTE never sees it."
- **Erratum 19** (`:191`): "AM-20.3 `resolve_invocation` returns `job_type`, `job_id` and `conversation_id` instead
  of SA:459's `allowed_tools` (plan ruling 21)." Plan E ruling 21 (`…first-slice-e…md:64`): "**Handles are hashed
  everywhere.** … The server binding comes from `session_user` (`mcp_read` → read handles, `mcp_exec` → write
  handles) **and** from the job type (SA:496), never from the worker-written `server` column alone; the tool
  allowlist stays in Python (`JOB_RULES`), so `resolve_invocation` returns `job_type` rather than `allowed_tools`."
- **Erratum 48** (`:361-362`): `mark_sent(raw_handle, …)`, `record_outcome(raw_handle, …)`; "a stale fence or a
  lapsed lease is the handle refusal OC008".
- **Erratum 53** (`:373-374`): "SA:459: `resolve_invocation` reads `invocation_context` without a lock; `run_lease
  FOR SHARE` in `_resolve_handle` is the one lock, shared by every handle function."
- **Erratum 55** (`:377`): "`revoke_handles` revokes the handles of the given fence and older ones and never
  refuses." **Erratum 57** (`:381-383`): "exits the run" means cancelling in-flight MCP and model calls, revoking
  the job's handles and handing the job back.
- **Erratum 58** (`:384-388`): "a handle's \"additionally bounded by current lease\" is enforced at use, not at
  mint. `_resolve_handle` compares the handle's fence with `run_lease` and requires a live lease, under `FOR SHARE`
  …. Its stored `expires_at` is `app.current_time() + 60 s` at mint, with no `least(…, lease_until)` cap". Plan H
  ruling (`:405-410`): "This replaces the debt line that gave handles a 20-30 s practical life; per-call minting is
  no longer owed."
- **Erratum 59** (`:389-392`): "AM-15 (SA:355) … After SENT a stale-fence refusal is answered `status=outcome` /
  `UNKNOWN` with the `action_id` …. Before SENT it stays the plain refusal." (mcp-write only.)
- **Plan D rulings** (`docs/superpowers/plans/2026-10-08-first-slice-d-walking-skeleton.md`): review focus 3
  (`:34`): "A token with the wrong audience must be refused by every resource server — … `mcp-write`'s token at
  `mcp-read`, a persona token at either MCP server — and the refusal must never carry an `action_id` (SA:357)."
  Ruling 2 (`:43`): "The one read tool is `search_procedures`, served from `data/handoff-fixtures/` inside
  `mcp-read` … `get_asset_status`/`get_recent_alerts` need asset-sim (T16) and are not registered. Lexical mode
  only; `vector_exact` is refused with a tool error until T17". Ruling 15 (`:56`): the `MCPServer(…,
  auth=AuthSettings(…, validate_token_resource=False), token_verifier=…)`, `stateless_http=True`,
  `json_response=True` shape and the client's `mode="2026-07-28"`; "The servers' derived input schemas are checked
  against `schemas/tools/<tool>.input.schema.json` for required keys, property names and enums (not byte
  equality)." Ruling 19 (`:60`): handles per job, checks of expiry, revocation, azp, job type → server ("R131 in
  miniature") and the tool allowlist; "The handle is never logged." Ruling 25 (`:66`): "A wrong-audience token is
  401 everywhere in T08 … T10's 403 for \"authenticated but not this audience\" is its own refinement."
- **Plan E rulings**: ruling 12 (`…first-slice-e…md:55`): `WrongAudience(TokenRejected)` for aud/azp mismatch;
  "every existing `except TokenRejected` keeps answering 401 (Plan D ruling 25 stands for the API and the MCP
  servers), and incident-sim catches `WrongAudience` first and answers 403 `FORBIDDEN` with no action id (SA:357)."
  Review focus 5 (`:38`): "`mcp_exec` must not be able to read any table …" (R084/R124/R128). Ruling 1 (`:44`): no
  stub definers (§3.6). Ruling 20 (`:63`): the `OC` error vocabulary, `OC008` handle_rejected, "Messages never carry
  a handle, a token or a secret."
- **Plan F**: erratum 31 (`:221`): "The provider refresh token is stored sealed and spent at logout; the ID and
  access tokens are not stored." (The API keeps no `ops-web` access token.)
- **Plan H**: erratum 47 (`:350-351`, the worker's unit takes `run_lease FOR SHARE`); the T15-relevant Plan H
  debt is none; `SESSION_STATE.md:399-401` re-homes "the token verifier's injected-fetch exception → T30".
- **Errata 60–71** (Plan I) contain nothing on mcp-read, tokens, handles, audiences or the protocol version.
  Erratum 62's "No job is created by either MCP server" companion is the catalog test of §3.7.
- Errata 1–71 contain no ruling on the protocol-version check, a legacy-version request, the browser-token test,
  `asset_scope`, the run-state/attempt-state allowlist or mcp-read's startup guard beyond those quoted above.

---

## 5. Open questions the planner must rule on

1. **What T15 adds beyond the skeleton.** Already real (Plan D "Not debt", `SESSION_STATE.md:569`): the custom
   verifier (iss, aud ∋ resource URL, azp ∈ {ops-worker}, exp, sub, RS256; §3.4), the SDK wiring (§3.2), the
   header-only handle, hashing, azp/server/expiry/revocation/fence binding in `_resolve_handle` (§3.6), the
   job-type allowlist (§3.5), revocation at release (§3.11). Not yet: the run-state/attempt-state allowlist
   (`jobs.py:54-56`), `asset_scope`/`search_procedures_scoped` (§3.6), R131's ACL shape (Q10), protocol-version
   tests (Q4), live tests for most DoD 2 cases (§3.13), a startup guard (Q18). Open: the exact scope, and which of
   these the plan treats as evidence-only (tests over existing code) versus new code.
2. **Verifier strictness and `validate_token_resource`.** Today `McpVerifier` stamps `resource=self._resource`
   whatever `aud` held (`server.py:132`) and `validate_token_resource=False` (`:194`); the audience check is
   PyJWT's containment (`tokens.py:155`). The worker's single token carries both MCP audiences
   (`keycloak-claims.txt:10`), so aud alone does not separate the two servers for the worker; the handle's server
   binding does. The SDK warns that 3.0 makes `validate_token_resource=True` the default (`settings.py:57-69`).
   `typ` is not checked for access tokens (`typ=None`), `nbf` is enforced by PyJWT. Open: keep the stamp, or set
   `resource` from the matching `aud` entry and turn `validate_token_resource` on; whether `typ: "Bearer"` is
   required; whether `WrongAudience` stays 401 at the MCP servers (Plan D ruling 25, Plan E ruling 12) or becomes 403
   like incident-sim; whether the duplicated `McpVerifier` moves into `ops_core` (mcp-write's comment `:39-40` keeps
   it duplicated by design).
3. **"Custom TokenVerifier" vs the SDK's auth mode.** BS:366 asks to "Implement the MCP resource-server requirements
   of the pinned protocol separately"; the SDK serves protected-resource metadata at
   `/.well-known/oauth-protected-resource/mcp` naming `http://mcp-read:8081/mcp` and the Keycloak issuer (spike §2
   item 7). Open: whether that route stays, and whether any further 2026-07-28 resource-server requirement is in
   scope.
4. **Protocol-version enforcement (DoD 3, SA:571-572).** The SDK rejects a header/`_meta` mismatch on the modern path
   with `HEADER_MISMATCH` (-32020, HTTP 400, `inbound.py:449-455`) and an unknown version with -32022; but a request
   with **no** `MCP-Protocol-Version` header, or with a 2024/2025 handshake version, is routed to the legacy
   stateless path (`streamable_http_manager.py:192-202`), which neither mcp-read nor mcp-write disables. BS:378:
   "reject unexpected negotiation/schema changes". Open: whether T15 refuses non-2026-07-28 requests (a guard
   before the SDK app, a server setting, or none), what status/body a refusal carries, and whether the same applies
   to mcp-write now or in T47.
5. **Staging the mismatch test.** The SDK client stamps header and `_meta` from one value (`session.py:161-164`,
   `streamable_http.py:139-157`, whose docstring says the MCP headers take precedence over the httpx client's
   defaults); the spike reached the ladder with a raw `httpx2` POST (`:226`). Open: raw POST versus a patched client,
   which mismatches are asserted (header absent, header ≠ `_meta`, `Mcp-Method` ≠ body), and that each runs with a
   valid token (auth precedes the ladder, §3.12).
6. **The run-state and attempt-state allowlist.** SA:338/SA:459 derive allowed tools from job type + run state +
   attempt state; erratum 19 / Plan E ruling 21 keep the allowlist in Python and return `job_type`, `run_state`,
   `attempt_state`; `allowed_tool` checks the job type only (`persistence.py:375-379`); `JOB_RULES[…].run_states`
   exists but is unused at resolution. For read handles: `investigate` runs in QUEUED/RETRIEVING/DRAFTING, and the
   worker calls mcp-read in RETRIEVING (`handlers.py:108-122`); `resume_input` in AWAITING_INPUT/QUEUED (no
   handler, T20). Open: SQL (`_allowlist`, SA:474) versus Python; the exact run-state set per read job type; what
   a refusal for a terminal or CANCELLED run looks like (same `INVALID_HANDLE`?); whether `_resolve_handle` should
   also check `jobs.done_at IS NULL` and `jobs.run_id = handle.run_id` (neither is checked, §3.6).
7. **Review note 2 is a write rule.** "create_incident only with no attempt or INTENT, not cancelled, before
   deadline" (SA:240, SA:344-345) concerns mcp-write (T47), yet sits on T15, whose `resolve_invocation` and
   `allowed_tool` are shared by both servers (`mcp-write/server.py:182-185`). mcp-write today branches on the
   attempt state inside `execution.next_step` (`execution.py:36-44`) and re-checks cancellation and the deadline in
   `mark_sent`. Open: whether T15 implements the attempt-state filter for both servers, only the shared mechanism,
   or leaves the write half to T47/T22.
8. **Which read tools T15 registers.** T15's instructions name no tool; T16 owns `get_asset_status`,
   `get_recent_alerts` and asset-sim; asset-sim is a stub with no server (§3.8); T15 review note 3 says mcp-read
   "reads asset data via asset_scope + asset-sim". Open: whether T15 registers anything beyond `search_procedures`;
   whether `asset_scope` ships in T15 with no caller (Plan E ruling 1 rejected definers without a caller) or with
   T16; whether DoD 1's "lists and calls tools" is satisfied by one tool.
9. **`search_procedures_scoped` (T15, T16 or T17).** It needs approved, effective, tenant-permitted chunks
   (SA:461), i.e. T17's tables, which do not exist (no `documents`/`chunks`/`embeddings`, no pgvector extension);
   T15 does not depend on T17; T16 depends on T15 and T17; the Plan E debt line says "→ T15/T16/T17" (`:574`); the
   procedures docstring says "debt → T17" (`procedures.py:1-2`); erratum 3's translation is TODO(T15). Open: who
   creates the function and when; whether the fixture corpus in mcp-read survives T15; whether T15's R131 evidence
   can assert a three-function list before two of the functions exist.
10. **R131's read half against today's grants.** `mcp_read` holds EXECUTE on `current_time` and
    `resolve_invocation` (§3.7); R131 says "mcp_read can EXECUTE only resolve_invocation, asset_scope,
    search_procedures_scoped" and erratum 15 grants `current_time` to every runtime role. Open: whether the R131
    test counts `current_time` as an allowed extra (an erratum) or `mcp_read` loses it (mcp-read itself never calls
    `current_time`; the definers do, as `app_definer`); what "cannot execute any write-path function" is tested by
    (the catalog ACL equality, `has_function_privilege` per write function, an attempted call → `42501`); and the
    live HTTP case "an execute/recover handle presented to mcp-read" (untested, §3.7), plus the review-note-4 case
    of a stored `server` column that lies (untested).
11. **Staging R027 / DoD 2's handle cases.** "replayed": a handle is reusable for its job's life by design (60 s,
    erratum 58), so a replay is refused only after `revoke_handles`/release, expiry, or a fence move; "expired":
    `expires_at` on `app.current_time()` (test clock available in the test profile); "other-run": `search_procedures`
    takes no run argument, so the handle alone names the run — what "other run" means for a read tool is open (a
    handle for run A presented while the caller intends run B? a handle whose job belongs to another run?);
    "other-azp": the verifier refuses any azp other than `ops-worker` before resolution, and Keycloak has no other
    client carrying the mcp-read audience (§3.10), so a different azp reaches `_resolve_handle` only through a
    synthetic token (unit, synthetic JWKS), a realm change, or a direct definer call (as `test_definers_write_path_
    live.py:287` does); "expired fence" and "tool" are covered at the definer/Python level (§3.13). R027 also asks
    "handle absent from model/logs": the redaction filter covers `X-Ops-Invocation` (`redaction.py:40`), the draft
    request carries no handle (`handlers.py:153`). Open: which layer each case is proved at (HTTP, persistence,
    definer), and what log evidence is captured.
12. **"Independent-process client" (DoD 1, R025, BS:378, BS:589).** The live mcp-read test runs the server in the
    test's own event loop over a real socket (`test_mcp_read_live.py:29-31`); R105 runs the worker as a separate
    process. No live test calls `list_tools`. R025's expected evidence names **both** servers, but T15 is its only
    owner and mcp-write is T47's. Open: a subprocess server, a subprocess client (a script, the worker's
    `HttpMcpCaller`, or `python -m` of a probe), whether mcp-write is included now, and whether R031's "network
    tests" half is the same evidence.
13. **Error envelopes for auth and handle failures (review note 1, SA:354-355).** Token failures are HTTP 401 at the
    transport before the tool body (the client sees `MCPError -32603`, the status lost, spike item 5); handle
    failures are a tool-level `status=error` envelope `INVALID_HANDLE` "invocation handle rejected", returned with
    `is_error=False` (`server.py:183-184`), which the worker turns into "retrieval failed" via `ValueError`
    (`proposals.py:37-38`). The T08 open item (`:172`) flags "the same `INVALID_HANDLE`" for every rejection. mcp-read
    never has an `action_id`. Open: one code or several, `retryable` (a lapsed lease is retryable for the next
    owner), whether an authorization failure should be an MCP tool error (`is_error=True`) rather than an
    application envelope, and whether the worker should distinguish a 401 (spike: an httpx event hook sees it).
14. **The browser-token test (SA:558, R026).** `ops-web` is code-flow only, has no audience mapper and no direct
    grant (§3.10); the API stores no access token (erratum 31); the unit test mints an `azp=ops-web` token on a
    synthetic JWKS (`test_tokens.py:90`); the live test uses an `ops-dev-direct` persona token (aud `ops-api`) as
    the browser stand-in (`test_mcp_read_live.py:63-78`). A real `ops-web` access token could be obtained by
    driving the code flow (the `tests/e2e/kc_browser.py` helper drives Keycloak's form) and exchanging the code
    without the API, which needs the `ops-web` client secret from the secrets directory. Open: what counts as the
    browser token in evidence, and how it is minted without secrets in tests.
15. **The missing-`aud` live case.** No realm client now issues an access token without `aud` (every token carries
    at least `account`, §3.10; the first-run personas had none, `keycloak-claims.txt:4-8`). Unit coverage exists
    (`test_tokens.py:80`). Open: whether a synthetic-JWKS case suffices for "missing aud" or a live token is needed.
16. **TLS and hosts.** BS:364 "Use TLS outside localhost"; BS:350/BS:625 allow localhost HTTP and loopback binding;
    the servers bind 127.0.0.1 and the SDK's default DNS-rebinding guard admits only loopback `Host` values
    (§3.12), while the audience strings name `mcp-read:8081` (§3.10); containerisation is T30 (spike item 6 gives the
    `allowed_hosts` setting). Open: whether T15 configures `transport_security` or leaves both TLS and container
    hostnames to T30.
17. **What changes in the worker's client.** It pins `mode="2026-07-28"`, sends the token and handle as headers,
    opens one connection per call and checks only `is_error` and a dict result (§3.11). Open: whether T15 adds
    discovery (`list_tools`) or schema checks (or leaves them to T16's R029), distinguishes 401 from other failures,
    records the azp it actually holds instead of the literal `"ops-worker"` at mint (`handlers.py:110`), and handles
    `resume_input` handles (T20).
18. **mcp-read's startup guard.** mcp-read asserts only the clock profile (`server.py:211`); the other four
    processes assert a relation from 0007/0008 (§3.2), and Plan I's debt line omits mcp-read from the "refuse to
    start" list (`SESSION_STATE.md:716-717`). Open: which relation or revision mcp-read asserts, and whether T15
    adds a revision (0009) for new definers, an `_allowlist`, or changed `resolve_invocation` text — with frozen
    callers, a downgrade restoring 0008 exactly (R006 pattern, `0007_leases_fences.py:1-23`), and the dev-database
    instruction (still at 0005, owner input).
19. **Read results and the fence at use.** mcp-read resolves the handle in one committed unit, then serves results
    from memory (`server.py:179-189`); SA:176-184's "first executes … FOR SHARE" is phrased for mutations, while
    SA:460-461 give `asset_scope`/`search_procedures_scoped` the same locks "as above". Open: whether a read's data
    must be produced inside the lease-checked transaction (one definer call resolving and searching), and whether a
    handle refused mid-call matters for a read.
20. **Arguments versus the schema.** mcp-read's tool lacks the optional `asset_type` (§3.2), refuses `vector_exact`
    after resolution with `UNSUPPORTED_MODE` (`server.py:185-186`), and returns a fallback `corpus_version` when the
    tenant has no corpus (`:82-83`). Open: whether T15 touches the argument set (SA:461's `asset_type`), the order
    of checks, and the fallback.
21. **The azp binding (R085 "bound to the workload client").** The handle stores the azp the worker passes
    (`handlers.py:110`, literal `"ops-worker"`); `_resolve_handle` compares it with the token's azp (`0007:147`);
    the write-path definers other than `resolve_invocation` pass a literal `'ops-worker'` (§3.3). Open: whether
    T15 changes where the stored azp comes from, and whether the literal in the write-path bodies is in T15's scope
    (it is mcp-write's, T47).
22. **"Worker-chosen tools ignored" (R085).** The worker names the tool in `call_tool`; the server checks it against
    the job type (`allowed_tool`). There is no worker-supplied allowlist anywhere (the `server` column is the only
    worker-written binding, review note 4). Open: what R085's "worker-chosen tools ignored" is evidenced by (a call
    to a tool outside the allowlist; a lying `server` column; an unregistered tool name).
23. **Acceptance-matrix bookkeeping.** R031 is M01 in the matrix but M05 in `ACCEPTANCE.md:37`, owned by T04 (DONE)
    and T15, still `NOT_RUN`; R025's evidence wording differs between the matrix (both servers) and `ACCEPTANCE.md:31`
    (separate processes). Open: which rows T15 marks, with what `implementation_status`/`evidence_status`, and where
    its evidence lives (`reports/<area>/` like Plans F–I, `tests/plan_j/`, the `testpaths` entry).
24. **Spec cross-references that read oddly.** SA:34 sends the audience wording to AM-20.6 (the test clock); SA:459's
    lock column (`invocation_context FOR SHARE`) and return (`allowed_tools`) are superseded by errata 53 and 19;
    BS:360's "Refresh it only while the lease is current" has no refresh mechanism (one handle per job, 60 s,
    erratum 58). Open: whether T15 proposes errata for any of these.
25. **Per-service `tests/` and `Dockerfile`** (AM-01; Plan D open item → T30). mcp-read has neither (§3.2). Open:
    whether T15's new tests go under `mcp-read/tests/` or keep the repository's `tests/plan_<x>` and `tests/e2e`
    layout.

---

## 6. Glossary of exact names

- `ops_mcp_read.server`: `ToolResult`, `envelope`, `tool_error`, `search_response`, `Verifier`, `McpVerifier`,
  `strict_tool`, `State(session, corpora, verifier)`, `build_server(state, *, issuer, resource_url)`,
  `build_app(server, state)`, `production_app()`, `serve_app(app, port)`, `serve()` — `mcp-read/src/ops_mcp_read/
  server.py:42, 64, 59, 77, 103, 114, 138, 155, 164, 201, 244, 255, 265`.
- `ops_mcp_read.procedures`: `Corpus`, `Section`, `Hit`, `load_corpora`, `EXCERPT_CHARS = 500` —
  `procedures.py:68, 47, 60, 108, 21`.
- `ops_core.tokens`: `TokenVerifier`, `Principal`, `TokenRejected`, `WrongAudience`, `UnknownSigningKey`,
  `SigningKeysUnavailable`, `bearer_token`, `WorkloadTokenSource` — `tokens.py:77, 48, 29, 43, 33, 37, 58, 210`.
- `ops_core.persistence`: `resolve_invocation`, `Invocation`, `allowed_tool`, `handle_hash`, `mint_handle`,
  `revoke_handles`, `release_lease`, `HandleRejected`, `assert_clock_profile`, `assert_relation`, `Session` —
  `persistence.py:387, 363, 375, 382, 893, 284, 752, 51, 161, 170, 138`.
- `ops_core.jobs`: `Tool`, `Server`, `JobType`, `JobRule`, `JOB_RULES`, `server_for` — `jobs.py:19, 30, 37, 50, 69,
  133`.
- `app.resolve_invocation(text, text)` — `0004_write_path_functions.py:238`; callers `mcp_read`, `mcp_exec`.
- `app._resolve_handle(text, text, text)` — `0007_leases_fences.py:122` (fenced); `0004:65` (pre-fence, restored by
  0007's downgrade).
- `app.invocation_context(handle_sha256 PK, run_id, job_id, server, fence bigint, azp, expires_at, revoked_at,
  created_at)` — `0001:121`, `0002:304-306`.
- `HANDLE_COLUMNS` — `0004:29`. `OC008 handle_rejected` → `HandleRejected` — `persistence.py:80`.
- `privileges.DEFINER_FUNCTIONS`, `HELPER_FUNCTIONS`, `RUNTIME_ROLES` — `privileges.py:185, 204, 31`.
- `asset_scope(raw_handle)`, `search_procedures_scoped(raw_handle, query, query_embedding vector(768) NULL,
  asset_type, limit, mode)` — SA:460-461; not created.
- `settings.urls()` → `mcp_read_resource` (`MCP_READ_RESOURCE_URL`, default `http://mcp-read:8081/mcp`), `mcp_read`
  (`OPS_MCP_READ_URL`, default `http://127.0.0.1:8081/mcp`) — `settings.py:421-436`. `OPS_MCP_READ_PORT` 8081.
- Keycloak clients `ops-worker` (aud both MCP resource URLs), `ops-mcp-read` (aud `asset-sim`), `ops-mcp-write`
  (aud `incident-sim`), `ops-web` (no mapper), `ops-dev-direct` (aud `ops-api`) — `realm-ops-dev.json:18-143`.
- `HttpMcpCaller`, `McpCallFailed`, `failure_leaf` — `worker/src/ops_worker/mcp.py:50, 17, 21`.
- SDK: `MCPServer`, `Context` (`sp/mcp/server/mcpserver`), `Client` (`sp/mcp/client/client.py:267`),
  `AuthSettings` (`sp/mcp/server/auth/settings.py:20`), `TokenVerifier`/`AccessToken`
  (`sp/mcp/server/auth/provider.py:124`/`:53`), `BearerAuthBackend`/`RequireAuthMiddleware`
  (`bearer_auth.py:44`/`:91`), `get_access_token` (`auth_context.py:13`), `classify_inbound_request`
  (`sp/mcp/shared/inbound.py:390`), `HANDSHAKE_PROTOCOL_VERSIONS`/`MODERN_PROTOCOL_VERSIONS`
  (`sp/mcp_types/version.py:33`/`:41`), `HEADER_MISMATCH = -32020`, `UNSUPPORTED_PROTOCOL_VERSION = -32022`
  (`sp/mcp_types/jsonrpc.py:73`, `:79`), `PROTOCOL_VERSION_META_KEY` (`sp/mcp_types/_types.py:53`),
  `TransportSecuritySettings` (`sp/mcp/server/transport_security.py:20`).

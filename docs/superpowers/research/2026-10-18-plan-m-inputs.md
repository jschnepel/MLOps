# Plan M inputs: T16 (read tools and asset-sim on mcp-read) — fact sheet

Prepared 2026-10-18 on branch `plan-m` at `4be745a` (= `main` `66d6833` plus one records commit; read-only on the
repository except this file; the tree carries one unrelated uncommitted modification,
`docs/superpowers/research/2026-10-16-plan-k-inputs.md`, which this sheet neither reads for facts nor touches). Facts
only, no design. Citations: `SA:<line>` = `SPEC_AMENDMENTS.md`, `BS:<line>` = `BUILD_SPEC.md` (line numbers as of
`4be745a`); the amendments win wherever the two conflict. Repository files are cited as `path:line`. Nothing was run
against a database, Keycloak or a service for this sheet: every fact below is read from the files, and no secret,
token or `.env` value was opened.

Note on line numbers: AM-01 SA:68–91 (layout table SA:72–81, `mcp-read/` SA:76, `asset-sim/` SA:78); AM-02 SA:93–114
(roles SA:106); AM-10 clock rule SA:156–162; AM-12 fenced writes SA:176–184, lock order SA:188–189; AM-15 SA:327–358
(tool table SA:331–336, read row SA:333, handle binding SA:338, job table SA:340–346, read tools and vector mode
SA:348, schema rule SA:350, envelope SA:351–355); AM-16 graph router SA:377; AM-20.1 SA:391–404 (`mcp_read` SA:400);
AM-20.2 SA:406–442 (notes SA:436–442, "no table grants" SA:437); AM-20.3 SA:444–474 (header SA:446,
`resolve_invocation` SA:459, `asset_scope` SA:460, `search_procedures_scoped` SA:461, `grant_execution` SA:462,
helpers SA:474); AM-20.4 SA:492–506 (`invocation_context` SA:496); AM-20.5 SA:508–524; AM-20.6 SA:526–530; AM-20.7
item 6 SA:554–558 (asset-sim's trust SA:555, verifier SA:557); AM-50 corpus SA:640–645; AM-60 SA:680–728 (1.3.4
"T16 keeps the read tools" SA:689, 1.3 "T17 moves to M05 ahead of T16" SA:709); AM-80 SA:743–778 (tool-result row
SA:761, tool input schemas SA:766, alerts example SA:775, fixtures row SA:777). BUILD_SPEC §1 BS:36–42, §3 deployment
diagram BS:136–151 (asset API BS:146), §4 tenants/assets BS:161, §7 interval resolution BS:297, §9 BS:344–366 (MCP
workload identity BS:354–366: token BS:356, handle BS:360–361, server checks BS:362, allowlist BS:363, revoke
BS:364), §10 BS:376–407 (SDK BS:378, business tools BS:384–386, absolute timestamps BS:389, model-facing adapter
BS:395, tool-result contract BS:399, trusted records BS:401, synthetic services BS:405), §11 filtering BS:417, bundle
BS:419, source changes BS:425, §13 freshness BS:476, §17 budgets (interval BS:547, freshness BS:559), §19 MCP network
tests BS:589, §22 caller table BS:641–650 (MCP row BS:646), §25 M05 row BS:706.

---

## 1. T16 verbatim, its acceptance-matrix rows, and related tasks

### 1.1 T16 (`handoff/tasks.json:749-782`)

- **id/milestone/title:** `T16`, `M05` ("MCP read and write servers and governed corpus", `tasks.json:65-76`, task_ids
  `T15`, `T47`, `T17`, `T16`, milestone `status: "PLANNED"`), "Read tools and asset-sim on mcp-read" (`:752`).
  `status: "PLANNED"` (`:763`), `external_approval_required: false` (`:768`). The file's `current_milestone` is
  `"M05"` (`:3`).
- **instructions** (`:753`, verbatim): "asset-sim service (trusts only the mcp-read workload token and forwarded
  tenant/asset context, applies its own tenant filter); get_asset_status, get_recent_alerts (absolute interval,
  next_cursor), search_procedures over the governed store (vector mode: mcp-read computes the nomic search_query
  embedding); fail-closed result validation."
- **depends_on** (`:754-758`): `["T15", "T10", "T17"]`. T15 `DONE` (`:682`), T17 `DONE` (`:738`), T10 `DONE` (M02
  `status: "DONE"`, `:43`). T18 is **not** in T16's `depends_on`.
- **requirement_ids** (`:759-762`): `R028`, `R029`.
- **definition_of_done** (`:764-767`, verbatim):
  1. "Cross-tenant asset reads denied; unexpected tools and malformed results fail closed."
  2. "asset-sim rejects worker, api and mcp-write tokens."
- **review_notes** (`:769-781`, verbatim, all of them):
  - (`:770`) "search_procedures reads the governed store built in T17."
  - (`:771`) "search_procedures vector mode: mcp-read computes the nomic search_query embedding and passes it to
    search_procedures_scoped."
  - (`:772`) "T16 debts (Plan L debt list, Plan J ruling 20, Plan L final review; SESSION_STATE.md Plan J, K and L
    debt lists, docs/PROJECT_HISTORY.md Plan L review round):"
  - (`:773`) "a. asset_scope(raw_handle, client_azp) definer, the asset tools and asset-sim serving
    data/corpus/assets.json (R131's read half; erratum 96)."
  - (`:774`) "b. vector mode: mcp-read's vector_exact -> mode=vector translation and the nomic search_query embedding
    need T18's stored embeddings; until T18 the definer refuses mode=vector with OC005/VECTOR_MODE_UNAVAILABLE (0011,
    TODO(T18)) and mcp-read answers UNSUPPORTED_MODE before the database. Plan M will rule on deferring it."
  - (`:775`) "c. mcp-read's tool arguments, the order of its UNSUPPORTED_MODE check and its fallback corpus_version
    (Plan J ruling 20, to T16/T17; Plan L added the optional asset_type and reports the tenant's latest corpus
    version)."
  - (`:776`) "d. R029: the worker's client does no tool discovery and no result-schema check."
  - (`:777`) "e. pass the run's own asset type to search_procedures (the tool takes asset_type from its caller only)."
  - (`:778`) "f. R028: re-check the requester's current membership at read time."
  - (`:779`) "g. the excerpt is still cut silently at 500 characters (Plan D's open item)."
  - (`:780`) "h. retrieved_at is stamped from the wall clock (mcp-read/src/ops_mcp_read/server.py:95) instead of
    app.current_time(); return the definer's instant as one more output column, i.e. a new revision 0012 (0011 is
    frozen) (Plan L final review, M4)."
- `handoff/BUILD_BACKLOG.md:106` repeats the instructions unchecked (`- [ ]`); `:109`: "Debts aimed at T16
  (asset_scope, asset tools and asset-sim; the vector_exact -> mode=vector translation; mcp-read's tool arguments and
  UNSUPPORTED_MODE order; R029; the run's asset type; R028; the 500-character excerpt cut; retrieved_at from
  app.current_time(), revision 0012): see T16's review_notes in `handoff/tasks.json`."
- `SESSION_STATE.md:5`: "**Next task:** Plan M = T16 (the read tools, `asset_scope` and asset-sim), on branch `plan-m`
  from `main`." `:13`: "Next is Plan M = T16 (the read tools and asset-sim, the earliest dependency-satisfied PLANNED
  task in `handoff/tasks.json`; T18 and T23 are unblocked too; T19 and T41 wait on owner steps)." `STATUS.md:323`:
  "Next: Plan M = T16 (read tools, asset_scope, asset-sim) on branch plan-m from main."
- `tasks.json:4` note: "A proposed erratum awaiting the owner's decision does not change a task's status; a task met
  'subject to' an erratum stays DONE."

### 1.2 Acceptance-matrix rows owned by T16 (`handoff/acceptance-matrix.json`)

- **R028 (:516-530)** — M05 / security; "Read tools enforce current source and asset access"; `blocking_for_v1: true`;
  `implementation_status: NOT_IMPLEMENTED_OR_NOT_TARGET_VERIFIED`; `evidence_status: NOT_RUN`; `evidence_paths: []`;
  expected_evidence (verbatim): "Alpha requests B22 or revoked procedure; no forbidden data reaches the model.";
  owners `T16` only; suggested_test `tests/acceptance/test_r028_read_tools_enforce_current_source_and_asset_acce.py`.
- **R029 (:531-545)** — M05 / security; "Unexpected tools and invalid results fail closed"; blocking;
  `NOT_IMPLEMENTED_OR_NOT_TARGET_VERIFIED` / `NOT_RUN`; expected_evidence (verbatim): "Alter discovered tool/schema;
  return error-flagged/malformed/oversized payload; no success assumption."; owners `T16`; suggested_test
  `tests/acceptance/test_r029_unexpected_tools_and_invalid_results_fail_closed.py`.
- `handoff/ACCEPTANCE.md:34-35` (the superseded 1.0 snapshot, `:3`) carries the same two lines unchecked.
- Matrix note (`acceptance-matrix.json:3`): "suggested_test paths are targets to implement"; `RECORDED_LOCALLY` =
  the tests in evidence_paths pass in `scripts/check.py` and CI; `RECORDED_LOCALLY_LIVE` = passes against the running
  dev profile with `OPS_LIVE=1`, collected but skipped by `check.py` and CI. `tests/acceptance/` does not exist.

### 1.3 R131 and the rows that name assets, alerts, freshness or membership

- **R131 (:2264-2288)** — M05; owners `T15`, `T47` (not T16); `IMPLEMENTED_LOCALLY_VERIFIED`,
  `RECORDED_LOCALLY_LIVE`; expected_evidence (`:2269`): "mcp_read can EXECUTE only resolve_invocation, asset_scope,
  search_procedures_scoped; mcp_exec only resolve_invocation, grant_execution, mark_sent, record_outcome,
  request_abort, lookup_action (pg_proc ACL test); an execute/recover handle at mcp-read and a read handle at
  mcp-write are rejected; incident-sim rejects mcp-read's token." Note (`:2287`, start): "Read half (Plan J, T15):
  mcp_read can EXECUTE current_time (erratum 15), resolve_invocation and, since Plan L (T17),
  search_procedures_scoped, and nothing else in app (asset_scope joins with T16; errata 72 and 96; the read half is
  met subject to the owner's decision on erratum 96) …"; it also records "incident-sim answers ops-mcp-read's
  workload token 403 at all three routes" and "That mcp-read cannot reach incident-sim over the network is T30's
  Docker network test." Evidence paths include `tests/e2e/test_mcp_read_t15_live.py` and
  `tests/e2e/test_migration_0011_live.py`.
- **R025 (:449)** T15: "A real independent MCP client crosses the network"; `NOT_IMPLEMENTED_OR_NOT_TARGET_VERIFIED`,
  `RECORDED_LOCALLY_LIVE`. **R026 (:471-490)** T15: "MCP rejects wrong audience or browser token passthrough"; its note
  records that an "ops-mcp-read token (aud asset-sim)" gets 401 at mcp-read. **R027** T15 (handle binding), **R085
  (:1420)** T15: "Tool allowlist is server-derived and bound to the workload client" — all
  `IMPLEMENTED_LOCALLY_VERIFIED` / `RECORDED_LOCALLY_LIVE`.
- **R013 (:220)** T11: "Current membership overrides old roles"; expected "Revoke membership while session/token
  remains otherwise valid; new protected operations fail."; `RECORDED_LOCALLY_LIVE`.
- **R086 (:1442)** T11: "IdP disable and back-channel logout end application authority"; expected "Disabled user: next
  decision-class mutation 401, grants blocked within 60 s; …"; `RECORDED_LOCALLY_LIVE`.
- **R018 (:319)** T12: "Relative intervals resolve once and ambiguity clarifies"; expected "Retry after clock advance
  and conflict text/form asset; interval remains fixed and ambiguity pauses."; `RECORDED_LOCALLY_LIVE`.
- **R099 (:1688)** T17: "Evidence corpus is large enough to measure retrieval" (">=6 assets … tenant/alert UUID
  fixtures"); `IMPLEMENTED_LOCALLY_VERIFIED`, `RECORDED_LOCALLY`.
- **R116 (:2002)** T21: "Stale asset observations block the grant"; expected "Asset status older than 5 minutes at
  grant -> BLOCKED_REVIEW."; `NOT_RUN`.
- **R110 (:1899)** T22, **R125 (:2153)** T21/T22, **R119 (:2050)** T22: the asset guard (same asset/interval);
  `NOT_RUN`. **R114 (:1963)** T20: "Read-only answers complete as ANSWERED without proposals"; `NOT_RUN`.
- **R007** T09 (tenant RLS) and **R106** T09 ("Definer functions are hardened and tenant-isolated by explicit
  policies": "search_path fixed, PUBLIC execute revoked, GRANT EXECUTE only to named callers, owner app_definer is not
  a table owner, FORCE RLS and the AM-20.5 policy text present per table; cross-tenant access through functions
  fails."): `IMPLEMENTED_LOCALLY_VERIFIED`, `RECORDED_LOCALLY_LIVE`.

### 1.4 Tasks that consume T16, and neighbours

- **T20** (`tasks.json:851-882`, M07, PLANNED) depends_on `["T19", "T14", "T16"]` (`:855-859`): "Nodes per AM-12 incl.
  the route_request graph router … retrieval before drafting; …" Owns R022, R038, R042, R091, R108, R114, R129. DoD 1:
  "Trace shows MCP reads complete before drafting." T20 is the only task whose `depends_on` names T16.
- **T21** (`:883-923`, M08) depends_on `["T20", "T11"]`: "… grant_execution final gate with UNIQUE(run_id),
  proposal/run binding, asset freshness and asset guard." Owns R045, R116, R125 and others. Review notes: "Asset guard
  via pg_advisory_xact_lock(tenant, asset) first in lock order …"; "Manual proposals must reference assets/evidence of
  the caller's tenant (alpha proposal for B22 -> 404, nothing written)."
- **T18** (`:783-800`, M06 "Vector retrieval", PLANNED) depends_on `["T17"]`: "nomic-embed-text with
  search_document:/search_query: prefixes (tested); record model, dimension, digest; exact search with the same
  filters; comparison report vs lexical." R034. DoD: "reports/retrieval-comparison.md with recall@k for both methods,
  denominators and CIs."; "Prefix application asserted by a test." No `review_notes`.
- **T19** (`:820-850`, M07, PLANNED) depends_on `["T07", "T17", "T02", "T03", "T44"]`: writes "the run manifest
  {run_id, model_route, model_digest, prompt_version, corpus_version, retrieval_mode}". DoD 2: "Injected source cannot
  add tools or authority; invalid output -> repair -> controlled failure." T19 waits on owner steps (T02, T03).
- **T23** (`:963-980`, M09, PLANNED) depends_on `["T17"]`: "~60 dev cases over the expanded corpus with gold labels;
  deterministic graders for schema, citations and abstention; …" R111. Does not name T16.
- **T41** (`:801-819`, M06, `external_approval_required: true`) depends_on `["T03", "T17"]`: labels "against the frozen
  T17 corpus version; … Corpus changes after this require re-labelling."
- **T30** (`:1125-1151`, M12) review note (`:1149`): "Docker network tests include: mcp-read cannot reach incident-sim;
  mcp-write cannot reach asset-sim; worker cannot reach either sim."
- **T15** review notes (`:691-695`): "mcp-read reads asset data via asset_scope + asset-sim, and procedures via
  search_procedures_scoped; it never has table access." (`:693`); the Plan J note defers "asset_scope, the asset tools
  and asset-sim -> T16; search_procedures_scoped and the governed store -> T17/T16" and ends "Since Plan L (T17) the
  read half also holds search_procedures_scoped, met subject to the owner's decision on erratum 96." (`:695`).
- **T17** review note (`:746`) defers "asset_scope, the asset tools, asset-sim, the run's asset type and the
  membership re-check at read time -> T16"; "embeddings, vector mode and another chunk window -> T18"; "tuning the
  minimum rank -> T18"; and records "R131's read half is met subject to the owner's decision on erratum 96 (asset_scope
  still arrives with T16)."
- **T04** (`:274`): "ADR-0001 layout (core/, api/, worker/, mcp-read/, mcp-write/, asset-sim/, incident-sim/ with
  trust-boundary READMEs) …" (DONE; that is where the asset-sim stub comes from).

---

## 2. Spec passages that bind T16

### 2.1 AM-15 tool contracts (SA:327–358), verbatim where it binds

- Tool table, read row (SA:333): "| `get_asset_status`, `get_recent_alerts` (absolute interval, `next_cursor`),
  `search_procedures` | **mcp-read** | `investigate` and `resume_input` jobs (read handles) |".
- SA:338: "Every job has exactly one `type`. Allowed tools are derived from type plus run state plus attempt state.
  **A handle is bound to one server:** `investigate`/`resume_input` handles are accepted only by mcp-read;
  `execute`/`recover` handles only by mcp-write (R131)."
- Job table (SA:342–343): `investigate` — "read tools" in "QUEUED, RETRIEVING, DRAFTING"; `resume_input` — "read
  tools" in "AWAITING_INPUT → QUEUED".
- SA:348: "Read tools are `get_asset_status`, `get_recent_alerts` and `search_procedures`. … For `search_procedures`
  in vector mode, mcp-read computes the query embedding with `nomic-embed-text` (`search_query:` prefix) and passes it
  to `search_procedures_scoped` [R6]."
- SA:350: "Every tool has an input JSON Schema in `schemas/tools/`. Arguments that supply a role, tenant, actor,
  approval or destination are rejected."
- SA:351–355: "**The envelope must agree with the data:** `status=ok` only for a read with data, or `SUCCEEDED`;
  `status=outcome` for `UNKNOWN` / `CONFLICT` / `FAILED_NO_COMMIT`, with `data.action_id` required; for an
  **authenticated, authorized** caller, `status=error` only before any grant exists; authentication and authorization
  failures always return a plain safe error, never with an `action_id`."

### 2.2 AM-20 rows for the read path

- SA:400 (AM-20.1): "| `mcp_read` | yes | mcp-read; read-path functions only |".
- SA:437 (AM-20.2 note): "`mcp_read`, `mcp_exec` and `operator` have **no table grants**; the right-hand column is
  only for `test_harness`." The grant table has **no `assets` or `alerts` row** (SA:410–434); `memberships` is `sel`
  for `api`, `worker`, `app_definer` and `sel, upd(active, permission_version, synced_at)` for `sweeper` (SA:412).
- SA:446 (AM-20.3 header): "All functions: `SECURITY DEFINER`, owner `app_definer`, `SET search_path = app, pg_temp`,
  `SET app.tenant_id = ''` as a function attribute. Each migration that creates one runs, in the same transaction,
  `REVOKE ALL ON FUNCTION … FROM PUBLIC` and then `GRANT EXECUTE … TO <exactly the callers listed below>` [R6-H2].
  Every function first resolves `tenant_id` through `run_directory` (or the handle) and sets `app.tenant_id` with
  `set_config(name, value, true)` (**transaction-local** …) before touching tenant rows, takes locks in the AM-12
  order, and raises `authority_violation` when `session_user` is not an allowed caller. Reads of the setting use
  `NULLIF(current_setting('app.tenant_id', true), '')::uuid` [R7]."
- SA:459: "| `resolve_invocation(raw_handle, client_azp)` | `mcp_read`, `mcp_exec` | the header value and the token's
  `azp` | `invocation_context` FOR SHARE → `run_lease` FOR SHARE | Hashes the handle inside; checks azp binding,
  **that the handle's server matches the calling role** …, expiry, current run fence; returns `{run_id, tenant_id,
  job_type, run_state, attempt_state, allowed_tools}` with the allowlist derived per AM-15 | none |" (amended by
  errata 19, 53, 77; §4).
- **SA:460**: "| `asset_scope(raw_handle)` | `mcp_read` | handle | as above | Returns the run's `tenant_id`,
  `asset_id`, `[start_at, end_at)` for forwarding to asset-sim | none |".
- **SA:461**: "| `search_procedures_scoped(raw_handle, query, query_embedding vector(768) NULL, asset_type, limit,
  mode)` | `mcp_read` | handle, text query, optional embedding computed by mcp-read with the `search_query:` prefix |
  as above | Lexical (`mode=lexical`) or exact vector (`mode=vector`, requires the embedding) search over approved,
  effective, tenant-permitted chunks; returns IDs, versions, section, hash, excerpt | none |" (amended by erratum 93:
  `client_azp` second; §4).
- SA:462 (`grant_execution`, for T21): "… requester and reviewer currently active; not cancelled; asset freshness (5
  min); **asset guard (AM-13)** …".
- SA:474: "Internal helpers (`_canonicalize`, `_asset_guard`, `_allowlist`) are not granted to any role."
- SA:496: "`invocation_context(handle_sha256 PK, run_id, job_id, server ∈ {read, write}, fence, azp, expires_at,
  revoked_at)`. `resolve_invocation` derives `job_type` from the referenced `jobs` row and `server` from that type …;
  it never trusts the worker-written `server` column alone [R7]."
- SA:510/520/523 (AM-20.5): the RLS table list has no `assets`/`alerts`; `tenant_isolation` and the two `sweeper_*`
  policies are "the only policies"; `tenants` has no RLS.

### 2.3 asset-sim, the workload token and the forwarded context

- SA:78 (AM-01): "| `asset-sim/` | Synthetic asset/alert API (deterministic, injected clock) |"; SA:76: "| `mcp-read/` |
  Authenticated MCP server for read tools only (asset status, alerts, procedure search); DB role `mcp_read` |"; SA:70:
  each process gets "its own `pyproject.toml`, `Dockerfile`, `tests/` and `README.md`".
- **SA:555** (AM-20.7 item 6): "Keycloak "Hardcoded audience" mappers set `aud` to the **resource URLs** of mcp-read
  (`MCP_READ_RESOURCE_URL`) and mcp-write (`MCP_WRITE_RESOURCE_URL`) and to `incident-sim`; each is a parameter, not a
  hard-coded container name. asset-sim trusts only the mcp-read workload token and the tenant/asset context it
  forwards, and applies its own tenant filter; incident-sim trusts only mcp-write."
- SA:557: "Both MCP servers use a custom `TokenVerifier` that checks iss, aud ∋ its own resource URL, azp ∈ its allowed
  workload clients, and exp." SA:558: "Tests cover a missing `aud`, a wrong `aud`, and a browser token."
- `docs/adr/ADR-0001-deployable-units-as-top-level-directories.md:31`: "**Network boundaries stay where §3 puts them:**
  browser → api, worker → mcp-read / mcp-write, mcp-read → asset-sim, mcp-write → incident-sim, worker → Ollama
  (ADR-0003)."; `:17`: each process has "its own `pyproject.toml`, `Dockerfile`, entrypoint, `tests/` and a
  `README.md` stating ownership and trust"; `:25`: "asset-sim/     synthetic asset/alert API"; `:41`: "The two
  synthetic services (`asset-sim/`, `incident-sim/`) are separate on purpose. The destination needs an independent
  database and credentials (§14). The read API does not."
- `docs/adr/ADR-0003-routers-and-read-write-mcp-split.md:18`: "`mcp_read` can execute only `resolve_invocation`,
  `asset_scope` and `search_procedures_scoped`; … Only mcp-write can reach incident-sim; only mcp-read can reach
  asset-sim."
- BS:362: "The MCP server validates the workload token, resolves the handle …, checks workload binding/expiry/current
  lease fence, then loads current requester/tenant policy from the stored run. Ignore or reject tool arguments that
  attempt to supply role, tenant, actor, approval or destination authority." BS:363: "Tool allowlists are server-side.
  A read invocation cannot call a write tool." BS:364: "Rotate/revoke handles on lease loss, cancellation, policy
  change and completion. … Use TLS outside localhost and never forward the handle to the destination."
- BS:401: "The server derives tenant and action context from trusted records. … Server-side role rechecks happen at
  read and write boundaries, not only during tool discovery."
- BS:405: "Create separate FastAPI endpoints for synthetic asset/alert reads and incident/receipt operations. Read data
  is deterministic under an injected clock/seed. Fault hooks are test-harness-only and inaccessible in a public or
  normal web profile. Hooks must support response loss after commit, timeout before acceptance, delayed receipt
  visibility, malformed response, mismatching receipt hash, rate limit, transient unavailable, definitive no-commit
  failure and concurrent same-key submission."
- BS:146 (diagram): "MCP --> Assets[Synthetic asset and alert API]"; BS:646 (§22 caller table): "| MCP | app/evidence DB
  for authorized resolution, synthetic services, Keycloak metadata, telemetry |".
- BS:161: "Use fictional tenants **alpha** and **beta**, with assets **A17** and **B22**. … resource-specific evidence
  access still applies. No cross-team visibility."
- No spec line, ADR, setting or script names a port, a host name or a URL for asset-sim (§3.5).

### 2.4 The business tools (BS §10) and the tool-result contract

- BS:378: "Use a real remote client in integration tests; an in-process call is not sufficient."
- BS:384: "| `get_asset_status` | `asset_id` | Permitted synthetic status, asset revision, observed_at, data_source; no
  equipment mutation |"
- BS:385: "| `get_recent_alerts` | `asset_id`, `start_at`, `end_at`, bounded `limit` | Fixed half-open interval, ordered
  alerts with timestamps/revisions; `truncated` flag and next cursor where needed |"
- BS:386: "| `search_procedures` | bounded `query`, optional `asset_type`, `limit` | Only approved, effective, currently
  permitted chunks; IDs, versions, section, source hash, excerpt, retrieval mode |"
- BS:395: "A model-facing tool adapter, if added, receives only permitted read tools. … Do not expose a generic
  `send_message`, `execute_sql`, `run_shell`, `fetch_url`, "approve" or role-management tool."
- **BS:399**: "Use the target `tool_result` schema. Carry `tool_name`, request correlation ID, `status`, bounded typed
  `data` for the known tool, safe `error` when present, observed timestamp and truncation metadata. Validate
  tool-specific nested schemas, not just the envelope. Check both transport errors and the SDK's tool-error flags; a
  protocol-success response can still represent application failure. Preserve error classification and never feed
  raw stack traces or credentials to the model."
- BS:589 (§19 item 4): "MCP network tests: independent process/client, actual negotiation/list/call, workload
  audience, invocation scope/replay, malformed results, server policy, no direct bypass."
- AM-80 (SA:761): "| `tool-result.schema.json` | `status=outcome`; remove `unknown`; envelope/data agreement;
  `action_id` required on outcomes for authorized callers; `next_cursor`; `abort_incident` result shape |"; SA:766:
  "| `schemas/tools/*.json` | Create input schemas for all six tools |"; SA:775: "| `examples/draft-valid.json` /
  `tool-get_recent_alerts-valid.json` | Make the alerts consistent (the draft says "two warnings", the alerts example
  returns `[]`) |"; SA:777: "| `data/handoff-fixtures/` | Tenant UUID mapping; alert UUIDs + revisions; per-section
  hashes (expanded in T17) |".

### 2.5 Absolute time, the clock and freshness

- BS:389: "The target uses absolute timestamps for alerts so retries keep the same interval. The historical `hours`
  argument is a reference-only input; convert at the admission boundary, not repeatedly inside retrieval."
- BS:297: "Resolve "last 24 hours" once against an injected server clock into `[start_at, end_at)`; store the interval
  so retrying does not move the investigation" (line truncated here). BS:547: "| Investigation interval | 1–168 hours,
  resolved once to absolute UTC |".
- SA:157: "Every lease, expiry, freshness and deadline comparison uses `clock_timestamp()`, evaluated **after** the
  relevant row locks are acquired. Never use `now()`, which is the transaction start time." SA:158: "Tests inject time
  through the database function `app.current_time()`." SA:159: "**Only the Alembic branch `testclock` creates
  `app.test_clock`** … In dev and demo it does not exist, and the function returns `clock_timestamp()` unchanged."
- SA:528 (AM-20.6): "Every service, not only the bootstrap, asserts at start that the table is absent outside the test
  profile."
- **BS:476** (§13): "Freshness proposal: a 15-minute proposal expiry; exact source version still approved/effective;
  asset status observation no older than 5 minutes at grant. The investigation interval remains fixed. If freshness
  fails, stop at BLOCKED_REVIEW and request new evidence/revision." BS:559: "| Proposal / asset freshness | 15-minute
  proposal expiry / status observed within 5 minutes at grant |".
- BS:419: "The model receives a bounded evidence bundle: fixed asset/interval, status observation, alert records or
  aggregate plus truncation notice, permitted excerpts, source IDs/versions/hashes and retrieval timestamp. It cannot
  read the whole corpus or database."
- SA:377 (AM-16): ""Evidence sufficient?" is a code rule (at least one permitted status observation and at least one
  effective procedure chunk, all within freshness), never a model judgement".
- BS:417: "Filter before results enter the model. Apply approved/effective/tenant/resource-access constraints to
  lexical and vector retrieval. … Start `top_k=5`, allow up to 8 source references under the context budget".
- BS:425: "The final execution gate rechecks document versions and proposal freshness."

### 2.6 Milestone rows and ordering

- `tasks.json:65-76` M05 "MCP read and write servers and governed corpus", `required_for_v1: true`, `PLANNED`.
  SA:709: "T17 moves to M05 ahead of T16. M05 becomes "MCP boundary and governed corpus"." SA:689: "T15 becomes
  mcp-read; new **T47** builds mcp-write (R030, R131). T16 keeps the read tools; recovery tools move to T47."
- BS:706 (1.0 table, superseded by SA:43): "| M05 — Remote MCP | Authenticated server/client, invocation context, four
  business tools plus restricted reconciliation | Real transport discovery/calls, audience/replay/scope errors, no
  direct bypass |".
- AM-50 (SA:641, SA:644): "at least 12 authored documents …, at least 6 assets, 2 tenants;" "tenant slugs map to seeded
  UUIDs, and alert IDs are UUIDs with revisions;" SA:645: "embeddings use `nomic-embed-text` with the
  `search_document:` and `search_query:` prefixes, with a test that they are applied."
- AM-30 (SA:571–573): MCP protocol revision 2026-07-28; "Tests check per-request version validation and mismatch
  rejection"; imports `from mcp.server.mcpserver import MCPServer, Context` and `from mcp import Client`; pgvector-python
  0.5.0 (SA:584).

---

## 3. The tree as it is (branch `plan-m`, `4be745a`)

### 3.1 `asset-sim/` (a stub)

`git ls-files asset-sim` lists exactly three files:
- `asset-sim/pyproject.toml` (16 lines): `name = "ops-asset-sim"`, `version = "0.0.1"`, `description = "Synthetic
  asset/alert API"`, `requires-python = ">=3.13"`, `dependencies = ["ops-core"]` (no FastAPI, no uvicorn), hatchling,
  `packages = ["src/ops_asset_sim"]`.
- `asset-sim/README.md` (12 lines): "## Owns / Deterministic asset and alert data under an injected clock"; "## Trusts /
  Only mcp-read's token and forwarded tenant/asset context"; "## Never / Any write; any other caller".
- `asset-sim/src/ops_asset_sim/__init__.py` (3 lines): docstring `"""Synthetic asset/alert API"""`, `__version__ =
  "0.0.1"`.
- (An untracked `__pycache__/__init__.cpython-313.pyc` exists on disk.) No `__main__.py`, no app, no `tests/`, no
  `Dockerfile`.
- Wiring that already names it: root `pyproject.toml:12` (`"ops-asset-sim"` dependency of the virtual root), `:26`
  (`ops-asset-sim = { workspace = true }`), `:31` (workspace `members`); `scripts/check.py:34` (`"asset-sim/src"` in
  `MEMBER_SRC`, type-checked by mypy); `tests/plan_a/test_layout.py:19` (`"asset-sim": "ops_asset_sim"`).
- The template sibling `incident-sim/` (no `tests/` either) has `pyproject.toml:6` `dependencies = ["ops-core",
  "fastapi>=0.142,<1", "uvicorn>=0.54,<1"]`, `src/ops_incident_sim/__main__.py` (serves `production_app()` on
  `127.0.0.1:OPS_INCIDENT_SIM_PORT`, default 8090, through `uvicorn.Server` on a selector loop on Windows, after
  `redaction.install()`), `app.py:281-288` `production_app()` building `TokenVerifier(issuer=kc.issuer,
  audience="incident-sim", allowed_azp=frozenset({"ops-mcp-write"}), jwks_url=kc.jwks_url)`; `app.py:143-148` maps
  `WrongAudience` → 403 `FORBIDDEN` "token is not for this service" and other `TokenRejected` → 401 `UNAUTHENTICATED`
  with `WWW-Authenticate: Bearer`; `/health/live` and `/health/ready` (`:166-171`); fault routes only under the test
  profile (`:122-127`, `:248-252`).

### 3.2 mcp-read (`mcp-read/src/ops_mcp_read/server.py`, 326 lines)

- Module docstring (`:1-11`): "One tool, `search_procedures`, answered from the governed corpus in the database through
  `search_procedures_scoped` since T17 (mcp-read reads no file); the asset tools arrive with T16."
- `HANDLE_BINDING = persistence.HANDLE_BINDING` (`:45`). `ToolResult(TypedDict)` (`:48-57`): `tool_name, request_id,
  status, observed_at, truncated, data, error`. `stamp(value)` (`:60-62`): UTC, seconds-only, `Z`. `tool_error(code,
  message)` (`:65-67`): `{"code", "message", "retryable": False}`. `envelope(tool_name, *, data=None, error=None)`
  (`:70-80`): fresh `request_id` (uuid4), `status` `"error"` or `"ok"`, **`observed_at = stamp(datetime.now(UTC))`**
  (`:76`), **`truncated: False`** always (`:77`).
- `search_response(found, *, now)` (`:83-102`): per hit `evidence_id, document_id, version, section, content_sha256,
  excerpt, effective_from` and **`"retrieved_at": stamp(now)` (`:95`)**; `data = {"results", "retrieval_mode":
  "lexical", "corpus_version": found.corpus_version}` (`:101`); the rank is dropped ("the contract has no score",
  `:84-85`).
- `McpVerifier` (`:116-145`): refuses a token whose `aud` lacks the server's resource URL (`:135-136`), then stamps
  `resource`. `without_default` (`:148-152`); `strict_tool(fn)` (`:155-169`): subclasses the SDK-derived argument
  model with `ConfigDict(arbitrary_types_allowed=True, extra="forbid", strict=True)` and regenerates `tool.parameters`.
- `State` (`:172-177`): `session: persistence.Session | None`, `verifier: Verifier`.
- `build_server(state, *, issuer, resource_url)` (`:180-236`) registers **one** tool, `tools=[strict_tool(
  search_procedures)]` (`:235`). The tool's arguments (`:183-191`): `query: Annotated[str, Field(min_length=1,
  max_length=500)]`, `limit: Annotated[int, Field(ge=1, le=8)]`, `mode: Literal["lexical", "vector_exact"]`, `ctx:
  Context`, `asset_type: Annotated[str, Field(min_length=1, max_length=40, json_schema_extra=without_default)] = ""`.
  Body order: missing token/handle/session → `INVALID_HANDLE` "missing invocation handle" (`:197-198`); unit 1
  `persistence.resolve_invocation(conn, handle=..., azp=token.client_id, tool=ToolName.SEARCH_PROCEDURES)`
  (`:199-203`), `HandleRejected` → `INVALID_HANDLE` (`:204-205`); **then** `if mode != "lexical":` →
  `UNSUPPORTED_MODE` "vector_exact arrives with T18" with `# TODO(T16): translate vector_exact to mode=vector once T18
  stores embeddings (erratum 3).` (`:206-208`) — i.e. the mode check runs after the handle resolution and before any
  search; unit 2 `persistence.search_procedures(conn, handle=..., azp=..., query=..., asset_type=asset_type or None,
  limit=...)` (`:213-222`); `HandleRejected` → `INVALID_HANDLE`, `Refused` → `tool_error("REFUSED", exc.code)`
  (`:223-226`); `return search_response(found, now=datetime.now(UTC))` (`:227`).
- `build_app` lifespan (`:243-263`): connects as `Role.MCP_READ`, `assert_clock_profile`, `assert_function_text(conn,
  *HANDLE_BINDING)` (0009), `assert_function_text(conn, *persistence.GOVERNED_CORPUS)` (0011) (`:247-251`), loads JWKS.
  Routes `/health/live`, `/health/ready` (`:265-281`), `Mount("/", app=ProtocolVersionGuard(mcp_app))` (`:284`).
- `read_verifier(kc, urls)` (`:290-301`): `TokenVerifier(issuer=kc.issuer, audience=urls.mcp_read_resource,
  allowed_azp=frozenset({settings.workload_client_id()}), jwks_url=kc.jwks_url, token_type="Bearer")`.
- `production_app()` (`:304-309`), `serve_app(app, port)` (`:312-319`, `127.0.0.1`), `serve()` (`:322-326`) on
  `OPS_MCP_READ_PORT` default 8081. mcp-read holds **no outbound HTTP client and no workload token source** today.
- `mcp-read/pyproject.toml:6`: `dependencies = ["ops-core", "mcp==2.3.0", "uvicorn>=0.54,<1"]` (no httpx2 directly;
  core depends on `httpx2>=2.13,<3`, `core/pyproject.toml:6`). `mcp-read/README.md:15-16` "Trusts … the definer
  functions `resolve_invocation` and `search_procedures_scoped` (T17; `asset_scope` arrives with T16)".
  `docs/runbooks/mcp-read.md:47-48` documents the tool's arguments; `:87`: "The asset tools and asset-sim (T16), vector
  search (T18), TLS and container host names (T30)."

### 3.3 Core modules mcp-read uses

- **`ops_core.persistence`**: `PersistenceError` (`:39`), `NotFound` (`:43`), `HandleRejected` (`:51`), `Refused`
  (`:64-69`, `code` = the DETAIL), `OC_CODES` (`:72-81`: OC001 AuthorityViolation, OC002 NotFound, OC003
  VersionConflict, OC004 IllegalTransition, OC005 Refused, OC006 EventRuleViolation, OC007 HashMismatch, OC008
  HandleRejected), `translate` (`:84-94`: OC008 → one fixed message), `assert_relation` (`:170`), `HANDLE_BINDING`
  (`:183`), `WRITE_PATH` (`:187`), `GOVERNED_CORPUS` (`:191-194`: `("app.search_procedures_scoped(text, text, text,
  public.vector, text, integer, text)", "ts_rank_cd(c.search, v_query)")`, with the rule "a later revision that
  re-creates the function keeps this text or changes it here in the same commit"), `assert_function_text` (`:197`),
  `Invocation` (`:393-403`: `run_id, job_id, job_type, tenant_id, conversation_id, run_state, attempt_state` — no
  asset or interval), `allowed_tool(job_type, run_state, attempt_state, tool)` (`:406-424`), `resolve_invocation(conn,
  *, handle, azp, tool)` (`:432-450`: `SELECT * FROM app.resolve_invocation(%s, %s)`), `Procedure` (`:452-465`, with
  `rank`), `Procedures(corpus_version, results)` (`:467-473`), **`search_procedures(conn, *, handle, azp, query,
  asset_type, limit)` (`:476-507`)**: `SELECT * FROM app.search_procedures_scoped(%s, %s, %s, NULL, %s, %s,
  'lexical')` — the embedding is the literal `NULL` and the mode the literal `'lexical'` (`:488-492`); `current_time`
  (`:628-639`: `SELECT app.current_time()`); `mint_handle(conn, *, run_id, job_id, server, azp, fence,
  ttl_seconds=60)` (`:1016`).
- **`ops_core.jobs`**: `Tool(StrEnum)` (`:19-26`) with `GET_ASSET_STATUS = "get_asset_status"`, `GET_RECENT_ALERTS =
  "get_recent_alerts"`, `SEARCH_PROCEDURES`; `Server` (`:30`); `JobType` (`:37`); `_READ = frozenset({GET_ASSET_STATUS,
  GET_RECENT_ALERTS, SEARCH_PROCEDURES})` (`:68`); `JOB_RULES` (`:70`): `investigate` → `_READ` in {QUEUED, RETRIEVING,
  DRAFTING}, `resume_input` → `_READ` in {AWAITING_INPUT, QUEUED}; `ATTEMPT_STATES` (`:119`). The allowlist already
  admits the two asset tools for read handles.
- **`ops_core.routing`**: `RunManifest` (`:350-370`), `retrieval_mode: Literal["lexical", "vector_exact"]` with the
  comment "Plan ruling 3: the externally visible mode keeps the delivered `vector_exact` …; AM-20.3's `mode=vector` is
  the SQL function's argument value." and **`# TODO(T16): mcp-read, the caller of `search_procedures_scoped` (T17),
  translates `vector_exact` to `mode=vector`.` (`:362`)**. `corpus_version: str = Field(min_length=1,
  max_length=100)`.
- **`ops_core.privileges`** (318 lines): `RUNTIME_ROLES` (`:33`), `GRANTS` (`:73`; `memberships` `:75-80`; the corpus
  tables `:143-148`; no `assets`/`alerts` key), `RLS_TABLES` (`:152-171`), `NO_RLS` (`:176-188`), `TENANT_EXPR` (`:193`),
  **`DEFINER_FUNCTIONS` (`:197-218`)**: `"current_time": ("", RUNTIME_ROLES)` (`:198`), `"resolve_invocation": ("text,
  text", ("mcp_read", "mcp_exec"))` (`:207`), `"search_procedures_scoped": ("text, text, text, public.vector, text,
  integer, text", ("mcp_read",))` (`:208-209`, comment "SA:461 with the caller's azp second, as the write path since
  T47 (erratum 93)"); **no `asset_scope` entry**. `HELPER_FUNCTIONS` (`:220-231`: `_authority`, `_tenant_of_run`,
  `_tenant_of_action`, `_resolve_handle`, `_latest_attempt`, `_grant_row`, `_append_event`, `_transition`,
  `_dispatch_seconds`, `_min_rank`). `grant_statements` (`:243`), `rls_statements` (`:276`),
  `function_grant_statements(name, roles=None, *, args=None, callers=None)` (`:295-318`: REVOKE FROM PUBLIC then GRANT
  EXECUTE; `KeyError` for an unknown name).
- **`ops_core.corpus`** (494 lines, standard library only, `:1-20`): `ASSETS = "assets.json"` (`:46`), `LOCK =
  "corpus.sha256"` (`:47`), `META = "meta.json"` ("deliberately not in the lock", `:48`), `RELEASES = {"corpus-1":
  "81f50c2b8623675f9c899033cba748f289b7f4024003385aabc8a95147b71862"}` (`:67-69`), `load_assets(root)` (`:209-275`:
  checks `asset_types`, assets with exactly `{"asset_id", "tenant", "asset_type", "name"}`, alerts with a string `id`,
  a known `asset_id`, an integer `revision >= 1`; it does not check any other alert key), `lock_text` (`:278-284`:
  **the lock covers the catalog, `assets.json` and every document**), `check_lock` (`:287-305`: "a new lock without a
  new version fails the release check"), `load` (`:308`), `returnable` (`:474`). The module docstring (`:13-16`):
  "`corpus-1` is the version T41 labels the holdout against (ruling 23): any change to a locked file after T41 needs a
  new version and re-labelling."

### 3.4 The asset and alert data that exist

- **`data/corpus/assets.json`** (27 lines, authored, locked): `"asset_types": ["compressor", "conveyor", "pump"]`;
  six assets, each `{asset_id, tenant, asset_type, name}`: `A17` alpha pump "Alpha transfer pump A17", `A21` alpha
  compressor, `A30` alpha conveyor, `B22` beta pump "Beta feed pump B22", `B25` beta compressor, `B31` beta conveyor;
  seven alerts, each `{id, asset_id, kind, severity, raised_at, revision}`: `A17-seal-001` (seal_leak, warning,
  2026-10-05T14:00:00Z, rev 1), `A17-seal-002` (seal_leak, warning, 2026-10-06T08:30:00Z, rev 2), `A21-temp-001`
  (high_discharge_temperature, critical, 2026-10-04T22:10:00Z, rev 1), `A30-noise-001` (noise, info,
  2026-10-03T09:45:00Z, rev 1), `B22-vibration-001` (vibration, warning, 2026-10-05T11:20:00Z, rev 1), `B25-oil-001`
  (oil_condition, warning, 2026-10-02T16:05:00Z, rev 3), `B31-guard-001` (guard_open, critical, 2026-10-06T07:15:00Z,
  rev 1). **No asset carries a status, state, revision or `observed_at`**; alerts carry `kind`/`severity`/`raised_at`,
  not the contract's `code`/`message`/`occurred_at` (§3.7).
- **`data/corpus/meta.json`** (generated by `scripts/gen_corpus_meta.py`, not in the lock): keys `corpus_version,
  lock_sha256, meta_version, tenants, assets, alerts, sections`; `tenants`: alpha
  `3ea79c95-914c-52cb-9d10-c4e19dda8ff7`, beta `5ab45c2c-1e12-5a0c-a2b9-66cd2ff05201`; `assets[]`: `{asset_id, tenant,
  tenant_id, asset_type}`; `alerts[]`: `{id, asset_id, alert_id, revision}` with `alert_id` = uuid5 of `alert/<id>`
  under the seed namespace (`gen_corpus_meta.py:4-6`, `:75`), e.g. `A17-seal-001` → `6699502e-a981-5959-9f24-
  6df6bd3d3ac5`, `B22-vibration-001` → `19cb1a10-9a56-5d2d-b67d-3ab044451941`.
- `docs/retrieval.md:17`: "| `assets.json` | asset types, assets, alerts with revisions (T16's asset-sim serves them) |
  authored |"; `:33`: "Changing a document, the catalog or the assets file without a new lock" fails.
- **`data/handoff-fixtures/observations.json`** (the delivered 1.0 fixture, `fixture_version` `handoff-1`, `clock`
  `2026-10-06T12:00:00Z`): two assets with `state`/`revision`/`observed_at` (`A17` alpha `warning` rev 3
  `2026-10-06T11:59:30Z`; `B22` beta `normal` rev 1 `2026-10-06T11:59:30Z`) and three alerts with `occurred_at`,
  `code` `SIM-WARN`, `message` (`A17-alert-001`, `A17-alert-002`, `A17-old-001`). Erratum 101: "the delivered fixtures
  stay the 1.0 contract fixture and no service reads them".
- No database table holds assets or alerts (`privileges.GRANTS` has none; no revision creates one); `app.runs` carries
  `asset_id text NOT NULL`, `start_at`, `end_at` (`0001_walking_skeleton.py:80-82`) and `requester uuid NOT NULL`
  (`:77`), no asset type and no issuer. `create_run` checks only that `asset_id` is present and non-empty
  (`0003_run_path_functions.py:261`, `:267`; no later revision re-creates `create_run`); the admission router's
  parser reads asset ids from text (`ops_core/routing.py:143`), so nothing ties a run's asset to its tenant today.
- The governed documents carry `asset_family` (`documents.asset_family`, `0011:87`) from the same `asset_types`
  vocabulary (`corpus.py:373-375`).

### 3.5 Processes, ports, health URLs, Keycloak clients

- `scripts/skeleton.py:346-353` `PROCESSES`: `incident-sim` `ops_incident_sim` 8090; `mcp-read` `ops_mcp_read` 8081;
  `mcp-write` `ops_mcp_write` 8082; `api` `ops_api` 8000; `worker` `ops_worker` 8070; `sweeper` `ops_sweeper` 8071.
  `Process.health_url` = `http://127.0.0.1:<port>/health/ready` (`:341-343`). `process_environment()` (`:357-372`)
  sets defaults for `OPS_API_PORT`, `OPS_WORKER_HEALTH_PORT`, `OPS_SWEEPER_HEALTH_PORT`, `OPS_MCP_READ_PORT`,
  `OPS_MCP_WRITE_PORT`, `OPS_INCIDENT_SIM_PORT`; no asset-sim entry. `tests/plan_e/test_skeleton_cli.py:31-32` pins
  `[p.name for p in PROCESSES] == ["incident-sim", "mcp-read", "mcp-write", "api", "worker", "sweeper"]` and six
  distinct ports.
- `ops_core.settings.Urls` (`settings.py:421-436`): `mcp_read_resource` (`MCP_READ_RESOURCE_URL`, default
  `http://mcp-read:8081/mcp`), `mcp_write_resource`, `mcp_read` (`OPS_MCP_READ_URL`, `http://127.0.0.1:8081/mcp`),
  `mcp_write`, `incident_sim` (`OPS_INCIDENT_SIM_URL`, `http://127.0.0.1:8090`); **no asset-sim URL or port**.
  `workload_client_id()` (`:439-446`): `OPS_WORKLOAD_CLIENT_ID`, default `ops-worker`.
- Keycloak realm (`deploy/dev/keycloak/realm-ops-dev.json`): `ops-worker` service account with audiences
  `${MCP_READ_RESOURCE_URL}` and `${MCP_WRITE_RESOURCE_URL}` (`:39-61`); **`ops-mcp-read`** service account, name
  "mcp-read (workload; calls asset-sim)", mapper "aud asset-sim" with `"included.custom.audience": "asset-sim"`
  (`:66-81`); `ops-mcp-write` → `incident-sim` (`:86-101`); `ops-web` (authorization code, `:18`), `ops-dev-direct`
  (persona password grant, aud `ops-api`, `:106-121`), `ops-view-users` (service account; "used by the API's
  fail-closed enabled check and the sweeper's membership sync", `:126-135`), `ops-test-admin` (`:138`).
  `docs/runbooks/dev-topology.md:37`: "| `ops-mcp-read` | service account | `asset-sim` | mcp-read → asset-sim |".
  `tests/plan_b/test_realm_template.py:92` asserts `audiences(c["ops-mcp-read"]) == {"asset-sim"}`;
  `tests/plan_b/live/test_keycloak_tokens.py:47` checks the live audience. The client secret's file name is
  `kc_client_secret_ops_mcp_read` (`scripts/bootstrap_dev.py:32`; not read). Measured audiences (Plan B review,
  `docs/reviews/plan-review-b-2026-10-08.md:701`): mcp-read `["asset-sim", "account"]`.
- `ops_core.tokens.WorkloadTokenSource(*, token_url, client_id, client_secret, post=None)` (`tokens.py:215`): cached
  client-credentials tokens refreshed 30 s before expiry; used by the worker (`worker/main.py:130-133`) and by
  mcp-write for incident-sim (`mcp-write/src/ops_mcp_write/server.py:315-319`, `client_id="ops-mcp-write"`,
  `settings.read_secret("kc_client_secret_ops_mcp_write")`). `TokenVerifier(*, issuer, audience, allowed_azp,
  jwks_url, algorithms=("RS256",), required_claims=("exp","iss","aud","sub"), require_azp=True, typ=None,
  token_type=None)` (`:77-100`); `WrongAudience(TokenRejected)` (`:43`); `bearer_token` (`:58`).
- `tests/e2e/test_mcp_read_process_live.py:150-155` already mints an "ops-mcp-read (aud asset-sim)" token in a live
  test (as a foreign token refused by mcp-read).

### 3.6 The worker as the caller (R029)

- `worker/src/ops_worker/mcp.py` (77 lines): `HttpMcpCaller.call(url, *, handle, tool, arguments)` (`:59-77`) opens a
  fresh `Client(streamable_http_client(...), mode=PROTOCOL_VERSION)` and calls `client.call_tool(tool, arguments)`
  directly — **no `list_tools`**, no comparison of the advertised schema; it raises `McpCallFailed` on transport
  failures and when `result.is_error or not isinstance(result.structured_content, dict)` (`:75-76`), and returns the
  structured content unvalidated. Read timeout 60 s (`:57`); no size bound.
- `worker/src/ops_worker/handlers.py`: `QUERY_CHARS = 500` (`:39`); the investigate handler mints one read handle
  (`:111-118`), emits `TOOL_STARTED` (`:119`), calls only `search_procedures` with `arguments={"query":
  text[:QUERY_CHARS], "limit": 3, "mode": "lexical"}` (`:123-130`) — no `asset_type`, no asset tools — and maps
  `McpCallFailed`/`ValueError` to FAILED "retrieval failed" (`:132-135`), an empty result to INSUFFICIENT_EVIDENCE
  (`:137-139`); it reads `doc["data"]["corpus_version"]` (`:146`).
- `worker/src/ops_worker/proposals.py:35-52` `evidence_from_search(doc)`: requires `status == "ok"` and a dict `data`,
  reads six fields per row and raises `ValueError` on a missing key; no JSON-schema validation.
- `worker/src/ops_worker/drafting.py:24-30` `DraftRequest(asset_id, text, start_at, end_at)` (four fields; no asset
  status or alerts).
- Runtime dependencies: `worker/pyproject.toml:6` `["ops-core", "mcp==2.3.0", "uvicorn>=0.54,<1"]`; `core` has no
  `jsonschema`; `jsonschema` and `rfc3339-validator` are root dev-group dependencies only (`pyproject.toml:34-45`;
  T04 "add jsonschema to the dev group").

### 3.7 Contracts for the three read tools (`schemas/`)

- `schemas/tools/get_asset_status.input.schema.json`: `additionalProperties: false`, required `asset_id` (string,
  maxLength 32, pattern `^[A-Z][A-Z0-9_-]{0,31}(?![\s\S])`).
- `schemas/tools/get_recent_alerts.input.schema.json`: required `asset_id`, `start_at`, `end_at`, `limit`;
  `start_at`/`end_at` date-time with pattern `…(Z|\+00:00)(?![\s\S])` (erratum 6); `limit` integer 1..100; optional
  `cursor` string 1..200.
- `schemas/tools/search_procedures.input.schema.json`: required `query` (1..500), `limit` (1..8), `mode` (`lexical`
  | `vector_exact`); optional `asset_type` (1..40).
- `schemas/tool-result.schema.json` (1453 lines): envelope (`:1-130`) — required `tool_name` (six-name enum),
  `request_id` (uuid), `status` (`ok`|`error`|`outcome`), `observed_at` (date-time), `truncated` (boolean), `data`,
  `error` (`{code ≤80, message ≤500, retryable}` or null); `status=error` ⇒ `data` null. `get_asset_status` ok branch
  (`:132-186`): `data` with `additionalProperties: false`, required `asset_id`, `state` ∈ {`normal`, `warning`,
  `unavailable`}, `revision` ≥ 1, `observed_at`, `data_source` const `synthetic`. `get_recent_alerts` ok branch
  (`:187-288`): required `asset_id`, `start_at`, `end_at`, `alerts` (0..100 items, each `additionalProperties: false`
  with required `alert_id` (uuid), `asset_id`, `occurred_at`, `code` (1..80), `message` (1..500), `revision` ≥ 1),
  `next_cursor` (string 1..200 or null). `search_procedures` ok branch (`:290-386`): `results` 0..8 items with
  required `evidence_id` (≤160), `document_id` (≤100), `version` (≤40), `section` (≤120), `content_sha256`, `excerpt`
  (1..**8000**), `effective_from`, `retrieved_at`; `retrieval_mode` (`lexical`|`vector_exact`); `corpus_version`
  (1..100). Read tools may only be `ok` or `error` (`:1284-1300`).
- `schemas/evidence.schema.json`: the same eight fields as a search result row, `retrieved_at` required.
- Examples: `schemas/examples/tool-get_asset_status-valid.json` (A17, `state` `warning`, `revision` 1, `observed_at`
  `2026-10-06T12:00:00Z`, `data_source` `synthetic`); `tool-get_recent_alerts-valid.json` (A17, interval
  `2026-10-05T12:00:00Z`–`2026-10-06T12:00:00Z`, two alerts with the handoff-fixture uuid5 IDs
  `cfa4e790-6f70-5e49-b73f-e9e8d613f52e` and `8fd07823-d6b4-5ffc-a691-3bba680494e1`, `code` `SIM-WARN`, `next_cursor`
  null); `tool-invalid-read-tool-outcome.json`; `tool-search_procedures-valid.json`. No Pydantic model of the tool
  result exists in `core/src/ops_core/contracts.py`; schema conformance is tested in
  `tests/plan_c/test_schema_conformance.py`, `tests/plan_d/test_mcp_read.py`, `tests/plan_k/test_write_tools_server.py`.

### 3.8 The revision chain and how definers are written

- `migrations/app/versions/`: `0001_walking_skeleton` … `0011_governed_corpus` (head of the `app` tree) and
  `tc_0001_test_clock` (branch `testclock`). `skeleton.py:219-221` `migrate_target`: `heads` in the test profile,
  `app@head` otherwise. The dev `ops` database is at 0011 with corpus-1 ingested (owner, 2026-10-18;
  `SESSION_STATE.md:12-13`).
- **0011** (`0011_governed_corpus.py`, 280 lines): `HEADER = "LANGUAGE plpgsql SECURITY DEFINER SET search_path = app,
  pg_temp SET app.tenant_id = ''"` (`:40`), `HELPER_HEADER` (`:41`), **`EXCERPT_CHARS_0011 = 500` with "# Plan D's
  excerpt bound, unchanged (the tool contract allows 8000; the silent cut stays with the tool, T16)." (`:42-43`)**,
  `REQUIRE_VECTOR` (`:47-55`), `TABLES_0011` (`:57`), `GRANTS_0011` (`:63-65`), `MIN_RANK` (`:150-158`, 0.25),
  `SEARCH_PROCEDURES_SCOPED` (`:160-238`): signature `(p_raw_handle text, p_client_azp text, p_query text,
  p_query_embedding public.vector(768), p_asset_type text, p_limit integer, p_mode text)` returning `TABLE
  (corpus_version text, results jsonb)` (`:161-164`); `PERFORM app._authority('search_procedures_scoped',
  ARRAY['mcp_read'])` (`:172`); `SELECT * INTO v_handle FROM app._resolve_handle(p_raw_handle, p_client_azp, 'read')`
  (`:175`); `set_config('app.tenant_id', …, true)` (`:176`); `IF p_mode = 'vector' THEN -- TODO(T18) … RAISE
  EXCEPTION 'refused' USING ERRCODE = 'OC005', DETAIL = 'VECTOR_MODE_UNAVAILABLE'` (`:177-180`); `BAD_ARGUMENT`
  bounds (`:181-185`); `corpus_version` = the tenant's latest `corpus_ingestions` row or `'none'` (`:187-188`);
  **`v_now := app.current_time();` "read after the lease lock (SA:157)" (`:189`) — `v_now` is used for effectiveness
  and is not returned**; asset filter `p_asset_type IS NULL OR e.asset_family IS NULL OR e.asset_family =
  p_asset_type` (`:216`); `left(c.body, 500) AS excerpt` (`:219`); rank threshold `> app._min_rank()` (`:225`); the
  JSON rows carry `evidence_id, document_id, version, section, content_sha256, excerpt, effective_from, rank`
  (`:228-233`). `FUNCTIONS` tuple (`:241-249`) "(name, argument types, callers, body): frozen here (N1); the
  newest-revision test reads this tuple"; `upgrade()` (`:260-272`) runs each body, then
  `privileges.function_grant_statements(name, args=args, callers=callers)`; exact `DOWNGRADE` (`:250-257`).
- **`_resolve_handle(p_raw_handle, p_client_azp, p_server)`** (`0007_leases_fences.py:122-171`, re-created by `0009`
  with `JOB_READ_0009`, `0009_handle_binding.py:42-49`): `HELPER_HEADER` (not a definer); looks the handle up by its
  SHA-256; `run_lease FOR SHARE` first; refuses (`OC008`, one message) on a missing lease, another fence, a lapsed
  lease, revocation, expiry or another `azp`; derives the server from the job type (and the job must be the handle's
  own run's and unfinished since 0009); returns `HANDLE_COLUMNS` = `run_id uuid, job_id uuid, job_type text,
  tenant_id uuid, conversation_id uuid, run_state text, attempt_state text` (`0004_write_path_functions.py:29-31`) —
  not `asset_id`, `start_at`, `end_at` or `requester`, which it reads into `v_run` (`runs%ROWTYPE`) without returning.
- `resolve_invocation(p_raw_handle, p_client_azp)` (`0004_write_path_functions.py:238-251`): `_authority` for
  `mcp_read`/`mcp_exec`, then `_resolve_handle(…, CASE WHEN session_user::text = 'mcp_read' THEN 'read' ELSE 'write'
  END)`.
- `_authority(p_function, p_allowed)` (`0003_run_path_functions.py:73-83`).
- `persistence.HANDLE_BINDING`/`GOVERNED_CORPUS` are startup markers; `tests/plan_l/test_migration_0011.py:133`
  "test_the_startup_marker_is_only_in_0011s_function".
- **Newest-revision guard**: `tests/plan_e/test_transitions_table.py:61-80`
  `test_the_newest_revision_of_every_cell_equals_the_live_matrix` (every revision's `GRANTS_*` and `FUNCTIONS`
  callers must equal `privileges.GRANTS` / `DEFINER_FUNCTIONS`; a helper must have no callers and be in
  `HELPER_FUNCTIONS`); its `REVISIONS` tuple (`:86-98`) lists `0002` … `0011_governed_corpus` and
  `tc_0001_test_clock` by name.
- Lock-order guard: `tests/plan_h/test_locking.py:14-21` requires every table in `privileges.GRANTS` to be placed once
  in `ops_core.locking.LOCK_ORDER` (`locking.py:29`), `OWN_UNIT` or `NEVER_LOCKED`.

### 3.9 Tests that pin mcp-read's tools and ACL today

- Tool list equal to `["search_procedures"]` / `{"search_procedures"}`: `tests/plan_d/test_mcp_read.py:98-99` (also
  pins the advertised schema's properties, bounds and `extra`-refusal, `:100-121`);
  `tests/plan_j/test_mcp_read_http.py:114`, `:147`; `tests/e2e/test_mcp_read_process_live.py:114-116`;
  `tests/e2e/test_mcp_read_t15_live.py:328`.
- `UNSUPPORTED_MODE`: `tests/plan_l/test_mcp_read_corpus.py:112-117`
  ("test_vector_exact_is_refused_after_resolution_and_before_any_search"); `tests/e2e/test_mcp_read_live.py:85`.
- `retrieved_at`: `tests/plan_d/test_mcp_read.py:63` asserts `(first["effective_from"], first["retrieved_at"]) ==
  ("2026-09-01T00:00:00Z", "2026-10-16T12:00:00Z")` on a database-free `search_response`.
- R131 ACL equality: `tests/e2e/test_mcp_read_t15_live.py:269-291` asserts `mcp_read`'s EXECUTE set in `app` ==
  `{"current_time", "resolve_invocation", "search_procedures_scoped"}` (`:279`) and that every other
  `DEFINER_FUNCTIONS` name exists; `tests/e2e/test_mcp_write_t47_live.py:186-205` asserts `mcp_exec`'s set and that
  `search_procedures_scoped` is 42501 for `mcp_exec`, docstring "`asset_scope` arrives with T16";
  `tests/e2e/test_migration_0008_live.py:243-262` "no function an MCP server may call inserts a job" (transitively
  over every function `mcp_read`/`mcp_exec` may execute); `tests/e2e/test_migration_0011_live.py:419` (mcp_read holds
  no table grant).
- Unit half of 0011: `tests/plan_l/test_migration_0011.py` (nine tests, `:48-156`), incl.
  `test_the_function_is_granted_to_mcp_read_alone_with_the_matrix_signature` (`:77`),
  `test_mcp_read_refuses_a_database_without_0011` (`:156`).

### 3.10 Gates

- `scripts/check.py` (`:1-9`): ruff, ruff format, mypy over `MEMBER_SRC` (`:27-36`, includes `asset-sim/src`), pytest;
  `--profile dev` (default, database-free) or `--profile test` (sets `OPS_LIVE=1`, `PROFILE=test`, `:56-63`; "also
  runs the live suite; needs the dev stack up"). `pyproject.toml` `testpaths` (`:48-51`) lists `tests/plan_a` …
  `tests/plan_l` and `tests/e2e` (no `tests/plan_m`).
- `scripts/verify_handoff.py`: `--contracts`, `--manifest`, `--reference-code`, `--reference-tree`, `--zip`
  (`:197-218`); its default run loads `data/corpus` with `corpus.load` and requires `meta.json` to equal the
  regenerated one (`:284-293`), and `--contracts` meta-validates `schemas/tools/*.json` and the examples
  (`:348-380`).

---

## 4. Prior rulings, debt lines and proposed errata that touch T16

Errata are proposed in `SESSION_STATE.md`; the owner decides, the spec stays authoritative until then.
`SESSION_STATE.md:9-12`: owner input (3) "decide the proposed errata of Plans C, E, F, G, H, I, J, K and L (errata
1-102; L: 93-102 below)". New errata continue at **103**.

- **3** (`SESSION_STATE.md:145`): "AM-20.3 `search_procedures_scoped`: `mode=vector` is the SQL argument value; the
  externally visible `retrieval_mode` is `vector_exact`, and mcp-read translates between them."
- **6** (`:148`): "BUILD_SPEC §6 "UTC instants with explicit offsets": only hashed documents (the proposal) spell UTC
  as `Z`; `manual-proposal`, `model-pins` and the `get_recent_alerts` input accept `Z` or `+00:00`, as do request
  bodies, and the contract normalises to `Z` before hashing."
- **15** (`:187`): "AM-20.6: `app.current_time()` is a definer function callable by every runtime role."
- **19** (`:191`): "AM-20.3 `resolve_invocation` returns `job_type`, `job_id` and `conversation_id` instead of SA:459's
  `allowed_tools` (plan ruling 21)."
- **53** (`:373-374`): "SA:459: `resolve_invocation` reads `invocation_context` without a lock; `run_lease FOR SHARE`
  in `_resolve_handle` is the one lock, shared by every handle function."
- **72** (`:562-565`): "R131 and SA:400/SA:459 (`mcp_read`'s functions): `mcp_read` holds EXECUTE on `current_time`
  (erratum 15) and `resolve_invocation` and on nothing else in `app`; `asset_scope` arrives with T16 and
  `search_procedures_scoped` with T17/T16, each in its owner's revision (Plan E ruling 1: no definer without a
  caller), so R131's three-function set is the target, not today's."
- **75** (`:577-579`): `_resolve_handle` resolves a handle only when its `job_id` names an unfinished job of the
  handle's own run (revision 0009).
- **76** (`:580-585`): "`persistence.allowed_tool(job_type, run_state, tool)` checks the job type's tools and run
  states at the start of every MCP call (`persistence.resolve_invocation`; the definers' own resolutions … do not apply
  it …)".
- **77** (`:586-588`): "SA:459 (the `resolve_invocation` row as amended): the only lock is `run_lease FOR SHARE`
  (erratum 53); it returns `run_id, job_id, job_type, tenant_id, conversation_id, run_state, attempt_state` (erratum
  19); it binds the handle as erratum 75 says."
- **80** (`:593-595`): "SA:460-461 with SA:176-184 (reads and the fence): a read tool is served after the handle
  resolved in its own committed unit; a fence that moves during the read cannot cause a write, and the worker's next
  fenced unit fails."
- **81** (`:596-599`): the missing-`aud` and browser-token cases are synthetic-key unit tests at mcp-read's
  configuration; "live, a persona token (aud `ops-api`) stands in for a browser token, because no `ops-web` access
  token is minted anywhere (the API stores none, erratum 31, and minting one needs the client secret)."
- **83** (`:676-680`): "SA:462-466 with erratum 48 (the caller's `azp`): `grant_execution(raw_handle, client_azp,
  proposal_id)`, `lookup_action(raw_handle, client_azp)`, `mark_sent(raw_handle, client_azp, action_id)`,
  `record_outcome(raw_handle, client_azp, action_id, outcome, document)` and `request_abort` compare the presented
  token's `azp` with the handle's, as `resolve_invocation` does; the worker's client is named once
  (`OPS_WORKLOAD_CLIENT_ID`, default `ops-worker`)."
- **91** (`:715-717`): "`mcp_exec` holds EXECUTE on `current_time` (erratum 15) as well as the six; "cannot execute any
  read function" is shown as no EXECUTE on any other `app` function, since `asset_scope` and
  `search_procedures_scoped` do not exist yet (T16, T17/T16; erratum 72's pattern)."
- **93** (`:780-784`): "SA:461 (`search_procedures_scoped`): the signature is `(raw_handle, client_azp, query,
  query_embedding vector(768), asset_type, limit, mode)`, the caller's `azp` second as in `resolve_invocation` and the
  write path (erratum 83), because `_resolve_handle` binds the handle to the presented token's `azp`; it returns one
  row `(corpus_version, results)`, the tenant's latest ingested corpus version (`none` before any) and the ranked
  results with a `rank` each, which mcp-read leaves out of the tool result."
- **96** (`:795-797`): "R131 with errata 72 and 91: `mcp_read` executes `current_time`, `resolve_invocation` and
  `search_procedures_scoped`; only `asset_scope` (T16) is still to come; `mcp_exec`'s "no read function" now includes
  `search_procedures_scoped` (42501 when called)."
- **99** (`:803-805`): "`mode = 'vector'` is refused inside the function (`OC005` `VECTOR_MODE_UNAVAILABLE`) until T18
  stores embeddings; the `vector` extension is bootstrap infrastructure (`skeleton.py ensure_extensions`) that
  revision 0011 requires and never creates or drops."
- **101** (`:809-811`): "AM-50 wins; one injected document per tenant is approved and labelled `injected`, stored and
  not filtered; the delivered fixtures stay the 1.0 contract fixture and no service reads them."
- **102** (`:812-816`): R033's no-source residue (5/20) is open; "SA:377 as written counts any returned effective chunk
  as sufficient …; T20 must add a relevance criterion beyond it".

Debt lines and parked items that name T16 or its subjects:

- Walking skeleton (`SESSION_STATE.md:862`): "`search_procedures` is served lexically from `data/handoff-fixtures/`
  inside mcp-read (no governed store, no `asset_scope`) → T17; `get_asset_status` / `get_recent_alerts` and asset-sim
  are absent → T16". Plan E (`:880`): "`asset_scope`, `search_procedures_scoped` → T15/T16/T17".
- Plan J (`:604-606`): "Plan E's `asset_scope` and `search_procedures_scoped` ("T15/T16/T17") now name T16 and T17/T16;
  … Plan D's silent excerpt truncation stays with the tool's contract (T16)."
- Plan J debt list (`:1037-1047`): "`asset_scope`, `get_asset_status`, `get_recent_alerts` and asset-sim → T16;
  `search_procedures_scoped`, the governed store and the `vector_exact` → `mode=vector` translation by its caller →
  T17/T16; …"; "mcp-read's tool arguments (the optional `asset_type`), the order of its `UNSUPPORTED_MODE` check and
  its fallback `corpus_version` → T16/T17 (ruling 20)"; "the worker's client does no tool discovery and no
  result-schema check (R029) → T16; it does not tell a 401 from other transport failures … → T20; it holds no
  `resume_input` handle → T20"; "TLS outside localhost, and container host names … → T30"; "mcp-read has no `tests/`
  directory and no Dockerfile of its own (AM-01) → T30 (ruling 25)".
- Plan J plan rulings (`docs/superpowers/plans/2026-10-15-first-slice-j-mcp-read-verifier-handles.md:187-189`, `:217`):
  "8. **Tools** — only `search_procedures` is registered"; "9. **`search_procedures_scoped`, `asset_scope`** — not
  created; debt lines to T16 and T17/T16"; "20. **Arguments** — untouched; debt line to T16/T17."
- Plan L debt list (`SESSION_STATE.md:1087-1112`, items `:1094-1109`): "mcp-read's `vector_exact` → `mode=vector` translation (until then
  `UNSUPPORTED_MODE` before the database) → T16"; "`asset_scope`, the asset tools, asset-sim serving
  `data/corpus/assets.json`, and the run's own asset type passed to the search (the tool takes `asset_type` from its
  caller only) → T16 (ruling 11)"; "the requester's current membership re-checked at read time (R028) → T16 (ruling
  10)"; "the excerpt is still cut silently at 500 characters (Plan D's open item) → T16"; "`retrieved_at` is the wall
  clock (`datetime.now(UTC)` in mcp-read's `search_response`) while a version's effectiveness is decided at
  `app.current_time()`, so under a moved test clock a result can carry a `retrieved_at` earlier than its own
  `effective_from`; return the definer's instant (one more column) and stamp `retrieved_at` from it, so the evidence
  row records the instant its permission was decided → T16 (Plan L final review, M4)". Also (`:1101-1104`): the
  grant's document recheck → T21; R035 → T26; R036 and the conflicting pair → T19/T20.
- Plan L plan rulings (`docs/superpowers/plans/2026-10-16-first-slice-l-governed-corpus.md:219-224`): "10. **Access
  filtering** — tenant (from the handle) + lifecycle + optional asset type; the requester's membership at read time →
  T16 (debt line)."; "11. **Assets** — `data/corpus/assets.json`: three asset types, six assets …, seven alerts with
  revisions; `meta.json` gives their tenant UUIDs and uuid5 alert IDs (Task 2). … mcp-read's tool gains the optional
  `asset_type` (Task 4); the run's own asset type → T16." Plan L review (`docs/reviews/plan-review-l-2026-10-17.md:86`,
  `:89-92`): "The requester's current membership re-check at read time → T16 (R028) debt line."; alerts "with UUID5
  IDs and revisions … — consumed later by T16's asset-sim … the run's own asset type lookup → T16".
- Plan L final review (`docs/reviews/plan-l-final-review-2026-10-18.md:112-116`): "4. **`retrieved_at` uses the wall
  clock while "effective" uses the database clock.** … in the test profile with a moved clock a result can carry
  `retrieved_at` earlier than its own … return `v_now` from the definer (one more column) and stamp `retrieved_at` from
  it, or record it as T16 debt." `docs/PROJECT_HISTORY.md:685-693`: "M4 became a debt line for T16 (return the
  definer's instant and stamp `retrieved_at` from it)."
- Round-6 review (`docs/reviews/plan-review-r6-2026-10-06.md:49`): "**T16/T18:** `search_procedures_scoped` takes text
  only, so vector search cannot run inside it without an embedding argument. Add one (or embed inside the function via
  a trusted embedding service)." Round-5 (`plan-review-r5-2026-10-06.md:45`, H2): "The MCP server cannot implement
  `search_procedures` or the asset-access reads … AM-20.1 / T09 / T16: add read definer functions".
- Plan C final review (`docs/reviews/plan-c-final-review-2026-10-08.md:82`): "If T15 validates `get_asset_status`
  arguments with these schemas, `"A17\n"` passes and reaches asset-sim" (fixed by the `(?![\s\S])` end anchor, `:403`).
- Plan D ruling (`docs/superpowers/plans/2026-10-08-first-slice-d-walking-skeleton.md:43`): "`vector_exact` is refused
  with a tool error until T17 (the governed store)."
- No document records any ruling on asset-sim's port, data model, cursor format or forwarding mechanism.

---

## 5. Open questions the planner must rule on

1. **Vector mode: in T16 or deferred to T18.** For T16: its instructions ("vector mode: mcp-read computes the nomic
   search_query embedding", `tasks.json:753`), review note `:771`, SA:348 and SA:461 put the translation and the
   embedding in mcp-read. Against: the definer refuses `mode=vector` (`0011:177-180`, `TODO(T18)`); no `embeddings`
   table exists (erratum 95: created by T18); no `nomic`/embedding code or model pin exists in the tree (§3.6;
   `data/model-pins.json` is absent, T02 pending); T18 is not in T16's `depends_on` (`:754-758`) and owns the prefix
   test (SA:645, T18 DoD 2); debt (b) says "Plan M will rule on deferring it". `persistence.search_procedures` passes the
   literal `NULL` and `'lexical'` (`:488-492`); `RunManifest.retrieval_mode` already allows `vector_exact`
   (`routing.py:362-363`). Options: (a) defer the whole vector path to T18 with a debt line (and an erratum against
   T16's instruction/note); (b) T16 writes mcp-read's translation and embedding call, still refused by the definer
   until T18; (c) T16 implements the translation only (`vector_exact` → `mode=vector`, embedding absent), so the
   refusal moves from mcp-read's `UNSUPPORTED_MODE` to the definer's `VECTOR_MODE_UNAVAILABLE`.

2. **`asset_scope`'s signature and output.** SA:460 says `asset_scope(raw_handle)`; T16 note a says
   `asset_scope(raw_handle, client_azp)` (erratum 96's wording in the task, by analogy with errata 83 and 93, since
   `_resolve_handle` needs the token's `azp`, `0007:122`); SA:460 returns "`tenant_id`, `asset_id`, `[start_at,
   end_at)`"; `_resolve_handle` returns neither the asset nor the interval (`HANDLE_COLUMNS`, `0004:29-31`) but reads
   the whole `runs` row; T16 debt e needs the run's asset **type**, which no table holds (§3.4). Open: the argument list
   (an erratum to SA:460 either way if `client_azp` is added), the returned columns (with or without `asset_type`,
   `requester`, `run_id`, an instant), whether `run_state`/allowlist is checked in Python first (erratum 19/76's
   pattern), and the revision that creates it (0012).

3. **`retrieved_at` and revision 0012's contents.** Debt h: "return the definer's instant as one more output column,
   i.e. a new revision 0012 (0011 is frozen)"; `v_now` is computed after the lease lock (`0011:189`) and not returned;
   `persistence.GOVERNED_CORPUS`'s marker and the rule "a later revision that re-creates the function keeps this text
   or changes it here in the same commit" (`persistence.py:188-194`); a changed `RETURNS TABLE` needs `DROP FUNCTION` +
   `CREATE` (not `CREATE OR REPLACE`) and a re-grant; `observed_at` in every envelope is also the wall clock
   (`server.py:76`); `tests/plan_d/test_mcp_read.py:63` pins the current stamping. Candidates for 0012 named by the
   debts: `asset_scope` (+ its grant, R131), the extra column on `search_procedures_scoped`, a membership re-check
   (Q7), a different excerpt bound (Q9), any assets table (Q4). Open: what 0012 carries, whether `observed_at` also
   comes from `app.current_time()`, the downgrade, which services assert 0012 at start, and the owner step to migrate
   the dev database to it.

4. **asset-sim's data source.** For `data/corpus/assets.json`: T16 note a ("asset-sim serving data/corpus/assets.json"),
   Plan L ruling 11, `docs/retrieval.md:17`; it has six assets and seven alerts with revisions and uuid5 IDs in
   `meta.json`. Against / gaps: it has **no status** (`state`, asset `revision`, `observed_at`) for
   `get_asset_status`, and its alerts carry `kind`/`severity`/`raised_at` where the contract requires `code`,
   `message`, `occurred_at`, `alert_id` (uuid) (§3.7); `assets.json` is in the corpus lock (`corpus.py:278-284`), so
   any edit needs a new corpus version (`check_lock`, `RELEASES`) and, once T41 has labelled, re-labelling
   (`tasks.json:805`); `load_assets` checks only some keys (`corpus.py:209-275`); BS:405 and SA:78 want data
   "deterministic under an injected clock/seed"; `observations.json` has status for two assets only and is retired
   (erratum 101). AM-20.2 has no assets table and ADR-0001:41 says the read API needs no database. Options: derive
   status and alert text from `assets.json` (+ `meta.json`) by a deterministic rule; add fields to `assets.json` as
   `corpus-2`; a separate asset-sim data file outside the corpus lock; asset-sim's own store; and how the injected clock
   is supplied (asset-sim has no `app.current_time()`; a setting, a header from mcp-read, or the request's interval).

5. **asset-sim's port, URL, process and health.** No port, URL setting or process entry exists (§3.5); used ports are
   8000, 8070, 8071, 8081, 8082, 8090; `tests/plan_e/test_skeleton_cli.py:31-32` pins the six processes;
   `settings.Urls` has no asset-sim field; incident-sim's shape (`__main__.py`, `production_app`, `/health/live`,
   `/health/ready`, FastAPI + uvicorn) is the existing template; `asset-sim/pyproject.toml` lacks FastAPI/uvicorn.
   Open: the port and `OPS_*` names (port, URL), the skeleton entry and start order (before mcp-read, as incident-sim
   precedes mcp-write), whether asset-sim gets a `/health/ready` that checks anything, its `tests/`/`Dockerfile` (AM-01
   vs the T30 debt pattern for mcp-read and mcp-write).

6. **asset-sim's authentication.** SA:555 "trusts only the mcp-read workload token"; T16 DoD 2 "asset-sim rejects
   worker, api and mcp-write tokens"; the realm already gives `ops-mcp-read` the audience `asset-sim`
   (`realm-ops-dev.json:66-81`) and its secret file is named `kc_client_secret_ops_mcp_read`; incident-sim's verifier
   pattern is `TokenVerifier(audience="incident-sim", allowed_azp={"ops-mcp-write"})` with 403 for `WrongAudience` and
   401 otherwise (`incident-sim/app.py:143-148`, `:283-285`); mcp-read has no outbound token source today. The "api
   token" has no workload form: the API's clients are `ops-web` (no access token is minted anywhere, erratum 81) and
   `ops-view-users` (a service account shared with the sweeper); erratum 81 used a persona token (aud `ops-api`) as the
   browser stand-in. Open: which tokens the DoD-2 test presents as "worker", "api" and "mcp-write" (worker
   `ops-worker`, mcp-write `ops-mcp-write`, api = persona or `ops-view-users`), the status codes, whether `typ`
   (`token_type="Bearer"`) is required as at mcp-read, and whether asset-sim exposes fault hooks (BS:405) under
   `PROFILE=test` (R098).

7. **R028's membership re-check at read time.** Debt f; BS:362 "loads current requester/tenant policy from the stored
   run"; BS:401 "Server-side role rechecks happen at read and write boundaries"; R013/R086 cover the API and the grant;
   `runs.requester` is a bare subject `uuid` with no issuer (`0001:77`), while `memberships` is keyed `(tenant_id,
   issuer, subject, role)` with `role ∈ {requester, reviewer, reader}`, `active`, `permission_version`
   (`0001:41-50`); `mcp_read` has no table grants (SA:437) but `app_definer` has SELECT on `memberships` under
   `tenant_isolation`; the sweeper's sync deactivates within 60 s (SA:547). Open: where the check runs (inside
   `asset_scope`/`search_procedures_scoped`/`_resolve_handle`, or a new definer), which role(s) count as current,
   whether it applies to all three tools, the refusal (the one `INVALID_HANDLE` refusal, SA:355 and Plan D ruling 13 as `SESSION_STATE.md:603` records it, or a distinct
   code), and whether `resolve_invocation`'s output changes (erratum 77).

8. **The tenant filter and how mcp-read forwards tenant/asset context.** SA:460 "for forwarding to asset-sim"; SA:555
   "the tenant/asset context it forwards, and applies its own tenant filter"; BS:364 "never forward the handle to the
   destination"; the tool inputs carry `asset_id` (and an interval) from the caller (§3.7) while SA:350/BS:362 forbid
   tenant arguments; R028 "Alpha requests B22"; `assets.json` names tenants by slug, `meta.json` by UUID. Open: the
   transport (HTTP headers, query or JSON body; names), tenant as UUID or slug, whether mcp-read refuses an `asset_id`
   that differs from the run's own (`asset_scope`'s) before calling asset-sim or lets asset-sim's filter refuse it,
   what asset-sim answers for another tenant's or an unknown asset (404, empty, `state: unavailable`), and how the
   refusal maps into the envelope (SA:354–355).

9. **The interval of `get_recent_alerts`.** BS:389 "absolute timestamps … convert at the admission boundary";
   SA:333/SA:460 give the run's `[start_at, end_at)`; the input schema requires `start_at`/`end_at` from the caller
   (`Z` or `+00:00`, erratum 6) and the result echoes them. Open: whether mcp-read uses only the run's interval
   (ignoring/refusing a different one), refuses a mismatch, or clamps; half-open comparison on `occurred_at`; which
   alert time `raised_at` maps to; and whether alerts after `end_at` but before "now" are ever shown.

10. **`next_cursor`, `limit` and `truncated`.** BS:385 "`truncated` flag and next cursor where needed"; input `limit`
    1..100 and optional `cursor` 1..200 chars; result `alerts` ≤100 and `next_cursor` string or null; the envelope's
    `truncated` is always `False` today (`server.py:77`); the corpus has at most two alerts per asset. Open: the cursor
    format (opaque, signed, an offset/last-ID), whether it binds to the run/handle/interval so it cannot be replayed
    across runs, the ordering key (time then id), and when `truncated` is true.

11. **The excerpt cut (debt g).** `0011:42-43`, `:219` cut at 500 characters silently; the schema allows 8000;
    chunks are 45-119 words (erratum 100); `truncated` exists only on the envelope. Options: raise the bound to the
    whole section (a 0012 body change), keep 500 and set a flag (the result row has no truncation field; the envelope's
    `truncated` is per call), or cut in mcp-read; and whether the cut is recorded in `docs/retrieval.md`.

12. **The run's asset type passed to `search_procedures` (debt e).** The tool takes `asset_type` from its caller only
    (`server.py:191`); the worker sends none (`handlers.py:128`); the run has `asset_id` only; the type lives in
    `assets.json`/`meta.json` (asset-sim's side) and nowhere in the database. Options: mcp-read derives it (from
    asset-sim's answer, or a table/column in 0012) and overrides or intersects the argument; the worker passes it
    after `get_asset_status`; or the definer derives it; and whether a caller-supplied type that differs from the
    run's asset's type is refused.

13. **R029: tool discovery and result validation in the worker.** Debt d; BS:399 "Validate tool-specific nested
    schemas, not just the envelope. Check both transport errors and the SDK's tool-error flags"; R029 "Alter discovered
    tool/schema; return error-flagged/malformed/oversized payload; no success assumption"; BS:589 "malformed results";
    the worker calls `call_tool` without `list_tools` and validates only `status`/six keys (`mcp.py:75-77`,
    `proposals.py:35-52`); `jsonschema` is a dev dependency only; mcp-read's advertised input schema is generated by
    pydantic (`strict_tool`), not the committed JSON file, and the Plan D test compares only selected keys
    (`test_mcp_read.py:98-107`). Open: what "discovered tool/schema" is compared against (the committed
    `schemas/tools/*.json`, a pinned hash, a set of names), when discovery runs (per call, per job, at start), the
    validator (jsonschema as a runtime dependency of `ops-core`/worker, or Pydantic models of the read results), the
    size bound for "oversized", and what the run does on failure (FAILED "retrieval failed" as today, or another state).

14. **The order of the `UNSUPPORTED_MODE` check and the fallback `corpus_version` (debt c).** Today the mode is checked
    after the handle resolution and before the search (`server.py:206-208`, pinned by
    `tests/plan_l/test_mcp_read_corpus.py:112-117`); a `vector_exact` call therefore reveals handle validity first.
    The corpus version comes from the definer (`'none'` before any ingestion, `0011:187-188`); mcp-read has no own
    fallback since T17. Open: keep the order or move the mode refusal before resolution, and whether "fallback
    `corpus_version`" is closed by T17 (a recorded ruling) or needs anything.

15. **How the three tools are served per call (units and fences).** Erratum 80 serves a read after the handle
    resolved in its own committed unit; `search_procedures` uses two units (`server.py:199-226`); an asset tool needs
    `asset_scope` (a database unit) then an HTTP call to asset-sim (outside any transaction, BS:364); SA:157 compares
    freshness after locks. Open: whether the asset tools resolve via `resolve_invocation` then `asset_scope` (two units)
    or `asset_scope` alone with the allowlist in Python, what happens when the handle dies between scope and the HTTP
    call, timeouts and retries toward asset-sim, and the envelope codes for asset-sim failures (`UNAVAILABLE`?
    `retryable`?).

16. **Status observation and freshness at grant.** BS:476 / SA:462 / R116 (T21) require "status observed within 5
    minutes at grant"; SA:377 needs "at least one permitted status observation … within freshness"; nothing records an
    asset observation today (the proposal payload has no observation field, `contracts.py:349-418`;
    `grant_execution` carries `TODO(T21): asset freshness`, `0004:301`/`0005:140`, re-worded in `0007:179`). Open:
    whether T16 records the observation (`observed_at`, revision) anywhere the grant can read later (a table, the
    proposal, an event), or only returns it and leaves recording to T20/T21; and what `observed_at` means for a
    deterministic simulator (the request time on the injected clock, or a stored instant).

17. **The worker's use of the asset tools before T20.** T20 owns "retrieval before drafting" and the graph; the
    investigate handler calls only `search_procedures` (`handlers.py:119-136`); `DraftRequest` has no status/alerts
    (`drafting.py:24-30`); T16 DoD 1 is phrased at the server. Open: whether T16 changes the worker to call
    `get_asset_status`/`get_recent_alerts` (and pass the asset type) now, or proves the tools with an independent
    client only (BS:378, R025's pattern) and leaves the worker's calls to T20.

18. **Tests and evidence that change.** Four tests pin the tool list to `search_procedures` alone (§3.9); the R131
    ACL equality (`test_mcp_read_t15_live.py:279`) and the write half's "`asset_scope` arrives with T16"
    (`test_mcp_write_t47_live.py:190`) change when `asset_scope` exists; `test_migration_0008_live.py:243` will scan
    `asset_scope`'s body; `test_transitions_table.py` `REVISIONS` (`:86-98`) and `privileges.DEFINER_FUNCTIONS` must
    gain 0012/`asset_scope`; `test_skeleton_cli.py:31-32` pins six processes; `pyproject.toml` `testpaths` lacks
    `tests/plan_m`. Open: which acceptance evidence files R028/R029 point at (`tests/acceptance/` does not exist; past
    plans used `tests/e2e/*_live.py` plus `reports/<area>/`), whether R131's note and evidence are updated by T16
    (R131's owners are T15/T47), and where asset-sim's own unit tests live (`asset-sim/tests/` per AM-01, or
    `tests/plan_m/`).

---

## 6. Glossary of exact names

- **Tools** (`ops_core.jobs.Tool`): `get_asset_status`, `get_recent_alerts`, `search_procedures` (read, mcp-read);
  `create_incident`, `get_incident_receipt`, `abort_incident` (write, mcp-write). Job types with read handles:
  `investigate`, `resume_input`. `Server.READ = "read"`, `Server.WRITE = "write"`.
- **Definer functions**: existing `app.resolve_invocation(text, text)` (`mcp_read`, `mcp_exec`),
  `app.search_procedures_scoped(text, text, text, public.vector, text, integer, text)` (`mcp_read`),
  `app.current_time()` (all runtime roles); spec-named, not created: `app.asset_scope(raw_handle)` (SA:460; T16 note a:
  `asset_scope(raw_handle, client_azp)`). Helpers (no callers): `app._resolve_handle(text, text, text)`,
  `app._authority(text, text[])`, `app._tenant_of_run(uuid)`, `app._latest_attempt(uuid)`, `app._min_rank()` (0.25).
- **Tables**: `app.runs` (`asset_id`, `start_at`, `end_at`, `requester`), `app.memberships`, `app.tenants`,
  `app.invocation_context`, `app.run_lease`, `app.jobs`, `app.corpus_ingestions`, `app.documents` (`asset_family`,
  `label`), `app.document_states`, `app.chunks`; spec-named, not created: `app.embeddings`. No assets/alerts table.
- **Roles**: `mcp_read`, `mcp_exec`, `worker`, `api`, `sweeper`, `operator`, `app_definer` (NOLOGIN), `migrator`
  (NOLOGIN, BYPASSRLS), `test_harness` (test profile), `incident`; Compose superuser `ops`.
- **Error codes**: SQLSTATE classes `OC001`–`OC008` (`OC005` Refused with DETAIL `VECTOR_MODE_UNAVAILABLE` or
  `BAD_ARGUMENT`; `OC008` handle refused), `42501` (no EXECUTE); mcp-read envelope codes `INVALID_HANDLE`,
  `UNSUPPORTED_MODE`, `REFUSED`; `ops_core.contracts.ErrorCode`: `UNAUTHENTICATED`, `FORBIDDEN`, `NOT_FOUND`,
  `INVALID_INPUT`, `RATE_LIMITED`, `UNAVAILABLE`, … ; MCP protocol errors `-32022` (version header), `-32020`
  (header/_meta mismatch).
- **Keycloak** (realm `ops-dev`): clients `ops-worker` (aud `MCP_READ_RESOURCE_URL`, `MCP_WRITE_RESOURCE_URL`),
  `ops-mcp-read` (aud `asset-sim`), `ops-mcp-write` (aud `incident-sim`), `ops-web`, `ops-dev-direct` (aud `ops-api`),
  `ops-view-users`, `ops-test-admin`. Secret file names (not read): `kc_client_secret_ops_mcp_read`,
  `kc_client_secret_ops_mcp_write`.
- **Ports** (loopback): api 8000, worker 8070, sweeper 8071, mcp-read 8081, mcp-write 8082, incident-sim 8090; Postgres
  15432 (`OPS_PG_PORT` default); Keycloak 18080 (`OPS_KC_BASE_URL` default). asset-sim: none assigned.
- **Env vars**: `OPS_MCP_READ_PORT`, `OPS_MCP_WRITE_PORT`, `OPS_INCIDENT_SIM_PORT`, `OPS_INCIDENT_SIM_URL`,
  `OPS_MCP_READ_URL`, `MCP_READ_RESOURCE_URL` (default `http://mcp-read:8081/mcp`), `MCP_WRITE_RESOURCE_URL`,
  `OPS_WORKLOAD_CLIENT_ID` (default `ops-worker`), `OPS_KC_BASE_URL`, `OPS_KC_ISSUER`, `OPS_SECRETS_DIR`, `OPS_PG_DB`,
  `OPS_LIVE`, `PROFILE` (`dev|test|demo`), `MODEL_MODE`.
- **Modules and symbols**: `ops_mcp_read.server` (`ToolResult :48`, `stamp :60`, `tool_error :65`, `envelope :70`,
  `search_response :83`, `McpVerifier :116`, `strict_tool :155`, `State :172`, `build_server :180`, `build_app :239`,
  `read_verifier :290`, `production_app :304`, `serve :322`); `ops_core.persistence` (`Invocation :393`,
  `allowed_tool :406`, `resolve_invocation :432`, `Procedure :452`, `Procedures :467`, `search_procedures :476`,
  `current_time :628`, `mint_handle :1016`, `HANDLE_BINDING :183`, `GOVERNED_CORPUS :191`, `assert_function_text
  :197`); `ops_core.jobs` (`Tool :19`, `JOB_RULES :70`); `ops_core.routing.RunManifest :350`; `ops_core.privileges`
  (`GRANTS :73`, `DEFINER_FUNCTIONS :197`, `HELPER_FUNCTIONS :220`, `function_grant_statements :295`);
  `ops_core.corpus` (`load_assets :209`, `lock_text :278`, `RELEASES :67`); `ops_core.tokens` (`TokenVerifier :77`,
  `WorkloadTokenSource :215`, `WrongAudience :43`); `ops_core.settings` (`Urls :421`, `urls :429`, `workload_client_id
  :439`); `ops_worker.mcp.HttpMcpCaller :51`; `ops_worker.handlers.QUERY_CHARS :39`;
  `ops_worker.proposals.evidence_from_search :35`; `ops_asset_sim` (package only).
- **Migrations**: `0001_walking_skeleton` … `0011_governed_corpus` (head), `tc_0001_test_clock`; constants `HEADER`,
  `HELPER_HEADER`, `EXCERPT_CHARS_0011`, `SEARCH_PROCEDURES_SCOPED`, `FUNCTIONS`, `DOWNGRADE` (0011), `RESOLVE_HANDLE`
  (0007), `JOB_READ_0009` (0009), `HANDLE_COLUMNS` (0004). Next revision number: `0012`.
- **Data**: `data/corpus/{assets.json, catalog.json, meta.json, corpus.sha256, *.md}` (`corpus-1`, lock
  `81f50c2b8623675f9c899033cba748f289b7f4024003385aabc8a95147b71862`); assets `A17`, `A21`, `A30` (alpha), `B22`,
  `B25`, `B31` (beta); asset types `pump`, `compressor`, `conveyor`; tenant UUIDs alpha
  `3ea79c95-914c-52cb-9d10-c4e19dda8ff7`, beta `5ab45c2c-1e12-5a0c-a2b9-66cd2ff05201`; alert uuid5 =
  `uuid5(NS, "alert/<id>")`; `data/handoff-fixtures/observations.json` (1.0 fixture, unread by services).
- **Schemas**: `schemas/tools/get_asset_status.input.schema.json`, `get_recent_alerts.input.schema.json`,
  `search_procedures.input.schema.json`; `schemas/tool-result.schema.json`; `schemas/evidence.schema.json`;
  `schemas/run-manifest.schema.json`; examples `tool-get_asset_status-valid.json`, `tool-get_recent_alerts-valid.json`,
  `tool-search_procedures-valid.json`, `tool-invalid-read-tool-outcome.json`.
- **Contract vocabulary**: envelope `tool_name, request_id, status (ok|error|outcome), observed_at, truncated, data,
  error`; asset status `state ∈ {normal, warning, unavailable}`, `revision`, `observed_at`, `data_source: synthetic`;
  alert `alert_id, asset_id, occurred_at, code, message, revision`; `next_cursor`; `retrieval_mode` `lexical` |
  `vector_exact` (external), `mode=lexical` | `mode=vector` (SQL, erratum 3); `search_query:` / `search_document:`
  prefixes; `nomic-embed-text`, dimension 768.
- **Requirement targets**: R028 `tests/acceptance/test_r028_read_tools_enforce_current_source_and_asset_acce.py`, R029
  `tests/acceptance/test_r029_unexpected_tools_and_invalid_results_fail_closed.py`, R131
  `tests/acceptance/test_r131_the_read_and_write_mcp_servers_hold_disjoint_fun.py`.

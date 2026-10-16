# Plan K inputs: T47 (authenticated MCP write server and recovery tools) — fact sheet

Prepared 2026-10-16 on branch `plan-k` at `9f34038` (= `plan-j`; clean tree; read-only on the repository except this
file). Facts only, no design. Citations: `SA:<line>` = `SPEC_AMENDMENTS.md`, `BS:<line>` = `BUILD_SPEC.md` (line
numbers as of `9f34038`); the amendments win wherever the two conflict. Repository files are cited as `path:line`;
the installed MCP SDK is cited under `.venv/Lib/site-packages/` (abbreviated `sp/`). Nothing was run against a
database, Keycloak or a service for this sheet: every fact below is read from the files, and no secret, token or
`.env` value was opened (the realm export carries `${…}` placeholders only).

Note on line numbers: AM-10 is SA:116–162 (ESCALATED SA:118–122, ABANDONED_UNVERIFIED SA:124–130, transition table
SA:132–143, reasons SA:152); AM-11 SA:164–168; AM-12 SA:170–218 (fenced writes SA:176–184, lock order SA:188–191);
AM-13 SA:220–299 (who does what SA:222–225, attempt protocol SA:227–234, recovery table SA:236–244, cancellation
SA:246–248, transport timeout SA:250–256, destination SA:258–270, outcome vocabulary SA:272–280, asset guard
SA:282–289, defaults SA:291–299); AM-15 SA:327–358; AM-20.1 SA:391–404; AM-20.2 SA:406–442; AM-20.3 SA:444–490
(rows `resolve_invocation` SA:459, `grant_execution` SA:462, `mark_sent` SA:463, `record_outcome` SA:464,
`request_abort` SA:465, `lookup_action` SA:466, `mark_unknown` SA:467, `escalate_run` SA:468, `resolve_escalation`
SA:469; helpers SA:474; "who performs which transition" SA:476–490); AM-20.4 SA:492–506; AM-20.5 SA:508–524; AM-20.7
SA:532–566 (item 6 SA:554–558); AM-30 SA:568–591; AM-60 SA:680–728 (1.3.4 note SA:689). BUILD_SPEC §9 BS:344–374,
§10 BS:376–407, §13 BS:462–478, §14 BS:480–506.

---

## 1. T47 verbatim, its acceptance-matrix rows, and related tasks

### 1.1 T47 (`handoff/tasks.json:698-723`)

- **id/milestone/title:** `T47`, `M05` ("MCP read and write servers and governed corpus", `tasks.json:65-74`, task_ids
  `T15`, `T47`, `T17`, `T16`), "Authenticated MCP write server (mcp-write) and recovery tools". `status: "PLANNED"`,
  `external_approval_required: false`.
- **instructions** (`:702`, verbatim): "mcp-write on the same SDK/protocol pin; TokenVerifier with aud =
  MCP_WRITE_RESOURCE_URL; accepts execute/recover handles only; DB role mcp_exec holds EXECUTE on resolve_invocation,
  grant_execution, mark_sent, record_outcome, request_abort, lookup_action only; hosts create_incident,
  get_incident_receipt (recover only) and abort_incident; sole caller of incident-sim with the incident-sim audience
  and azp."
- **depends_on** (`:703-706`): `["T15", "T10"]`. T15 is `DONE` (Plan J; its review note says "DONE subject to the
  owner's decisions on errata 72 and 76", `tasks.json:695`), T10 is `DONE` (Plan E, `:518-545`).
  `SESSION_STATE.md:14-16`: "Next is Plan K = T47 (mcp-write, the earliest dependency-satisfied PLANNED task in
  `handoff/tasks.json` after T15, unblocked by T15 and T10; T17 is also unblocked)."
- **requirement_ids** (`:707-710`): `R030, R131`.
- **definition_of_done** (`:712-716`, verbatim):
  1. "mcp_exec cannot execute any read function; a read handle presented to mcp-write is rejected (R131 write half)."
  2. "Receipt lookup unavailable outside recover jobs and cannot create actions (R030)."
  3. "incident-sim accepts only mcp-write's token and azp; mcp-read cannot reach incident-sim (network test in T30)."
- **review_notes** (`:718-722`, verbatim):
  1. "Handle server binding is checked inside resolve_invocation by comparing the handle's server field with
     session_user (mcp_read vs mcp_exec)."
  2. "record_outcome verifies the receipt hash against the grant hash, but both reach it through mcp-write: v1 states
     plainly in the threat model that mcp-write is trusted for outcome truth, with T10's detective check as the
     control. Optional hardening for v1.1: incident-sim HMAC-signs receipts with a key held in an app_definer-only
     table. R131 wording: named function sets (both roles share resolve_invocation)."
  3. "Plan J final review (DoD note and debt): a live create_incident through mcp-write over HTTP with a fresh handle
     for the re-queued execute job of an EXECUTING run returns the same action_id and no second incident (no HTTP test
     drives that re-send today); the worker client is named once in settings, replacing the \"ops-worker\" literals in
     worker main.py's token source, read_verifier's allowed_azp and the write-path definers."
- `handoff/BUILD_BACKLOG.md:99` repeats the instructions and requirements. `docs/ARCHITECTURE.md:173` gives mcp-write
  "`mcp_exec` (6 functions)"; `:64` the role row: "**no tables**; `EXECUTE` on `resolve_invocation`,
  `grant_execution`, `mark_sent`, `record_outcome`, `request_abort`, `lookup_action` | PostgreSQL (functions),
  incident-sim | the search and asset functions; asset-sim; …"; `:170` tools "`create_incident`,
  `get_incident_receipt`, `abort_incident`"; `:175` "Cannot | … | search, read asset data, see corpus text".
- No threat-model document exists in `docs/` (only `docs/archive/SECURITY.md`, the reference's archived file);
  review note 2's "states plainly in the threat model" has no target file today.

### 1.2 Acceptance-matrix rows owned by T47, and rows that name it (`handoff/acceptance-matrix.json`)

- **R030 (:545)** — M05 / recovery; "Receipt lookup is restricted and cannot create actions"; `blocking_for_v1: true`;
  `implementation_status: NOT_IMPLEMENTED_OR_NOT_TARGET_VERIFIED`; `evidence_status: NOT_RUN`; no evidence paths;
  expected_evidence: "Normal/model tools cannot call lookup; reconciliation workload sees minimal existing-action
  outcome only."; owners: `T47` only; suggested_test
  `tests/acceptance/test_r030_receipt_lookup_is_restricted_and_cannot_create_a.py`. `handoff/ACCEPTANCE.md:36` (1.0
  snapshot) has the same wording.
- **R131 (:2236)** — M05 / security, `source: SPEC_AMENDMENTS.md`; "The read and write MCP servers hold disjoint tool
  functions and reject each other's handles"; expected_evidence: "mcp_read can EXECUTE only resolve_invocation,
  asset_scope, search_procedures_scoped; mcp_exec only resolve_invocation, grant_execution, mark_sent,
  record_outcome, request_abort, lookup_action (pg_proc ACL test); an execute/recover handle at mcp-read and a read
  handle at mcp-write are rejected; incident-sim rejects mcp-read's token."; owners `T15`, `T47`;
  `implementation_status: NOT_IMPLEMENTED_OR_NOT_TARGET_VERIFIED`, `evidence_status: RECORDED_LOCALLY_LIVE`, evidence
  `tests/e2e/test_mcp_read_t15_live.py`, `reports/mcp-read/t15-mcp-read.txt`. Note (verbatim): "Read half only (Plan
  J, T15): mcp_read can EXECUTE current_time (erratum 15) and resolve_invocation and nothing else in app (asset_scope
  and search_procedures_scoped join with T16/T17, erratum 72); an attempted grant_execution is 42501; a recover and an
  execute handle presented to mcp-read are refused over HTTP. The write half (mcp_exec's set, a read handle at
  mcp-write, incident-sim refusing mcp-read's token) -> T47."
- **R025 (:449)** — owners `T15` only, but its note ends "mcp-write's half -> T47"; expected_evidence: "An independent
  process lists and calls tools on both mcp-read and mcp-write over the network."; `implementation_status:
  NOT_IMPLEMENTED_OR_NOT_TARGET_VERIFIED`, `evidence_status: RECORDED_LOCALLY_LIVE` (read half).
- **R031 (:560)** — owners `T04`, `T15`; note ends "mcp-write's own network test -> T47" (`:577`).
- Rows T47 touches without owning them: R096 (`:1601`, T10, done: "non-executor tokens or wrong azp 403"), R084
  (`:1377`) and R124 (`:2105`) (T09, done), and T22's R048–R051, R094 ("abort yields receipt or tombstone"), R095,
  R109 ("Timeout path takes the lease lock, bumps the fence, reads the grant"), R118 ("cancel commits vs mark_sent;
  nothing is POSTed and the abort yields a tombstone") and R119 (`:825-2021`).
- `tests/acceptance/` does not exist; `pyproject.toml` `testpaths` lists `tests/plan_a` … `tests/plan_j` and
  `tests/e2e` (no `tests/plan_k`).

### 1.3 Tasks that depend on T47, and neighbours

- **T22** (`tasks.json:912-949`, M08) depends_on `["T21", "T47"]` (`:917-918`): "grant inserts INTENT; mark_sent before
  I/O; record_outcome; recover jobs with redispatch/abort rules; reconciliation backoff; transport-timeout rule;
  CONFLICT and deadlines to ESCALATED; asset guard; receipt retention." Owns R048, R049, R050, R051, R094, R095, R109,
  R110, R046, R118, R119, R125. DoD (`:936-938`): "Kill tests at INTENT, SENT, post-commit and pre-persist each end
  with one matching incident or an authoritative abort."; "Timeout during create_incident resolves via the lease-lock
  read."; "Hash conflict escalates; never success; escalated action blocks a duplicate for the same asset/interval."
  Review notes (`:942-947`, verbatim):
  1. "Redispatch skips the section 13 gate via lookup_action -> mark_sent; mark_sent re-checks cancel/deadline under
     runs lock."
  2. "Cancellation after SENT aborts immediately; otherwise abort at dispatch deadline (<=5 min FAILED latency
     stated)."
  3. "Operator CLI `ops resolve-escalation` -> ABANDONED_UNVERIFIED with operator_resolutions audit row."
  4. "Late destination evidence on ABANDONED_UNVERIFIED emits action.late_evidence; record_outcome never transitions
     terminal runs; recover jobs stay allowed."
  5. "request_abort is invoked inside create_incident after mark_sent returns cancelled/expired; allow abort after
     ABANDONED_UNVERIFIED (tombstone recorded as late evidence) with a bounded reconciliation job budget."
  6. "Attempt states are INTENT, SENT, ABORT_REQUESTED, RESOLVED (append-only rows ordered by seq); create_incident is
     refused once ABORT_REQUESTED exists (1.3.6)."
- T22's chain: T21 is PLANNED and depends on `T20`, `T11`; T20 on `T19`, `T14`, `T16`; T19 on `T07`, `T17`, `T02`,
  `T03`, `T44`; T16 on `T15`, `T10`, `T17`. So between T47 and T22 sit T17, T16, T19, T20 and T21 (T02, T03 and T44
  are `DONE_PENDING_OWNER`). T24, T25, T26, T28 and T30 each depend on T22.
- **T10** (`:518-545`, DONE): review note 1 "keep GET /internal/actions/{id}; abort stores grant hash; POST onto
  ABORTED returns tombstone regardless of hash"; note 3 "incident-sim requires azp = mcp-write client in addition to
  aud; REJECTED is a permanent key state with tombstone shape; add a detective check that every destination key
  matches a grant hash." The Plan E note (`:542`) ends: "Deferred: the abort client and the abort_incident tool ->
  T47/T22; six remaining BS:405 faults -> T13; a schedule for the detective check -> T32."
- **T30** (`:1113-1138`, PLANNED, depends on T22): review note 2 (`:1136`) "Docker network tests include: mcp-read
  cannot reach incident-sim; mcp-write cannot reach asset-sim; worker cannot reach either sim." (T47 DoD 3 points
  there.)
- **T14** review note (`:661`): "The sweeper iterates tenants and sets app.tenant_id per tenant for expiry, outbox
  delivery and deadline escalation; …".
- SA:689 (1.3.4): "T15 becomes mcp-read; new **T47** builds mcp-write (R030, R131). T16 keeps the read tools; recovery
  tools move to T47. T22 depends on T47. T08 runs both servers." ADR-0003:18: "`mcp_exec` can execute only the
  write-path functions. Capability handles are bound to one server, so a read handle presented to mcp-write is
  rejected and vice versa (R131). Only mcp-write can reach incident-sim; only mcp-read can reach asset-sim." AM-01
  (SA:77): "| `mcp-write/` | Authenticated MCP server for the guarded write and recovery tools only; DB role
  `mcp_exec` |".

---

## 2. Spec passages that bind T47

### 2.1 AM-13 (SA:220–299), verbatim where it binds

- **Who does what** (SA:223–225): "The worker never contacts the destination." "**mcp-write** is the only caller of
  incident-sim. It records every step through fenced `SECURITY DEFINER` functions (AM-20). mcp-read cannot reach
  incident-sim and holds no write-path function." "The worker drives the process by calling MCP tools under an
  `execute` or `recover` job."
- **Attempt protocol** (SA:227): "`action_attempt(action_id, attempt_no)` plus append-only `action_attempt_state(
  action_id, attempt_no, seq, state ∈ {INTENT, SENT, ABORT_REQUESTED, RESOLVED}, at)`; the latest row by `seq` is the
  state". SA:228: "`grant_execution` performs the §13 final gate. It inserts the grant **and** attempt 1 in state
  `INTENT` in one transaction, then returns `(action_id, canonical_bytes, sha256)`." SA:229–232: "`mark_sent(action_id)`
  commits `INTENT → SENT` **before** network I/O. So `INTENT` means the request was definitely not sent." / "`mark_sent`
  locks `runs` (in lock order) and re-checks `cancel_requested` and the dispatch deadline." / "If either fails, it
  returns `cancelled` or `expired` and nothing is sent. The caller then aborts [R3-B2]." / "This lock is what makes
  \"cancel in INTENT = guaranteed no-commit\" true (R118)." SA:233: "The MCP server POSTs to incident-sim." SA:234:
  "`record_outcome(action_id, outcome, receipt_or_tombstone)` inserts the `RESOLVED` state row with the verified
  receipt or tombstone, performs the run transition (AM-20.3) and appends the `source=destination` event. States are
  append-only rows in `action_attempt_state`; nothing is UPDATEd [R6-H6]."
- **Recovery table** (SA:236–244; heading: "**Recovery** (`recover` job; tools allowed by AM-20.3
  `resolve_invocation`)"):
  - SA:240 "INTENT, before dispatch deadline, not cancelled" → "Redispatch with the same `action_id` and bytes.
    Redispatch **skips the §13 gate** (the grant was the linearization point). It loads the bytes through
    `lookup_action` and then goes through `mark_sent`. `create_incident` is allowed only when there is no attempt, or
    the attempt is INTENT, not cancelled and before the deadline."
  - SA:241 "INTENT, after deadline or cancelled" → "`abort_incident` → the destination returns a tombstone →
    `record_outcome` → FAILED(`cancelled_before_send` or `expired`)."
  - SA:242 "SENT, no response" → "OUTCOME_UNKNOWN. `get_incident_receipt` with backoff 1, 2, 4, 8 s + jitter, then
    scheduled `recover` jobs. When the dispatch deadline passes, call `abort_incident`: the destination returns the
    existing receipt (→ SUCCEEDED), the existing REJECTED tombstone (→ FAILED, `rejected`), or a fresh ABORTED
    tombstone (→ FAILED, `aborted_no_commit`)."
  - SA:243 "Destination unreachable" → "Keep retrying lookup or abort. When the escalation deadline passes, →
    ESCALATED (applies to INTENT and SENT)."
  - SA:244 "Receipt received but not persisted" → "Lookup replays the same receipt; `record_outcome` is idempotent."
- **Cancellation** (SA:247–248): "In INTENT, cancellation leads to abort, a guaranteed no-commit, because of the
  `mark_sent` re-check." / "After SENT, cancellation triggers an **immediate** abort request; without a cancellation,
  abort waits for the dispatch deadline. A SENT action with a lost response can therefore take up to 5 minutes to
  become FAILED. The README states this latency. The truthful outcome is whatever the destination returns: an existing
  receipt is reported as SUCCEEDED with a \"cancellation arrived after dispatch\" note. Nothing is ever claimed as
  undone."
- **Worker transport timeout during `create_incident`** (SA:250–256): "1. Take the run lease row lock (`FOR UPDATE`).
  2. Bump the fence, which revokes the handles. 3. Read `execution_grant` by `run_id`. 4. If a grant exists, the run
  becomes OUTCOME_UNKNOWN with that `action_id` and enters recovery. If not, no grant can commit any more, because the
  fence changed." "Tested by R109."
- **Destination (incident-sim)** (SA:259–270): one table `action_key(action_id PK, payload_sha256, state ∈ {COMMITTED,
  ABORTED, REJECTED}, incident_id NULL, reason NULL, decided_at)`, "All three states are permanent and terminal";
  SA:260 "**Tombstone shape** (returned for ABORTED and REJECTED): `{action_id, state, payload_sha256, reason,
  decided_at}`"; SA:261 a validation rejection "writes a permanent `REJECTED` key, so a lost response is recoverable
  by lookup"; SA:262 "incident-sim also requires the token's `azp` to be the mcp-write client."; SA:263 both POST
  routes "use `INSERT … ON CONFLICT (action_id) DO NOTHING` and then read the row, at **READ COMMITTED** isolation";
  SA:265 "**Rows are never deleted or expired**, not even tombstones."; SA:266 "**Abort carries the grant's
  `payload_sha256`**, which the tombstone stores [R3-B1]."; SA:267 "**Hash comparison applies only to `COMMITTED`
  keys.** A POST onto an `ABORTED` or `REJECTED` key returns that tombstone whatever hash it carries, and never
  commits. An abort onto a `REJECTED` key returns the REJECTED tombstone."; SA:268 "A different hash under an existing
  `COMMITTED` key → CONFLICT."; SA:269 "`GET /internal/actions/{action_id}` (restricted lookup, §14) is retained. It
  returns COMMITTED with the receipt, ABORTED or REJECTED with the tombstone, or NOT_FOUND. NOT_FOUND is never treated
  as a no-commit [R6-B2]."; SA:270 "It accepts only the `incident-sim` audience workload token."
- **Outcome vocabulary** (SA:274–280): destination `COMMITTED / ABORTED / REJECTED`; tool outcome `SUCCEEDED /
  FAILED_NO_COMMIT / UNKNOWN / CONFLICT`; run `SUCCEEDED / FAILED / OUTCOME_UNKNOWN / ESCALATED /
  ABANDONED_UNVERIFIED`. SA:280: "`FAILED_NO_COMMIT` carries `reason ∈ {aborted_no_commit, cancelled_before_send,
  rejected}`, mapped from destination ABORTED, ABORTED-after-cancel, or REJECTED." (Erratum 2 adds `expired`, §4.)
- **Defaults** (SA:291–299, "configurable; tests use `app.current_time()`"): "Dispatch deadline | 5 minutes after
  grant"; "Escalation deadline | 30 minutes after grant"; "Request-dedup replay window | 24 hours"; "Destination keys
  and receipts | Never expire"; "`recover` cadence on ESCALATED / ABANDONED_UNVERIFIED | every 5 min for 1 h, then
  hourly, cap 48 attempts (AM-20.4)".

### 2.2 AM-10 (run states) and AM-11 (grants), where they bind the write path

- SA:119–121: ESCALATED is "Reached on `CONFLICT`, or when the escalation deadline passes with the outcome still
  unresolved." / "Reconciliation continues. `ESCALATED → SUCCEEDED | FAILED` is allowed only on destination evidence."
- SA:127–129 (ABANDONED_UNVERIFIED): "It never claims success or failure. Reconciliation keeps running. On destination
  evidence it appends **`action.late_evidence`** (payload: `outcome ∈ {SUCCEEDED, FAILED_NO_COMMIT}` plus the receipt
  or tombstone) and the run status stays ABANDONED_UNVERIFIED [R4-E4]." / "`record_outcome` makes **no state
  transition** from any terminal state; it only records evidence." / "Recover jobs remain allowed for
  ABANDONED_UNVERIFIED runs (AM-15)."
- SA:141: "EXECUTING / OUTCOME_UNKNOWN | → ESCALATED on CONFLICT, or when the escalation deadline passes (AM-13)".
- SA:152 (reasons): "`cancelled_before_send`, `aborted_no_commit`, `rejected`, `asset_action_unresolved`,
  `asset_incident_exists`, `expired`, `stale_evidence`, `authority_revoked`, `conflict`, `escalation_deadline`. A
  cancel in INTENT ends FAILED with `cancelled_before_send` [R5-S6]."
- SA:167: "**At most one grant per run, ever.** `execution_grant` gains `run_id` with `UNIQUE (run_id)`, so it never
  has a second row, even after an abort. A failed or aborted action needs a **new run** for a new incident."
  SA:168: "`action_id` is a random UUIDv4 created inside `grant_execution`."

### 2.3 AM-15 (SA:327–358): tools, job types, envelope

- Tool table (SA:331–336), verbatim:
  - SA:334 "| `create_incident(proposal_id)` | **mcp-write** | `execute` jobs; `recover` jobs for same-key redispatch
    (refused when the latest attempt state is `ABORT_REQUESTED` or `RESOLVED`) |"
  - SA:335 "| `get_incident_receipt(proposal_id)` | **mcp-write** | `recover` jobs only, including on ESCALATED and
    ABANDONED_UNVERIFIED runs |"
  - SA:336 "| `abort_incident(proposal_id)` | **mcp-write** | `recover` jobs only, including on ESCALATED and
    ABANDONED_UNVERIFIED runs (the tombstone is recorded as late evidence) [R5] |"
- SA:338: "Every job has exactly one `type`. Allowed tools are derived from type plus run state plus attempt state.
  **A handle is bound to one server:** `investigate`/`resume_input` handles are accepted only by mcp-read;
  `execute`/`recover` handles only by mcp-write (R131)."
- Job table: SA:344 "| `execute` | API with an approving decision | Final grant and first dispatch | `create_incident` |
  APPROVED, EXECUTING (attempt absent or INTENT) |"; SA:345 "| `recover` | `mark_unknown` (worker timeout path); the
  worker after a `cancelled`/`expired` tool result; `reclaim_leases` (sweeper). Never by either MCP server. Dedup keys
  in AM-20.4 [R6] | Redispatch, lookup, abort | `create_incident` (INTENT only), `get_incident_receipt`,
  `abort_incident` | EXECUTING, OUTCOME_UNKNOWN, ESCALATED, ABANDONED_UNVERIFIED |".
- SA:348: "After `mark_sent` returns `cancelled` or `expired`, `create_incident` itself calls `request_abort`, POSTs
  the abort to incident-sim, calls `record_outcome` with the tombstone, and returns `FAILED_NO_COMMIT` (reason
  `cancelled_before_send` or `expired`). No job is created by either MCP server."
- SA:350: "Every tool has an input JSON Schema in `schemas/tools/`. Arguments that supply a role, tenant, actor,
  approval or destination are rejected."
- SA:351–355: "**The envelope must agree with the data:** `status=ok` only for a read with data, or `SUCCEEDED`;
  `status=outcome` for `UNKNOWN` / `CONFLICT` / `FAILED_NO_COMMIT`, with `data.action_id` required; for an
  **authenticated, authorized** caller, `status=error` only before any grant exists; authentication and authorization
  failures always return a plain safe error, never with an `action_id`."
- SA:356: "`abort_incident` result `data`: `{action_id, outcome: SUCCEEDED|FAILED_NO_COMMIT, receipt|tombstone}`."
- SA:357: "The old `unknown` envelope status is removed." SA:358: "The caller verifies that a `SUCCEEDED` receipt's
  hash equals the proposal hash. A mismatch becomes `CONFLICT`."
### 2.4 AM-20 rows for mcp-write

- AM-20 principles (SA:387–389): every transition, grant, attempt step and event goes through a definer; audit
  tables are insert-only ("latest" is the highest `seq`); functions decide by `session_user`.
- SA:401: "| `mcp_exec` | yes | mcp-write; write-path functions only |". SA:437: "`mcp_read`, `mcp_exec` and `operator`
  have **no table grants**". SA:441: "`execution_grant` has no `state` column; grant status is derived from the latest
  `action_attempt_state` row."
- SA:446: every definer is `SECURITY DEFINER`, owner `app_definer`, `SET search_path = app, pg_temp`, `SET
  app.tenant_id = ''`; "Each migration that creates one runs, in the same transaction, `REVOKE ALL ON FUNCTION … FROM
  PUBLIC` and then `GRANT EXECUTE … TO <exactly the callers listed below>` [R6-H2]."
- Rows (verbatim, columns Function | Callers | Inputs | Locks | Effect | Event):
  - SA:459 `resolve_invocation(raw_handle, client_azp)` | `mcp_read`, `mcp_exec` | "the header value and the token's
    `azp`" | "`invocation_context` FOR SHARE → `run_lease` FOR SHARE" | "Hashes the handle inside; checks azp binding,
    **that the handle's server matches the calling role** (read handles only for `mcp_read`, execute/recover handles
    only for `mcp_exec`), expiry, current run fence; returns `{run_id, tenant_id, job_type, run_state, attempt_state,
    allowed_tools}` with the allowlist derived per AM-15" | none.
  - SA:462 `grant_execution(raw_handle, proposal_id)` | `mcp_exec` | locks "advisory(tenant, asset) → `run_lease` FOR
    SHARE → `runs` FOR UPDATE → `proposals` FOR SHARE → `decisions` FOR SHARE → `memberships` FOR SHARE →
    `execution_grant` → `action_attempt`" | "The §13 final gate: proposal belongs to the handle's run and tenant;
    approved, unexpired, hash-matching; requester and reviewer currently active; not cancelled; asset freshness (5
    min); **asset guard (AM-13)**; inserts `execution_grant` (random `action_id`, `UNIQUE(run_id)`), `action_attempt` 1
    and `action_attempt_state` INTENT; transition APPROVED → EXECUTING (or → BLOCKED_REVIEW with the refusal reason)"
    | "`action.granted` (new type) or `review.blocked`".
  - SA:463 `mark_sent(action_id)` | `mcp_exec` | "`run_lease` FOR SHARE → `runs` FOR UPDATE → `action_attempt_state`" |
    "Re-checks `cancel_requested` and the dispatch deadline; inserts state SENT (with `seq`), or returns
    `cancelled`/`expired` without inserting" | "`action.dispatched`, or `action.redispatched` when `attempt_no > 1`".
  - SA:464 `record_outcome(action_id, outcome, receipt_or_tombstone)` | `mcp_exec` | "`run_lease` FOR SHARE → `runs` FOR
    UPDATE → `action_attempt_state` → `events`" | "Idempotent; inserts state RESOLVED; verifies the hash; transition
    EXECUTING/OUTCOME_UNKNOWN/ESCALATED → SUCCEEDED, FAILED(reason) or ESCALATED(`conflict`); on a terminal run, records
    late evidence without a transition" | "`action.confirmed` / `action.failed` / `action.conflict` /
    `action.late_evidence`, all with `source=destination`".
  - SA:465 `request_abort(action_id, reason)` | `mcp_exec` | "reason ∈ {`cancelled_before_send`, `expired`,
    `deadline`}" | "as `record_outcome`" | "Inserts an `ABORT_REQUESTED` state row (append-only); the caller then POSTs
    abort to incident-sim and calls `record_outcome` with the tombstone. If the attempt is INTENT (never sent), the
    outcome is FAILED(`cancelled_before_send` or `expired`)" | "via `record_outcome`".
  - SA:466 `lookup_action(raw_handle)` | `mcp_exec` | handle | "`run_lease` FOR SHARE" | "Returns the grant's
    `action_id`, canonical bytes and hash for same-key redispatch (no gate re-run)" | none.
  - SA:467 `mark_unknown(run_id, fence)` | `worker` | "`run_lease` FOR UPDATE → `runs` FOR UPDATE → `execution_grant`
    FOR SHARE" | "Bumps the fence (revoking handles); if a grant exists, transition EXECUTING → OUTCOME_UNKNOWN and
    inserts a `recover` job" | `action.uncertain`.
  - SA:468 `escalate_run(run_id, reason)` | `worker`, `sweeper` | "reason ∈ {`conflict`, `escalation_deadline`}" |
    "Transition EXECUTING/OUTCOME_UNKNOWN → ESCALATED; releases the conversation slot" | `run.escalated`.
  - SA:469 `resolve_escalation(run_id, operator_name, reason)` | `operator` | … | `run.abandoned_unverified`.
- SA:474: "Internal helpers (`_canonicalize`, `_asset_guard`, `_allowlist`) are not granted to any role."
- "Who performs which transition" (SA:486–489): "APPROVED → EXECUTING / BLOCKED_REVIEW | `grant_execution`";
  "EXECUTING → OUTCOME_UNKNOWN | `mark_unknown`"; "EXECUTING / OUTCOME_UNKNOWN / ESCALATED → SUCCEEDED / FAILED |
  `record_outcome` (FAILED(`cancelled_before_send`) included)"; "EXECUTING / OUTCOME_UNKNOWN → ESCALATED |
  `escalate_run`, or `record_outcome` on CONFLICT".
- SA:496: "`invocation_context(handle_sha256 PK, run_id, job_id, server ∈ {read, write}, fence, azp, expires_at,
  revoked_at)`. `resolve_invocation` derives `job_type` from the referenced `jobs` row and `server` from that type
  (read for `investigate`/`resume_input`, write for `execute`/`recover`); it never trusts the worker-written `server`
  column alone [R7]."
- SA:503: "| `recover` | `mark_unknown`, `worker` (after a `cancelled`/`expired` result), `reclaim_leases` |
  `action_id:trigger` where trigger ∈ {`timeout`, `cancel`, `deadline`, `sweep:<bucket>`} |". SA:506: "`recover` jobs
  on ESCALATED or ABANDONED_UNVERIFIED runs run on a bounded cadence: every 5 minutes for the first hour, then hourly,
  with a cap of 48 attempts, after which only the operator CLI or late destination evidence changes anything."
- SA:520 (AM-20.5): "For every other table the sweeper **iterates `tenants`** … before `expire_proposal`,
  `deliver_outbox` and deadline escalation".

### 2.5 AM-20.7 items 3, 6, 11 and AM-30

- SA:538 (item 3): "**Proposals are bound to runs.** Every write or recovery function requires `proposal.run_id =
  handle.run_id` and the same tenant (R100)."
- SA:555 (item 6): "Keycloak \"Hardcoded audience\" mappers set `aud` to the **resource URLs** of mcp-read
  (`MCP_READ_RESOURCE_URL`) and mcp-write (`MCP_WRITE_RESOURCE_URL`) and to `incident-sim`; each is a parameter, not
  a hard-coded container name. … incident-sim trusts only mcp-write." SA:557: "Both MCP servers use a custom
  `TokenVerifier` that checks iss, aud ∋ its own resource URL, azp ∈ its allowed workload clients, and exp." SA:558:
  "Tests cover a missing `aud`, a wrong `aud`, and a browser token."
- SA:566 (item 11): "**`X-Ops-Invocation` is a capability lookup key only.** It is never trusted as identity and never
  logged."
- SA:571–573 (AM-30): "MCP protocol revision **2026-07-28** (session-less; `io.modelcontextprotocol/protocolVersion`
  in `_meta` must match the `MCP-Protocol-Version` header)." / "Tests check per-request version validation and
  mismatch rejection, not \"negotiation\"." / "Imports: `from mcp.server.mcpserver import MCPServer, Context` and
  `from mcp import Client`." Version table: "mcp | 2.3.0 (pulls `mcp-types==2.3.0`, `httpx2`)".

### 2.6 AM-12 (fence and lock order) as it applies to the write path

- SA:176–184: "every worker or MCP mutation for a run **first** executes: `SELECT 1 FROM run_lease WHERE run_id = :r
  AND fence = :f AND lease_until > app.current_time() FOR SHARE`. A missing row aborts the transaction."
- SA:188: lock order "asset guard advisory lock → run_lease → runs → messages → proposals → decisions → memberships →
  execution_grant → action_attempt → operator_resolutions → events → outbox". SA:191: "Any transaction that will write
  `run_lease` takes `FOR UPDATE` from the start; it never upgrades from `FOR SHARE`."
### 2.7 BUILD_SPEC §10 (BS:376–407)

- BS:378: "The official MCP server exposes typed tool contracts and safe structured results over internal Streamable
  HTTP. Pin supported protocol/SDK versions and reject unexpected negotiation/schema changes. … Use a real remote
  client in integration tests; an in-process call is not sufficient."
- BS:387 (business tools): "| `create_incident` | `proposal_id` only | Load exact payload/approval; authorize and
  grant inside the write boundary; submit stable action ID; return confirmed or unknown outcome |".
- **Required operational tool** (BS:393, verbatim): "`get_incident_receipt(proposal_id)` is **reconciliation-only**.
  It resolves the stored action ID server-side and queries the synthetic destination. Register it only for the
  reconciliation workload or filter it from normal tool discovery and calls; never bind it to the model. Result:
  `SUCCEEDED`, `FAILED_NO_COMMIT`, `UNKNOWN`, or `CONFLICT`, plus permitted matching action/hash/receipt fields. No
  receipt is `UNKNOWN` unless the destination supplies a definitive terminal no-commit record. A hash mismatch is a
  conflict, never success."
- BS:395: "A model-facing tool adapter, if added, receives only permitted read tools. The deterministic executor owns
  writes; the reconciliation worker owns receipt lookup. Do not expose a generic `send_message`, `execute_sql`,
  `run_shell`, `fetch_url`, \"approve\" or role-management tool."
- **Structured tool-result contract** (BS:399): "Use the target `tool_result` schema. Carry `tool_name`, request
  correlation ID, `status`, bounded typed `data` for the known tool, safe `error` when present, observed timestamp and
  truncation metadata. Validate tool-specific nested schemas, not just the envelope. Check both transport errors and
  the SDK's tool-error flags; a protocol-success response can still represent application failure. Preserve error
  classification and never feed raw stack traces or credentials to the model."
- BS:401: "The server derives tenant and action context from trusted records. The incident service accepts only the
  MCP executor workload, not arbitrary web/worker traffic. Allowlist the destination identifier in server
  configuration. Server-side role rechecks happen at read and write boundaries, not only during tool discovery."
- BS:405 (faults), BS:407: "Same key/same hash returns the existing result. Same key/different hash conflicts."
- Related elsewhere: BS:174 (persona table): "| reconciliation workload | internal | inspect receipts for already
  dispatched actions; cannot create new actions |"; BS:368 "Reconciliation uses a distinct service scope and context
  bound to an already dispatched action. It may inspect a minimal receipt after the original user loses access … it
  cannot retrieve newly forbidden document content or initiate another incident." (SA:34 supersedes §9's "distinct
  service scope" wording.) BS:706 (§25): "M05 — Remote MCP | … four business tools plus restricted reconciliation |
  Real transport discovery/calls, audience/replay/scope errors, no direct bypass".

### 2.8 BUILD_SPEC §13 and §14

- BS:472: "The MCP write boundary uses a shared domain function to lock the active run/proposal, read current
  requester/reviewer membership, verify the immutable bytes/hash/revision, enforce expiry/freshness/cancellation, and
  compare the active lease fence. … Persist a single execution grant/action ID and dispatch intent. Commit before
  destination I/O." BS:478: "A crash after grant but before known dispatch leads to reconciliation/recovery of the same
  grant/action ID. A fresh write after the dispatch deadline requires documented policy checks; the system must not
  create a new identity to evade expiry. Reconciliation of an existing action is allowed even after approval expiry
  because it observes, rather than authorizes a new effect."
- **Destination contract** (BS:482–489): "Only destination records establish whether an incident exists. The
  application's grant proves permission to attempt the action, not completion." / BS:486 "`POST /internal/incidents`:
  trusted executor identity plus action ID, exact canonical payload/hash and grant metadata. Atomically insert
  incident+receipt or return existing same-key receipt. Reject changed hash under existing key." / BS:487 "`GET
  /internal/actions/{action_id}`: restricted lookup returning committed receipt, authoritative terminal no-commit
  record, conflict, or unknown. All outputs include enough immutable identity/hash data to verify the result." / BS:489
  "The caller verifies action ID, payload hash, tenant context and response schema before recording success. A
  malformed, mismatched or unauthenticated receipt cannot close the action successfully."
- **Failure matrix** (BS:493–500): "Verified matching committed receipt | SUCCEEDED; record actual incident ID";
  "Explicit authoritative terminal rejection with no side effect | FAILED; retain reason and action history";
  "Connection/transport timeout after possible dispatch | OUTCOME_UNKNOWN; schedule lookup"; "Missing/delayed receipt |
  Remain unknown while acceptance/visibility may be in flight"; "Same action key with different payload hash |
  CONFLICT; stop and escalate; never silently rewrite or rekey"; "Duplicate request/callback/worker replay | Same
  stable action ID; destination returns existing receipt".
- **Unknown-outcome lookup** (BS:502): "bounded backoff (initially 1, 2, 4, 8 seconds with jitter inside one recovery
  attempt), then scheduled recovery jobs, then operator escalation after a configurable deadline. No hot infinite
  loop. Scheduled reconciliation consumes its own bounded job budget, not a human-wait or model budget. Do not resend
  the write with a new key. Same-key redispatch is permitted only under the destination's verified idempotency
  protocol and the current recovery/grant policy, not because absence was mistaken for non-commit."
- AM-00 (SA:37): "**§14:** \"authoritative terminal no-commit record\": produced by the AM-13 abort tombstone."

---

## 3. The tree as it is (branch `plan-k`, `9f34038`)

### 3.1 Every "T47" mention outside uv.lock, reference/, docs/reviews, docs/superpowers (`git grep -n T47`)

Code and tests:

| Where | Text (verbatim) | What it asks for |
|---|---|---|
| `core/src/ops_core/jobs.py:56-57` | "TODO(T47): the attempt-state dimension (`create_incident` only while the attempt is absent or INTENT, not cancelled, before the deadline) is mcp-write's, where `execution.next_step` branches on it today." | the attempt-state allowlist dimension |
| `mcp-write/README.md:25` | "T22). The verifier's T15 hardening and the recovery tools arrive with T47." | verifier parity; recovery tools |
| `tests/plan_c/test_schema_conformance.py:45` | "envelopes are built by the MCP servers (T16/T47); the data shapes are ActionOutcome" | skip reason (envelope conformance) |
| `tests/plan_j/test_worker_azp.py:7-8` | "other three still name `\"ops-worker\"`: `main.py`'s token source, `read_verifier`'s `allowed_azp` and the write-path definers' literal (T47 debt, Plan J final review)." | name the worker client once |
| `tests/e2e/test_mcp_read_process_live.py:126` and `reports/mcp-read/t15-independent-client.txt:2` | "R025 (read half; mcp-write with T47) / R031 (network half)" | mcp-write's R025/R031 half |
| `docs/runbooks/mcp-read.md:80` | "mcp-write's equivalents of the verifier hardening (T47)" | verifier parity |

Status documents (verbatim):

- Plan E open items, `SESSION_STATE.md:206`: "the abort client and the `abort_incident` tool -> T47/T22"; `:207`: "the
  pre-SENT `STALE_RUN` / `HASH_MISMATCH` envelopes and the expired-handle read-back have no dedicated test ->
  T13/T47". Plan H re-homing, `:403-404`: "the pre-SENT `STALE_RUN`/`HASH_MISMATCH` envelopes → T47".
- Plan H debt, `:760-761`: "mcp-write handles the five new incident-sim faults only through today's `classify` (rate
  limit, timeout and a malformed body become UNKNOWN, a foreign receipt hash CONFLICT, a hidden receipt a 404 on
  lookup) → T22/T47"; `:763-764`: "the pre-SENT `STALE_RUN`/`HASH_MISMATCH` envelopes → T47".
- Plan I debt, `:818-819`: "incident-sim's fault route accepts any `FaultKind`, so `outbox_sink_fail` can be armed
  there and is never consumed → T47".
- Plan J debt (`:826-856`), six lines:
  - `:826-827`: "mcp-write's verifier keeps stamping its own resource whatever `aud` holds, leaves
    `validate_token_resource` off and does not require the `typ` claim `Bearer` (mcp-read does all three, Plan J
    ruling 2) → T47";
  - `:828-830`: "the write-path definers (`grant_execution`, `lookup_action`, `mark_sent`, `record_outcome`) call
    `_resolve_handle` with a literal `'ops-worker'` instead of the presented token's `azp` (`resolve_invocation`
    compares the real one first, so a mismatch is refused there) → T47";
  - `:831-832`: "the attempt-state dimension of the allowlist (`create_incident` only while the attempt is absent or
    INTENT, not cancelled, before the deadline; T15 review note 2) stays in mcp-write's `execution.next_step` → T47
    (recover: T22)";
  - `:833-834`: "mcp-write's half of R025 (an independent client lists and calls mcp-write) and of R131 (`mcp_exec`'s
    function set, a read handle at mcp-write) → T47";
  - `:848-852`: "no test drives the EXECUTING re-queue's re-send through mcp-write over HTTP (the tool path's only
    production replay is covered in two halves: the allowlist table's (EXECUTE, EXECUTING, CREATE_INCIDENT) row and
    `GrantThenDownMcp`, which skips `resolve_invocation`); T47's DoD gains \"a live `create_incident` through
    mcp-write over HTTP with a fresh handle for the re-queued execute job of an EXECUTING run returns the same
    `action_id` and no second incident\" → T47";
  - `:853-856`: "renaming the worker's client touches four places; the mint follows the token source
    (`tests/plan_j/test_worker_azp.py`), but `main.py`'s token source (`client_id=\"ops-worker\"`), `read_verifier`'s
    `allowed_azp` and the write-path definers' literal `'ops-worker'` still name it; settings should name the worker
    client once → T47."
- Errata text naming T47: erratum 74 ends "mcp-write follows in T47" (`:574-578`); erratum 76 ends "in its allowlist
  with T47" (`:582-587`); `:604` "\"resolution ignores run and attempt state\" is half done (the run state, Task 2) and
  half re-homed (the attempt state → T47)". `STATUS.md:252-259` and `docs/PROJECT_HISTORY.md:498-499` repeat the
  deferred list and the two final-review debt items.
- Lines naming the recovery side without T47: Plan E debt `:678` "`request_abort`, `escalate_run`,
  `resolve_escalation` → T22"; `:684` "the `recover` job `mark_unknown` enqueues is claimed and finished unhandled by
  the worker → T22"; Plan H debt `:741` "the worker's transport failure still re-queues instead of taking AM-13's
  timeout path (`mark_unknown` on a transport timeout, R109; erratum 14 stands) → T22"; `:743` "the reclaim inserts
  no `recover` job … → T22 (recover)"; Plan I debt `:787` "the worker still finishes a `recover` job it does not
  handle, and OUTCOME_UNKNOWN and ESCALATED runs are not swept (the recover cadence of SA:506 included) → T22".

### 3.2 `mcp-write/` today (294 + 129 + 127 + 6 + 3 lines)

Directory: `README.md`, `pyproject.toml` (`dependencies = ["ops-core", "mcp==2.3.0", "uvicorn>=0.54,<1"]`, `:6`),
`src/ops_mcp_write/{__init__,__main__,destination,execution,server}.py`. No `Dockerfile`, no `tests/` (AM-01; T30).

`mcp-write/src/ops_mcp_write/server.py`:

- Docstring `:1-4`: "One tool, `create_incident`; the grant, the dispatch and the outcome happen here, never in the
  worker."
- `:40-41`: "Duplicated from mcp-read on purpose: members never import each other (ADR-0001, test_layout); the shape is
  pinned by the tool-result contract tests in both packages." `ToolResult` (`:44-53`), `stamp` (`:56-58`),
  `tool_error(code, message, *, retryable=False)` (`:61-63`; mcp-read's has no `retryable`, `mcp-read/…/server.py:65`),
  `refusal_error` (`:66-70`: `MEMBERSHIP_STALE` → retryable `GRANT_DEFERRED`, everything else `GRANT_REFUSED "grant
  refused: <code>"`), `envelope` (`:73-83`: `status` `"error"` iff an error is given, else `"ok"`; fresh `uuid4`
  `request_id`; `truncated` always `False`).
- `Verifier` Protocol (`:86-100`), `McpVerifier` (`:103-125`): `verify_token` returns `None` on `TokenRejected`
  (`:115-116`), else an `AccessToken(… resource=self._resource …)` (`:117-125`) — **no** audience-containment check
  before stamping. `strict_tool` (`:128-142`). `serve_app` (`:145-152`, 127.0.0.1, selector loop on Windows).
- `outcome_envelope` (`:155-161`): `data = outcome.model_dump(mode="json")`; `envelope("create_incident", data=…)`;
  `status` set to `"outcome"` for every non-SUCCEEDED outcome. Hard-wired to the tool name `create_incident`.
- `State(deps: execution.Deps | None, verifier)` (`:164-169`).
- **Registered tools:** one. `create_incident(proposal_id: Annotated[UUID, Field(strict=False)], ctx)` (`:176`). Body:
  `token = get_access_token()`; `handle = (ctx.headers or {}).get("x-ops-invocation")` (`:178-179`); no token, no
  handle or no deps → `envelope(error=INVALID_HANDLE "missing invocation handle")` (`:180-181`). Then one unit
  `persistence.resolve_invocation(conn, handle=handle, azp=token.client_id, tool=ToolName.CREATE_INCIDENT)`
  (`:183-186`, comment "binds server, azp, expiry and the tool allowlist before any work (SA:459)"); then
  `execution.create_incident(state.deps, handle=handle, proposal_id=proposal_id)` (`:187`), which passes the raw
  handle, not the token's azp, to every definer. Error mapping (`:188-199`): `HandleRejected` → `INVALID_HANDLE`
  (message "invocation handle rejected"); `Refused` → `refusal_error(code)`; `NotFound` → `NOT_FOUND "run not found"`;
  `VersionConflict` → `STALE_RUN "run is no longer executing"` (comment `:195-196`: "Only grant_execution and mark_sent
  can raise this here, both before this call sends anything"); `HashMismatch` → `HASH_MISMATCH "stored bytes do not
  match"`. `:200-201`: "AuthorityViolation stays unmapped on purpose: it is a deployment error". Success →
  `outcome_envelope(outcome)` (`:202`). The `Invocation` that `resolve_invocation` returns (including
  `attempt_state`) is discarded.
- `MCPServer(name="mcp-write", auth=AuthSettings(…, validate_token_resource=False), token_verifier=McpVerifier(…),
  tools=[strict_tool(create_incident)])` (`:204-211`).
- `build_app` (`:214-276`): `streamable_http_app(streamable_http_path=MCP_PATH, stateless_http=True,
  json_response=True)` (`:216`). Lifespan (`:218-252`): connect as `Role.MCP_EXEC` (`:223`), `assert_clock_profile`
  (`:225`), `assert_relation(conn, "app.model_permit")` (`:227`, revision 0007), `assert_function_text(conn,
  *persistence.HANDLE_BINDING)` (`:230`, revision 0009; added in the Plan J final-review wave), close on failure
  (`:231-233`); `execution.Deps(session, http=httpx2.AsyncClient(), destination_url=settings.urls().incident_sim,
  destination_token=WorkloadTokenSource(token_url=kc.token_url, client_id="ops-mcp-write",
  client_secret=settings.read_secret("kc_client_secret_ops_mcp_write")))` (`:235-244`); keys loaded (`:246-247`).
  Health `/health/live`, `/health/ready` (`:254-266`); routes `Mount("/", app=ProtocolVersionGuard(mcp_app))`
  (`:273`, "The version rule runs before the SDK app and its bearer auth (AM-30, Plan J ruling 4)").
- `production_app` (`:279-287`): `TokenVerifier(issuer=kc.issuer, audience=urls.mcp_write_resource,
  allowed_azp=frozenset({"ops-worker"}), jwks_url=kc.jwks_url)` (`:283-285`) — no `token_type`. `serve` (`:290-294`):
  `redaction.install()`, port `OPS_MCP_WRITE_PORT` default 8082.

`mcp-write/README.md:5-25`: "## Owns create_incident, receipt lookup, abort"; "## Trusts Workload token with its
audience; the six write-path functions"; "## Never Any read function; asset-sim; corpus text"; "## Runs (T08, T15)".

### 3.3 `execution.py` and `destination.py`: how `create_incident` drives the attempt protocol

`mcp-write/src/ops_mcp_write/execution.py` (129 lines):

- Docstring `:1-12`: the replay rule — "execution_grant is UNIQUE (run_id), so a second `create_incident` for the
  same run finds the existing grant; if its attempt is RESOLVED the stored outcome is returned without touching the
  destination, otherwise the same action id and bytes are re-sent and the destination's idempotent key answers. …
  Through the tool, the stored branch is unreachable once the outcome is recorded: the run has left APPROVED and
  EXECUTING, so `server.create_incident`'s `resolve_invocation` refuses the handle first (T15, Plan J ruling 6) … A
  transport failure after SENT is reported as UNKNOWN and recorded by nobody here: the worker holds `mark_unknown`
  (SA:467; Plan E ruling 6)."
- `_POST_SENT_REFUSALS = (persistence.PersistenceError, IllegalTransition, EventRuleViolation)` (`:37`; comment
  `:33-36`: after SENT "the only answers then are a recorded outcome or UNKNOWN").
- `next_step(attempt_state)` (`:40-48`): `RESOLVED` → `"stored"`, `INTENT` → `"send"`, `SENT` → `"resend"`, anything
  else (incl. `ABORT_REQUESTED`, `None`) → `ValueError("… not handled by the walking skeleton")`.
- `Deps(session, http, destination_url, destination_token)` (`:51-58`). `_stored(grant)` (`:61-65`) parses
  `grant.detail` into `ActionOutcome`. `_read_back` (`:68-81`): `lookup_action` in its own unit; `HandleRejected` or a
  post-SENT refusal → `destination.unknown(…)`.
- `create_incident(deps, *, handle, proposal_id)` (`:84-129`), "Four units of work in AM-13 order":
  1. unit: `persistence.grant_execution(conn, handle=…, proposal_id=…)` (`:86-87`) — a first call inserts the grant
     and INTENT; a replay returns the existing grant (§3.6).
  2. `step = next_step(grant.attempt_state)` (`:88`); `"stored"` → return the recorded outcome (`:89-90`).
  3. `"send"` only: unit `persistence.mark_sent(conn, handle=…, action_id=…)` (`:91-93`, "committed before I/O");
     `"resolved"` → `_read_back` (`:94-95`); `"cancelled"` → `destination.unknown(…)` with the comment (`:96-100`):
     "The UNKNOWN envelope makes the worker call mark_unknown, which moves the run to OUTCOME_UNKNOWN and queues a
     recover job although nothing was sent: conservative. TODO(T22): request_abort and the abort POST replace this."
     `"sent"` and `"already_sent"` fall through to the POST. **`"resend"` (attempt SENT) skips `mark_sent`
     entirely**: no new state row, no `action.redispatched` event, no cancel/deadline re-check.
  4. POST: `destination.post_incident(…, token=await deps.destination_token.token(), …)` and `classify` (`:101-110`);
     any exception → `UNKNOWN` (`:111-113`); a classified `UNKNOWN` is returned without recording (`:114-117`).
  5. unit: `persistence.record_outcome(conn, handle=…, action_id=…, outcome=…)` (`:120-122`); a post-SENT refusal →
     `UNKNOWN` (`:123-125`); if the standing outcome equals ours return it (`:126-127`), else `_read_back` (`:128-129`).
- No `request_abort`, abort POST, GET lookup, backoff, deadline or attempt-number logic exists in mcp-write.

`mcp-write/src/ops_mcp_write/destination.py` (127 lines):

- `post_incident` (`:37-67`): body `canonical_json({"action_id", "payload_sha256", "payload_canonical": bytes decoded
  as one JSON string})`; `POST {url}/internal/incidents`, `Authorization: Bearer <ops-mcp-write token>`, timeout 10 s
  (`:56-61`); `httpx2.HTTPError` or non-JSON → `None` (`:63-64`); non-dict → `None`.
- `unknown(action_id, sha)` (`:70-79`), `_conflict` (`:82-90`).
- `classify(reply, *, action_id, payload_sha256)` (`:93-127`): `None` → UNKNOWN; `409` with `state == "CONFLICT"` →
  CONFLICT; any other non-200 (404, 429, 503, …) → UNKNOWN; `action_id` or `payload_sha256` ≠ ours → CONFLICT
  (`:103-104`, "a receipt for something else is not our receipt"); `COMMITTED` → SUCCEEDED with the parsed `Receipt`;
  otherwise `DestinationState(doc["state"])` + `Tombstone`, mapped through
  `outcome_from_destination(state, sent=True, cancel_requested=False)` (`:117`); parse errors → UNKNOWN. No GET or
  abort client exists.
- `ops_core.outcomes.outcome_from_destination` (`core/src/ops_core/outcomes.py:43-65`): COMMITTED → SUCCEEDED;
  REJECTED → FAILED_NO_COMMIT/`rejected`; ABORTED with `sent` → `aborted_no_commit`; ABORTED without `sent` →
  `cancelled_before_send` if `cancel_requested` else `expired` ("`sent` is the hinge", `:48-52`).
- `ActionOutcome` (`outcomes.py:97-131`): `status, action_id, payload_sha256, receipt, tombstone, reason`; SUCCEEDED
  carries exactly a receipt; FAILED_NO_COMMIT a tombstone and a reason from the FAILED set, the tombstone's
  `action_id`/`payload_sha256` must equal the outcome's, REJECTED iff reason `rejected`; UNKNOWN and CONFLICT carry
  none. There is no field for SA:248's "cancellation arrived after dispatch" note.

### 3.4 Verifier parity: mcp-read (after Plan J) against mcp-write (today)

| Check | mcp-read | mcp-write |
|---|---|---|
| Constructor | `read_verifier(kc, urls)` shared by production and unit tests (`mcp-read/…/server.py:265-275`) | inline in `production_app` (`mcp-write/…/server.py:283-285`) |
| `typ` claim `Bearer` | `token_type="Bearer"` (`:274`) | not set (`TokenVerifier.token_type=None`, `core/src/ops_core/tokens.py:89`) |
| aud containment in the SDK adapter | `if self._resource not in principal.audiences: return None` (`:140-141`) | none; stamps `resource=self._resource` (`:122`) |
| `validate_token_resource` | `True` (`:207`) | `False` (`:207`) |
| `allowed_azp` | `frozenset({"ops-worker"})` (`:272`) | `frozenset({"ops-worker"})` (`:284`) |
| Version guard | `ProtocolVersionGuard` | `ProtocolVersionGuard` (`:273`) |
| Startup | clock profile + `HANDLE_BINDING` | clock profile + `app.model_permit` + `HANDLE_BINDING` (`:225-230`) |

`TokenVerifier.__init__` (`tokens.py:78-108`): keyword-only `issuer, audience, allowed_azp, jwks_url`, `algorithms`,
`required_claims` (`exp, iss, aud, sub` always), `require_azp`, `typ` (JOSE header), `token_type` (the payload's `typ`
claim, Plan J ruling 2). PyJWT checks `aud` with list containment; `azp ∉ allowed_azp` raises `WrongAudience`
(Plan J sheet §3.4). The worker's single token carries both MCP audiences (`reports/bootstrap/keycloak-claims.txt:10`:
`aud: ["http://mcp-read:8081/mcp", "http://mcp-write:8082/mcp", "account"]`, `azp: "ops-worker"`).

### 3.5 Core: resolution, the allowlist and the job rules

- `persistence.Invocation` (`core/src/ops_core/persistence.py:383-392`): `run_id, job_id, job_type, tenant_id,
  conversation_id, run_state, attempt_state`.
- `allowed_tool(job_type, run_state, tool)` (`:395-406`): tool ∉ `JOB_RULES[job_type].allowed_tools` → log "tool %s is
  not allowed for job type %s" and `HandleRejected("invocation handle rejected")`; `run_state ∉ rule.run_states` →
  log "job type %s does not run in state %s" and the same refusal. It takes no attempt state.
- `resolve_invocation(conn, *, handle, azp, tool)` (`:414-431`): `SELECT * FROM app.resolve_invocation(%s, %s)`; no row
  → `HandleRejected`; `allowed_tool(job_type, run_state, tool)`; returns `Invocation`.
- `grant_execution` (`:463-468`), `lookup_action` (`:471-476`, `NotFound("no grant for this run")` on no row),
  `mark_sent` (`:479-485`, docstring "`sent`, `already_sent`, `resolved` or `cancelled` (SA:463)"; no `expired`),
  `record_outcome` (`:488-500`, refuses `UNKNOWN` in Python with `ValueError("UNKNOWN is recorded by the worker through
  mark_unknown, never as an outcome")`), `mark_unknown` (`:319-328`, returns `Unknown(state, fence)`). No
  `request_abort` wrapper. `Grant` (`:434-445`): `action_id, run_id, proposal_id, tenant_id, conversation_id,
  payload_sha256, payload_canonical, attempt_state, detail`.
- `translate` (`:84-94`): `OC008` → `HandleRejected("invocation handle rejected")`, "one message for every refusal";
  `OC005` → `Refused(detail)`; `OC002` → `NotFound`; `OC003` → `VersionConflict`; `OC007` → `HashMismatch`.
- `HANDLE_BINDING` (`:183`): `("app._resolve_handle(text, text, text)", "j.run_id = v_ctx.run_id AND j.done_at IS
  NULL")`; `assert_function_text` (`:186-195`).
- `ops_core.jobs` (`core/src/ops_core/jobs.py`): `Tool` has the six names incl. `GET_INCIDENT_RECEIPT`,
  `ABORT_INCIDENT` (`:19-27`); `JobRule` docstring with the `TODO(T47)` (`:51-64`); `JOB_RULES[EXECUTE]` (`:87-94`):
  `{CREATE_INCIDENT}`, `{APPROVED, EXECUTING}`, `Server.WRITE`, created by `record_decision`; `JOB_RULES[RECOVER]`
  (`:95-102`): `{CREATE_INCIDENT, GET_INCIDENT_RECEIPT, ABORT_INCIDENT}`, `{EXECUTING, OUTCOME_UNKNOWN, ESCALATED,
  ABANDONED_UNVERIFIED}`, `Server.WRITE`, created by `("mark_unknown", "worker", "reclaim_leases")`; `RECOVER_CADENCE
  = (300, 3600, 48)` (`:109`, read only by `tests/plan_c/test_jobs_routes_outcomes.py:85`); recover dedup triggers
  `timeout|cancel|deadline|sweep:<bucket>` (`:116`).
- `ops_core.states.AttemptState` (`core/src/ops_core/states.py:60-66`): `INTENT, SENT, ABORT_REQUESTED, RESOLVED`.
  `Reason` (`:45-58`) has `expired` and `escalation_deadline`, no `deadline`.
- Where the attempt-state dimension sits today: only in `execution.next_step` (§3.3) and in the definers' own guards
  (§3.6). `tests/plan_j/test_allowlist.py:22` tables every (job type, run state, tool) pair against `JOB_RULES`.
- Deadlines: no setting, column or code holds the 5-minute dispatch or 30-minute escalation deadline.
  `execution_grant.granted_at` is set to `app.current_time()` by `grant_execution` (`0005_sessions_login_logout.py:142-144`); `mark_sent`
  carries "TODO(T22): the dispatch deadline" (`0007_leases_fences.py:212`); `escalate_run` does not exist.

### 3.6 The definer bodies (as the head revision 0009 leaves them)

- **`app._resolve_handle(text, text, text)`** — 0009's body (`0009_handle_binding.py:42-49`) is 0007's
  (`0007_leases_fences.py:122-171`) with the job read replaced: hash lookup (no lock); `run_lease FOR SHARE`; refuse
  `OC008` on no lease, fence ≠ handle fence, lapsed lease, revoked, expired, or `ctx.azp <> p_client_azp`
  (`0007:146-149`); `SELECT j.type … WHERE j.id = v_ctx.job_id AND j.run_id = v_ctx.run_id AND j.done_at IS NULL`
  (0009); server derived from the job type and compared with the caller's server **and** the stored column
  (`0007:152-158`); returns the run's state and the latest attempt state via `execution_grant` + `_latest_attempt`
  (`0007:163-167`).
- **`app.resolve_invocation(text, text)`** (`0004_write_path_functions.py:238-251`, never re-created):
  `_authority(… ARRAY['mcp_read','mcp_exec'])`; server `CASE WHEN session_user::text = 'mcp_read' THEN 'read' ELSE
  'write' END` (`:245-247`) — T47 review note 1's mechanism, live since 0004.
- **`app.grant_execution(text, uuid)`** — 0005's body (`0005_sessions_login_logout.py:81-153`) with 0007's comment
  change (`0007:174-182`): `_resolve_handle(p_raw_handle, 'ops-worker', 'write')` (`0005:96`); `runs FOR UPDATE`;
  **replay first**: an existing grant for the run returns `_grant_row` (refusing `OTHER_PROPOSAL` if the proposal
  differs) before any state, cancel or membership check (`0005:99-105`); then `PROPOSAL_NOT_IN_RUN`,
  `NOT_ACTIVE_APPROVED`, `NO_APPROVAL`, `CANCELLED`, `MEMBERSHIP_INACTIVE`, `MEMBERSHIP_STALE`; "TODO(T21): asset
  freshness (5 min) and the asset guard advisory lock"; inserts grant, attempt 1, INTENT (seq 1); `_transition(…
  'EXECUTING', 'grant_execution', … 'action.granted' …)`.
- **`app.lookup_action(text)`** (`0004:335-353`, never re-created): `_authority('lookup_action', ARRAY['mcp_exec'])`;
  `_resolve_handle(p_raw_handle, 'ops-worker', 'write')` (`:343`); the run's grant or `OC002 not_found` DETAIL `grant`;
  returns `_grant_row` (incl. `payload_canonical`, latest `attempt_state`, `detail`). No tool or run-state check.
- **`app.mark_sent(text, uuid)`** (`0007:184-225`): `_resolve_handle(…, 'ops-worker', 'write')` (`:195`); grant must
  be the handle's run's (`OC002`); `runs FOR UPDATE`; latest RESOLVED → `'resolved'`; SENT → `'already_sent'`; run
  state ≠ `EXECUTING` → `OC003` (`:208-211`); `cancel_requested` → `'cancelled'`; else inserts SENT at
  `v_latest.attempt_no`, `seq + 1`, and `action.dispatched` (or `action.redispatched` when `attempt_no > 1`). It never
  returns `expired`, and accepts an attempt in `ABORT_REQUESTED` (only RESOLVED and SENT short-circuit). Nothing in the
  tree creates an `action_attempt` row with `attempt_no > 1`.
- **`app.record_outcome(text, uuid, text, jsonb)`** (`0007:228-314`): `_resolve_handle(…, 'ops-worker', 'write')`
  (`:242`); grant of the handle's run; `runs FOR UPDATE`; latest RESOLVED → returns the stored outcome ("idempotent
  (SA:464): the first record stands"); outcome ∈ {SUCCEEDED, FAILED_NO_COMMIT, CONFLICT} else `OC005`;
  **SUCCEEDED/CONFLICT require the latest state `SENT`** (`OC003 'outcome before SENT'`, `:257-259`), so after an
  `ABORT_REQUESTED` row an abort answered by the existing receipt could not be recorded as SUCCEEDED; FAILED_NO_COMMIT
  needs a tombstone object; hash must equal the grant's unless CONFLICT (`OC007`); `action_id` must match; inserts
  RESOLVED with the document; transitions EXECUTING/OUTCOME_UNKNOWN/ESCALATED to the implied state; on SUCCEEDED,
  FAILED or ABANDONED_UNVERIFIED runs appends `action.late_evidence` (non-CONFLICT), else
  `action.confirmed`/`action.failed`/`action.conflict` with `source=destination`.
- **`app.mark_unknown(uuid, bigint)`** (`0007:317-368`, `worker` only): lease row FOR UPDATE, stale fence → `OC003`;
  bump fence; revoke the old fence's handles; run already OUTCOME_UNKNOWN → only the bump; run ≠ EXECUTING → `OC003`
  (so an APPROVED run with no grant is refused, not "no grant can commit"); grant found → `OUTCOME_UNKNOWN`,
  `action.uncertain`, and `INSERT … jobs (type 'recover', dedup '<action_id>:timeout') ON CONFLICT DO NOTHING`.
- **`request_abort`, `escalate_run`, `resolve_escalation` do not exist** in any revision or in
  `privileges.DEFINER_FUNCTIONS`; the Plan E debt names them "→ T22" (`SESSION_STATE.md:678`). Plan E ruling 1
  (`…first-slice-e…md:44`): definers without a caller arrive with their owners; stub bodies were rejected.
- Literal azp: `'ops-worker'` in `0004:268` (grant 0004), `0004:343` (lookup_action), `0005:96` (grant, current
  body), `0007:195` (mark_sent), `0007:242` (record_outcome). `resolve_invocation` compares the token's azp
  (`p_client_azp`).
- Tables (`0001_walking_skeleton.py:170-195`): `execution_grant(action_id PK, run_id UNIQUE, proposal_id,
  payload_sha256, granted_at)`; `action_attempt(action_id, attempt_no, created_at)`; `action_attempt_state(action_id,
  attempt_no, seq, state CHECK IN ('INTENT','SENT','ABORT_REQUESTED','RESOLVED'), outcome, detail jsonb, at)`
  (tenant columns added in 0002).
- Head revisions: `0009_handle_binding` (main), `tc_0001_test_clock` (branch). Revisions re-create functions from
  frozen bodies (`FUNCTIONS` tuples) with exact downgrades by re-running applied revisions' bodies
  (`0007:1-23`, `0009:1-14`).

### 3.7 The `mcp_exec` role's EXECUTE grants and the R131-related tests

- `core/src/ops_core/privileges.py:185-201` (`DEFINER_FUNCTIONS`): `mcp_exec` appears in `current_time` (via
  `RUNTIME_ROLES`, `:31`, erratum 15), `resolve_invocation` (`:195`, with `mcp_read`), `grant_execution` (`:196`),
  `mark_sent` (`:197`), `record_outcome` (`:198`), `lookup_action` (`:199`). So `mcp_exec`'s EXECUTE set in `app` is
  `{current_time, resolve_invocation, grant_execution, mark_sent, record_outcome, lookup_action}` — R131's list minus
  `request_abort`, plus `current_time`. `HELPER_FUNCTIONS` (`:204-213`) go to nobody.
- Tests that pin it today:
  - `tests/e2e/test_definers_run_path_live.py:329` (`test_function_catalog_shape`): every definer's ACL grantees equal
    its matrix callers.
  - `tests/e2e/test_roles_live.py:82` (R124) and `:117` (R084, function-only roles cannot read or lock any table);
    `tests/e2e/test_definers_write_path_live.py:625` (`test_mcp_exec_cannot_reach_the_tables_the_functions_touched`).
  - `tests/e2e/test_migration_0008_live.py:242` (`test_no_function_an_mcp_server_may_call_inserts_a_job`): every
    function `mcp_read`/`mcp_exec` may EXECUTE, transitively, is free of an INSERT into `jobs`.
  - `tests/e2e/test_mcp_read_t15_live.py:267` is the read-half ACL equality (`{current_time, resolve_invocation}`
    for `mcp_read`; `grant_execution` → `42501`). No mcp_exec equivalent exists.
- A read handle at `mcp_exec`: refused at the definer/persistence level
  (`tests/e2e/test_migrations_and_persistence.py:186`; `tests/e2e/test_definers_write_path_live.py:284`). **Not
  tested over HTTP at mcp-write.** `tests/e2e/test_mcp_read_t15_live.py:206-264` uses `mcp_exec` at the definer as the
  positive control for write handles refused at mcp-read.

### 3.8 incident-sim's API (`incident-sim/src/ops_incident_sim/app.py`, 288 lines; `keys.py`, 131 lines)

- Trust (`app.py:1-3`, `:281-288`): `TokenVerifier(issuer=kc.issuer, audience="incident-sim",
  allowed_azp=frozenset({"ops-mcp-write"}), jwks_url=kc.jwks_url)`. `caller` (`:143-149`): `WrongAudience` →
  `WrongService` → 403 `FORBIDDEN "token is not for this service"` (`:157-159`); other `TokenRejected` → 401
  `UNAUTHENTICATED` with `WWW-Authenticate: Bearer` (`:151-155`). The same `caller` guards every route below.
- `POST /internal/incidents` (`:180-230`): body `IncidentRequest(action_id, payload_sha256, payload_canonical)`
  (`:76-80`, strict, extra forbidden); unparseable → 422; faults `timeout_before_accept` (sleep then 503) and
  `rate_limit` (429, `Retry-After: 1`) before anything is written; payload not a non-empty object → REJECTED
  `invalid_payload`; recomputed hash ≠ presented → REJECTED `hash_mismatch`; `reject_next` → REJECTED `policy`;
  `drop_before_commit` → 503, nothing written; commit; `lose_after_commit` → 503 after commit; DB error → 503;
  `malformed_response` and `receipt_hash_mismatch` corrupt the answer about a committed key.
- `POST /internal/actions/{action_id}/abort` (`:232-246`): body `AbortRequest(payload_sha256, reason:
  Literal["cancelled_before_send", "expired", "deadline"])` (`:83-88`); `keys.abort` → `INSERT … ('ABORTED', reason)
  ON CONFLICT DO NOTHING` then read (`keys.py:78-98`); answer `keys.document(row, presented_sha256=body.payload_sha256)`
  — an existing COMMITTED key with the same hash → 200 with the receipt; with another hash → 409 `CONFLICT`; an
  existing ABORTED/REJECTED key → that tombstone. **No fault hook** on this route.
- `GET /internal/actions/{action_id}` (`:264-276`): `lookup`; `delay_receipt` hides an existing row; no row → 404
  `NOT_FOUND "no such action"`; else `keys.document(row, presented_sha256=row.payload_sha256)` — the GET compares the
  row with itself, so it never answers CONFLICT; the caller compares against the grant hash.
- `keys.document` (`keys.py:112-131`): `{state, action_id, payload_sha256}` plus `receipt{receipt_id, incident_id,
  committed_at}` for COMMITTED or `tombstone{action_id, state, payload_sha256, reason (row.reason or state.lower()),
  decided_at}` otherwise. `ABORT_REASONS = ("cancelled_before_send", "expired", "deadline")`, `REJECTION_REASONS =
  ("invalid_payload", "hash_mismatch", "policy")` (`keys.py:22-23`).
- Fault route `POST /internal/faults/{kind}` (`:248-262`, test profile only) accepts any `FaultKind`
  (`core/src/ops_core/testing/faults.py:18-29`: the eight destination hooks plus `outbox_sink_fail`).
- Tests: `tests/plan_e/test_incident_sim_t10.py:44` (wrong audience 403, no action id), `:51` (abort then POST →
  tombstone whatever the hash), `:74` (abort after commit → receipt), `:85` (bad reason 422, no key), `:93`, `:114`;
  `tests/e2e/test_incident_sim_live.py:20, :41, :83, :115, :138` (replay/conflict, permanence, races R047/R096, R010,
  rejection). R105 (`tests/e2e/test_r105_walking_skeleton.py:201-206`) asserts a persona token and the **worker**
  token get 403 at the destination. No test presents an **`ops-mcp-read`** token to incident-sim (R131's "incident-sim
  rejects mcp-read's token").

### 3.9 The worker: execute, recover and `mark_unknown`

- `worker/src/ops_worker/handlers.py:212-266` (`execute`): in one fenced unit it reads the run; returns if the state
  ∉ `JOB_RULES[EXECUTE].run_states` (`:226`); mints a `Server.WRITE` handle with `azp=deps.workload_azp` at
  `lease.fence` (`:230-237`); calls `create_incident` with `{"proposal_id": …}` under `lease.effect` (`:238-243`).
  `McpCallFailed` → re-queue in 30 s (`:244-251`, "TODO(T22): bounded retries, reconciliation and AM-13's timeout
  path"); `GRANT_DEFERRED` → re-queue (`:253-261`); an `outcome` envelope whose `data.status == "UNKNOWN"` →
  `_mark_unknown` (`:263-265`); anything else counts as final.
- `_mark_unknown` (`:269-294`): `lease.begin_refence()`, `persistence.mark_unknown(conn, run_id, fence)`, the new
  fence handed to the shared `Lease`.
- `handle` (`:296-307`): dispatches `INVESTIGATE` and `EXECUTE`; every other type, `recover` included, logs "job %s of
  type %s is not handled by the walking skeleton" (`:305`) and is finished by `release_lease`.
- The worker never creates a `recover` job itself (AM-20.4 lists it as a creator "after a `cancelled`/`expired`
  result"); the sweeper's reclaim inserts none (erratum 49). Only `mark_unknown` inserts one (`:timeout`).
- Client: `worker/src/ops_worker/mcp.py:59-76` (`HttpMcpCaller.call`): one connection per call, headers
  `Authorization` and `X-Ops-Invocation`, `Client(…, mode=PROTOCOL_VERSION)`, `call_tool`; `is_error` or a non-dict
  result raise `McpCallFailed`. Token source `WorkloadTokenSource(client_id="ops-worker", …)`
  (`worker/src/ops_worker/main.py:136-140`).

### 3.10 Schemas for the write tools

- `schemas/tools/create_incident.input.schema.json`, `get_incident_receipt.input.schema.json`,
  `abort_incident.input.schema.json`: identical shape — `additionalProperties: false`, one property `proposal_id`
  (string, `format: uuid`), required. **`abort_incident` takes no reason** (SA:465's `request_abort` does).
- `schemas/tool-result.schema.json`: `create_incident` (`:388-…`) and `get_incident_receipt` (`:716-…`) with `ok` or
  `outcome` have the `ActionOutcome` data shape (`status ∈ {SUCCEEDED, FAILED_NO_COMMIT, UNKNOWN, CONFLICT}`,
  `action_id`, `payload_sha256`, …; `additionalProperties: false`); `abort_incident` (`:1044-…`) data is
  `{action_id, outcome ∈ {SUCCEEDED, FAILED_NO_COMMIT}, receipt, tombstone}`, all four required,
  `additionalProperties: false` (no `payload_sha256`, no `reason`), tombstone `state ∈ {ABORTED, REJECTED}`, `reason`
  string ≤500. Rules (`:1275-1414`): `status=outcome` only for the three write tools and requires `data.action_id`;
  `create_incident`/`get_incident_receipt` `outcome` ⇒ `data.status ∈ {UNKNOWN, CONFLICT, FAILED_NO_COMMIT}`, `ok` ⇒
  `SUCCEEDED`; `abort_incident` `ok` ⇒ `outcome SUCCEEDED`, `outcome` ⇒ `FAILED_NO_COMMIT`.
- Examples: `schemas/examples/tool-abort_incident-valid.json` (`status: outcome`, tombstone `reason: "cancelled before
  send"` with spaces, while incident-sim writes `cancelled_before_send`); `tool-get_incident_receipt-valid.json`
  (`outcome`/UNKNOWN); `tool-get_incident_receipt-invalid-unknown.json` (the removed `unknown` status);
  `tool-create_incident-valid.json`, `tool-create_incident-failed-valid.json`.

### 3.11 Keycloak and settings (names only; no secret values)

- Realm `deploy/dev/keycloak/realm-ops-dev.json`: client `ops-worker` (`:39-63`) with mappers "aud mcp-read resource"
  (`:50`, `${MCP_READ_RESOURCE_URL}`) and "aud mcp-write resource" (`:57`, `${MCP_WRITE_RESOURCE_URL}`); client
  `ops-mcp-write` (`:86-103`, "mcp-write (workload; calls incident-sim)", service account) with one mapper "aud
  incident-sim" (`:97`, `included.custom.audience: incident-sim`, `:101`); client `ops-mcp-read` (`:66-83`) with "aud
  asset-sim". No client other than `ops-worker` carries the mcp-write audience.
- Recorded claims: `ops-mcp-write` → `aud: ["incident-sim", "account"]`, `azp: "ops-mcp-write"`
  (`reports/bootstrap/keycloak-claims.txt`). Pinned by `tests/plan_b/test_realm_template.py:91-94` and
  `tests/plan_b/live/test_keycloak_tokens.py:47`.
- `settings.Urls` (`core/src/ops_core/settings.py:421-436`): `mcp_write_resource` (`MCP_WRITE_RESOURCE_URL`, default
  `http://mcp-write:8082/mcp`), `mcp_write` (`OPS_MCP_WRITE_URL`, `http://127.0.0.1:8082/mcp`), `incident_sim`
  (`OPS_INCIDENT_SIM_URL`, `http://127.0.0.1:8090`). No setting names the worker client; secret file name
  `kc_client_secret_ops_mcp_write`. `scripts/skeleton.py:273` starts `Process("mcp-write", "ops_mcp_write", 8082)`.

### 3.12 Existing mcp-write tests and what they prove

- `tests/plan_d/test_mcp_write.py` (unit): `classify` SUCCEEDED only on matching id and hash (`:37`); CONFLICT,
  UNKNOWN and tombstone reasons (`:45`); envelopes validate against the schema and an error envelope never names an
  action (`:77`); `next_step` (`:110`, `ABORT_REQUESTED` → `ValueError`, "T22 territory"); in-process `Client(mcp)`
  lists exactly `{"create_incident"}`, schema matches, an extra argument is `is_error`, no handle → `status=error`
  (`:131`).
- `tests/plan_j/test_mcp_read_http.py:155` (`test_mcp_write_carries_the_same_guard`): POST without the version header
  → 400/-32022. `tests/plan_j/test_mcp_read_startup.py:88`, `:97`: mcp-write refuses a database before 0009 and closes
  the connection; starts at 0009.
- `tests/plan_h/test_write_path_fence.py:62`, `:82`: a moved fence before SENT refuses and sends nothing; after SENT
  it is UNKNOWN. `tests/plan_f/test_grant_deferred.py:20-57`: `MEMBERSHIP_STALE` is the one deferred refusal.
- `tests/e2e/test_mcp_write_live.py` (live, direct `execution.create_incident` calls, not the tool): `:95` the write
  path twice (one action id, one incident, the stored outcome without a second POST); `:180` concurrent calls share one
  attempt; `:234` an exception, a swallowed reply or a 503 after SENT → UNKNOWN, nothing recorded; `:273` a refusal
  from `record_outcome` after a real POST → `outcome`/UNKNOWN.
- `tests/e2e/test_fenced_definers_live.py:85`, `:119`: stale fence before SENT is a handle refusal and sends nothing;
  after SENT UNKNOWN. `tests/e2e/test_definers_write_path_live.py:305` (grant/SENT/outcome once), `:455`
  (`mark_unknown` worker-only, revokes, enqueues recover), `:527` (late evidence on a terminal run), `:633` (stale
  `mark_sent` and early outcome refused).
- R105 (`tests/e2e/test_r105_walking_skeleton.py:127`): the worker process calls mcp-write over HTTP; a fresh handle
  for the finished execute job of the SUCCEEDED run is refused `INVALID_HANDLE` (`:234-235`); persona and `ops-mcp-read`
  tokens are refused at mcp-write's transport (`:237-238`; evidence "mcp-write:persona+mcp-read", `:243`).
- Not covered anywhere: `list_tools` on mcp-write over HTTP; a test-process client against mcp-write as an
  independent child process (R025/R031 write half); a read handle at mcp-write over HTTP; mcp_exec's ACL set equality;
  the EXECUTING re-queue's re-send through the tool over HTTP (Plan J debt); the pre-SENT `STALE_RUN` and
  `HASH_MISMATCH` envelopes (Plan E/H debt); mcp-write's verifier against a missing `aud`, `typ` ≠ Bearer, or
  `azp=ops-web` (no `tests/plan_j/test_verifier_t15.py` equivalent); incident-sim refusing the `ops-mcp-read` token.

### 3.13 Migration and dev-database state

- The dev database is at 0005 pending the owner's migrate to 0009 (`SESSION_STATE.md:11-14`); mcp-write refuses to
  start below 0009 (§3.2). Any new definer (`request_abort`, …) or a changed body (literal azp) means a new revision
  `0010` with frozen callers and an exact downgrade (the 0007/0009 pattern), and `HANDLE_BINDING`'s comment
  (`persistence.py:178-182`): "A later revision that re-creates `_resolve_handle` must keep this text or change it
  here in the same commit; a unit test checks the newest body carries it."

---

## 4. Prior rulings and proposed errata that touch mcp-write, recovery, abort, receipts and envelopes

Errata (proposed; `SESSION_STATE.md`; the owner decides, the spec stays authoritative until then):

- **2** (`:146`): "AM-13 \"Outcome vocabulary\": `FAILED_NO_COMMIT` carries `reason ∈ {aborted_no_commit,
  cancelled_before_send, rejected, expired}`; `expired` is produced by the recovery table (INTENT after the deadline)
  and by `create_incident` past the deadline."
- **14** (`:188`): "AM-20.3: `mark_unknown` is worker-only; mcp-write reports UNKNOWN to the worker, which dispatches an
  `execute` job for runs left in EXECUTING."
- **15** (`:189`): "`app.current_time()` is a definer function callable by every runtime role." (So `mcp_exec` holds
  it, outside R131's six.)
- **19** (`:193`): "`resolve_invocation` returns `job_type`, `job_id` and `conversation_id` instead of SA:459's
  `allowed_tools`".
- **21** (`:195`): "A CONFLICT on a terminal run is `action.conflict`, not late evidence."
- **22** (`:196`): "`mark_sent` and `record_outcome` carry state guards, and an outcome before SENT is refused".
- **48** (`:363-364`): "`mark_sent(raw_handle, action_id)`, `record_outcome(raw_handle, action_id, outcome, doc)`; a
  stale fence or a lapsed lease is the handle refusal OC008."
- **54** (`:377-378`): "`mark_unknown` refuses OC003 unless the caller's fence is current and its lease live, bumps the
  fence, revokes the old fence's handles and returns `(run_state, new_fence)`."
- **56** (`:380-382`): "the nine faults map to eight hooks (`reject_next`, `drop_before_commit`, `lose_after_commit`,
  `timeout_before_accept`, `rate_limit`, `malformed_response`, `receipt_hash_mismatch`, `delay_receipt`) and one
  harness race (concurrent same-key submission, R047)."
- **59** (`:391-394`): "AM-15 (SA:355) … After SENT a stale-fence refusal is answered `status=outcome` / `UNKNOWN`
  with the `action_id` (ruling 6; AM-13: after SENT the only answers are a recorded outcome or UNKNOWN). Before SENT
  it stays the plain refusal."
- **66** (`:478-482`): outbox intent for `action.confirmed`, `action.failed`, `action.conflict`, `run.escalated` and
  `run.abandoned_unverified` ("the first three are emitted today by `record_outcome`; the last two have no emitter
  until T22").
- **73** (`:568-573`): both MCP servers mount `ProtocolVersionGuard`; a POST without exactly `MCP-Protocol-Version:
  2026-07-28` is 400/-32022 before authentication.
- **74** (`:574-578`): mcp-read requires `typ` `Bearer`, refuses a token whose `aud` lacks its URL before stamping,
  keeps `validate_token_resource` on, "every token refusal stays HTTP 401 (Plan D ruling 25); mcp-write follows in
  T47."
- **75** (`:579-581`): `_resolve_handle` resolves only a handle whose `job_id` names an unfinished job of its own run.
- **76** (`:582-587`): "`persistence.allowed_tool(job_type, run_state, tool)` checks the job type's tools and run
  states at the start of every MCP call (`persistence.resolve_invocation`; the definers' own resolutions inside
  `grant_execution`, `mark_sent`, `record_outcome` and `lookup_action` do not apply it, since `record_outcome` must
  answer after the run moved); the attempt-state dimension (`create_incident` only while the attempt is absent or
  INTENT, not cancelled, before the deadline) is mcp-write's, in `execution.next_step` today and in its allowlist with
  T47."
- Errata 17, 18, 53 (one lock), 58 (60 s handles bound at use), 77 and 79 restate handle mechanics already in §3.
  Errata 1, 3–13, 16, 20, 23–47, 49–52, 55, 57, 60–65, 67–72, 78, 80 and 81 contain nothing on mcp-write, recovery,
  abort, receipts or the write envelopes beyond what is cited elsewhere in this sheet (72 and 81 are mcp-read's R131
  and token-test errata; 49 says the reclaim "inserts no recover job").

Plan rulings:

- **Plan D** (`docs/superpowers/plans/2026-10-08-first-slice-d-walking-skeleton.md`): review focus 1 (`:32`): "A
  second `create_incident` for the same proposal must not create a second incident or a second grant. … a repeat call
  with a grant already recorded resends the same `action_id` and hash (idempotent at the destination) or returns the
  recorded outcome." Review focus 3 (`:34`): a wrong-audience token "must be refused by every resource server … and
  the refusal must never carry an `action_id` (SA:357)". Ruling 21 (`:62`): failure after SENT → UNKNOWN (its
  "`mcp-write` records `OUTCOME_UNKNOWN`" half was replaced by Plan E ruling 6 / erratum 14). Ruling 25: a
  wrong-audience token is 401 at the MCP servers.
- **Plan E** (`…/2026-10-08-first-slice-e-roles-rls-definers.md`): ruling 1 (`:44`, no definer without a caller);
  review focus 4 (`:37`, one grant/action id/incident; tombstones whatever the hash); review focus 5 (`:38`,
  `mcp_exec` reads no table); ruling 6 (`:49`): "`mark_unknown` stays `worker`-only. After a transport failure past
  `SENT`, mcp-write records nothing and returns the `UNKNOWN` envelope … If the worker never receives it … the
  attempt stays `SENT` and the run `EXECUTING`; the execute job is re-queued and the replay resends (idempotent at the
  destination) — T22's reconciliation closes the rest."; ruling 11 (`:54`): the abort route's body and semantics;
  "mcp-write's abort client and the `abort_incident` tool are T22/T47's; the destination side is complete here.";
  ruling 12 (`:55`): `WrongAudience` → 403 at incident-sim only; ruling 20 (`:63`): the `OC` vocabulary, "Messages
  never carry a handle, a token or a secret"; ruling 21 (`:64`): handles hashed, server from `session_user` and the
  job type, allowlist in Python.
- **Plan F** ruling 14 (`…/2026-10-08-first-slice-f-sessions-login-sync.md:55`): `MEMBERSHIP_STALE` → tool error
  `GRANT_DEFERRED`, re-queued.
- **Plan H** ruling 6 (`…/2026-10-15-first-slice-h-leases-fences-heartbeat.md:174-176`): "a stale fence is OC008 →
  `HandleRejected`; before SENT it stays the `INVALID_HANDLE` envelope; after SENT `HandleRejected` is already one of
  `_POST_SENT_REFUSALS` … so the answer is `outcome`/`UNKNOWN`".
- **Plan J** (`…/2026-10-15-first-slice-j-mcp-read-verifier-handles.md`): ruling 2 (`:164-170`, "The verifier stays
  per service; mcp-write's change is a debt line (T47)"); ruling 6 (`:180-184`, run-state allowlist and 0009); ruling
  7 (`:185-186`): "no call site today needs the attempt-state parameter, so the shared function does not gain it";
  ruling 13 (`:204-205`): "one `INVALID_HANDLE` envelope for every handle refusal …, 401 for every token refusal";
  ruling 21 (`:218`): "the write-path definers' literal `'ops-worker'` → T47 (debt line)"; refinement (a)
  (`:233-244`): through the tool a replay is answered only while the run is APPROVED or EXECUTING; "Smallest
  alternative: keep the binding for read handles only … so a post-outcome replay at mcp-write still answers" (not
  taken).

---

## 5. Open questions the planner must rule on

1. **Which tools T47 builds versus T22.** T47's instructions say mcp-write "hosts create_incident,
   get_incident_receipt (recover only) and abort_incident" and the title says "and recovery tools"; SA:689: "recovery
   tools move to T47". T22 owns "recover jobs with redispatch/abort rules; reconciliation backoff; transport-timeout
   rule; CONFLICT and deadlines to ESCALATED" (`tasks.json:915`) and the kill tests (R094) that exercise abort. Plan E
   ruling 11 and `SESSION_STATE.md:206` say the abort client and `abort_incident` are "T47/T22". Open: whether T47
   registers `get_incident_receipt` and `abort_incident` with full bodies (GET and abort clients, outcome mapping,
   `record_outcome`), with bodies but no caller in the worker, or only the server-side shape; and how each is proved
   without T22's worker handler.
2. **`request_abort`: T47 or T22.** T47's instructions put `request_abort` in `mcp_exec`'s EXECUTE set and R131
   (T47-owned) expects it in the ACL; the Plan E debt line says "`request_abort`, `escalate_run`,
   `resolve_escalation` → T22" (`SESSION_STATE.md:678`); T22 review note 5 says it "is invoked inside create_incident
   after mark_sent returns cancelled/expired"; Plan E ruling 1 forbids a definer without a caller. Today
   `execution.py:96-100` answers `cancelled` with UNKNOWN under `TODO(T22)`. Open: whether T47 creates
   `request_abort` (and with which caller: `abort_incident`, `create_incident`'s cancelled branch, both), or R131's
   write half is met through an erratum like 72 ("the target, not today's").
3. **`request_abort`'s signature and reason.** SA:465 gives `request_abort(action_id, reason)`; erratum 48 moved
   `mark_sent`/`record_outcome` to take the raw handle first so the fence is checked; SA:465's reason set includes
   `deadline`, which is in incident-sim's `ABORT_REASONS` but not in `Reason` (`states.py:45-58`); the
   `abort_incident` input schema carries only `proposal_id` (§3.10). Open: whether the definer takes the raw handle,
   who chooses the reason (the server from run/attempt state and the clock, or the worker's recover trigger), and how
   `deadline` maps to a FAILED reason (`aborted_no_commit` after SENT per `outcome_from_destination`).
4. **The attempt-state allowlist: shape and place.** SA:338 derives tools from type + run state + attempt state;
   SA:344 (execute: "attempt absent or INTENT"), SA:345 (recover `create_incident` "INTENT only"), SA:334 (recover
   `create_incident` "refused when the latest attempt state is `ABORT_REQUESTED` or `RESOLVED`", i.e. SENT allowed),
   SA:240 ("no attempt, or … INTENT, not cancelled and before the deadline") and T22 note 6 ("refused once
   ABORT_REQUESTED exists") disagree on SENT. Erratum 76 / `jobs.py:56` put the dimension "in its allowlist with T47";
   `allowed_tool` takes no attempt state (Plan J ruling 7); SA:474 names an `_allowlist` SQL helper; erratum 19 keeps
   the allowlist in Python. `get_incident_receipt`/`abort_incident` have no attempt rule in SA:335-336 beyond
   "recover jobs only". Open: Python (`allowed_tool` gains `attempt_state`) or SQL; the per-(job type, tool) attempt
   rule; whether "not cancelled, before the deadline" belong in the allowlist (they need `cancel_requested` and
   `granted_at`, which `_resolve_handle` does not return) or stay in `mark_sent`.
5. **The execute re-send at SENT versus "attempt absent or INTENT".** Today the re-queued execute job of an EXECUTING
   run with a SENT attempt re-POSTs through `next_step` → `"resend"` without `mark_sent` (§3.3), Plan E ruling 6 and
   erratum 14 rely on that re-send, and T47 review note 3 asks for a live HTTP test of it ("returns the same
   action_id and no second incident"). SA:344's execute rule ("attempt absent or INTENT") would refuse that call, and
   SA:242 sends a SENT-without-response attempt to OUTCOME_UNKNOWN and `get_incident_receipt` instead. Open: whether
   the re-send stays (an erratum) or the attempt-state allowlist refuses SENT for execute jobs (and then what review
   note 3's test asserts, given that the worker's transport-failure path is T22's).
6. **Redispatch mechanics.** SA:240 and T22 note 1: redispatch loads bytes through `lookup_action` and "goes through
   `mark_sent`"; SA:463 emits `action.redispatched` "when `attempt_no > 1`". Today nothing creates `action_attempt`
   row 2 (`mark_sent` inserts at `v_latest.attempt_no`), `mark_sent` refuses unless the run is `EXECUTING` (an INTENT
   attempt on an OUTCOME_UNKNOWN run after `mark_unknown` cannot be redispatched), and the SENT re-send skips
   `mark_sent`. Open: whether T47 changes `mark_sent`'s run-state guard or attempt numbering, or leaves redispatch to
   T22.
7. **`record_outcome` after an abort request.** `record_outcome` refuses SUCCEEDED/CONFLICT unless the latest state is
   SENT (`0007:257-259`), returns the stored outcome once RESOLVED, and accepts FAILED_NO_COMMIT from any unresolved
   state. SA:242 expects an abort after SENT to be answerable by "the existing receipt (→ SUCCEEDED)"; with an
   `ABORT_REQUESTED` row written first (SA:465) that record is refused. SA:336 / T22 note 5 want an abort on
   ABANDONED_UNVERIFIED recorded as late evidence, but a run whose attempt is already RESOLVED (e.g. CONFLICT then
   ESCALATED then ABANDONED) cannot record new evidence. Open: whether T47 re-creates `record_outcome` (guard on
   "SENT or ABORT_REQUESTED after SENT"), and how late evidence after RESOLVED is recorded, if at all.
8. **What "receipt lookup cannot create actions" (DoD 2, R030) is evidenced by.** Facts: `lookup_action` returns
   `NotFound` before a grant and never inserts (§3.6); `get_incident_receipt` "resolves the stored action ID
   server-side" (BS:393); the catalog test already proves no MCP-callable function inserts a job
   (`test_migration_0008_live.py:242`); R030's evidence says "Normal/model tools cannot call lookup; reconciliation
   workload sees minimal existing-action outcome only". Open: which assertions count — an execute handle refused at
   `get_incident_receipt`; a recover handle on a run with no grant answered without a grant, attempt, event or POST
   (row counts before/after, destination untouched); `has_function_privilege` on `grant_execution` not reachable from
   the lookup path; and what "minimal" output means (the `ActionOutcome` shape of the schema, §3.10).
9. **Discovery filtering (BS:393 "Register it only for the reconciliation workload or filter it from normal tool
   discovery and calls").** `tools/list` needs a token but no handle; the SDK's `list_tools` returns every registered
   tool (`sp/mcp/server/mcpserver/server.py:516-532`); `MCPServer(…, middleware=…)` exists (`:185`, `:245-248`) and a
   comment says middleware can hide a tool from the caller (`:432-433`). The only token mcp-write accepts is the
   worker's. Open: whether `get_incident_receipt` is listed to every authenticated caller and refused per handle
   (DoD 2 "unavailable outside recover jobs"), or hidden from listing, and how R030's "normal/model tools cannot call
   lookup" is shown.
10. **Envelope rules for the new tools and for failures.** SA:354-355: `status=error` only before any grant for an
    authorized caller; auth failures never carry an `action_id`; erratum 59: after SENT a handle refusal is
    `outcome`/UNKNOWN with the `action_id`. A recover handle always concerns a run that has a grant (its run states
    are post-grant). `outcome_envelope` is hard-wired to `create_incident` (`server.py:155-161`); `abort_incident`'s
    data shape differs from `ActionOutcome` (§3.10). Open: what `get_incident_receipt` and `abort_incident` return for
    a refused handle (plain `INVALID_HANDLE`, never an action id — while the grant exists), for a destination 404
    (UNKNOWN per SA:269/BS:393), 429/503 (UNKNOWN), and for a recover handle on a run with no grant; whether a refused
    handle is an MCP tool error (`is_error`) or an application envelope (today the latter, Plan J ruling 13); and the
    tombstone `reason` text (the example's "cancelled before send" vs incident-sim's `cancelled_before_send`).
11. **Verifier parity on mcp-write (Plan J debt `:826-827`, erratum 74).** Today: no `typ` claim check, no aud
    containment in the adapter, `validate_token_resource=False`, inline construction (§3.4). Open: whether mcp-write
    gets a `write_verifier` constructor shared with its unit tests, the same three changes, the same unit cases as
    `tests/plan_j/test_verifier_t15.py` (missing aud, read server's audience only, `azp` `ops-mcp-write`/`ops-web`,
    `typ` ID/Refresh), and whether `McpVerifier` stays duplicated (`server.py:40-41`) or moves to core.
12. **Naming the worker client once (T47 review note 3, Plan J debt `:853-856`).** Four places: `worker/…/main.py:138`,
    `mcp-read/…/server.py:272`, `mcp-write/…/server.py:284`, and the definers' `'ops-worker'` (`0005:96`, `0004:343`,
    `0007:195`, `0007:242`). Open: the setting's name and default; whether the definers instead receive the token's
    azp from mcp-write (a signature change: `grant_execution(raw_handle, proposal_id)` etc. gain `client_azp`, as
    `resolve_invocation` has), or keep a literal that a settings value cannot reach (SQL cannot read process
    settings); which revision (0010) re-creates `grant_execution`, `lookup_action`, `mark_sent`, `record_outcome`.
13. **R131 write half: the ACL set.** `mcp_exec` today: `{current_time, resolve_invocation, grant_execution,
    mark_sent, record_outcome, lookup_action}` (§3.7); R131 lists six without `current_time` and with
    `request_abort`; erratum 72 handled the same mismatch for `mcp_read`. Open: the live equality asserted (with
    `current_time` as erratum 15's extra), whether `request_abort` is in it (Q2), "cannot execute any read function"
    shown how (`asset_scope`/`search_procedures_scoped` do not exist; `has_function_privilege` false for every other
    definer; an attempted read-path call → 42501 — none exists to call), and whether `mark_unknown`/`revoke_handles`
    (worker-only) count.
14. **R131 write half: a read handle at mcp-write over HTTP.** Refused at the definer today (§3.7), never over HTTP.
    Open: the HTTP cases (investigate handle, resume_input handle — there is no resume_input job creator in the
    worker, so the test stages one; a lying `server` column on a read handle at mcp-write; a positive control at
    `mcp_read`), mirroring `test_mcp_read_t15_live.py:206-264`.
15. **R131 / DoD 3: incident-sim refuses mcp-read's token.** No test presents an `ops-mcp-read` token to incident-sim
    (§3.8); its verifier would answer 403 (`aud` lacks `incident-sim` → `WrongAudience`). DoD 3's second half ("mcp-read
    cannot reach incident-sim") is "network test in T30" (`tasks.json:1136`), and T30 depends on T22. Open: whether
    T47 records only the token half (live 403) and leaves the network half to T30 with a matrix note.
16. **R025 / R031 write half: the independent client.** The read half runs `python -m ops_mcp_read` as a child
    process and an official SDK `Client` in the test (`tests/e2e/test_mcp_read_process_live.py`); mcp-write's child
    needs `kc_client_secret_ops_mcp_write` and incident-sim. Open: the same shape for mcp-write (child process, list
    exactly the registered tools, call one with a valid handle), whether the call is `create_incident` (it grants and
    POSTs) or a recovery tool, and the evidence file (`reports/mcp-write/`).
17. **Deadlines: where enforced and configured.** Dispatch deadline 5 min and escalation deadline 30 min after grant
    (SA:295-296, "configurable; tests use `app.current_time()`"); `mark_sent` should return `expired` (SA:229-231,
    SA:463) but carries `TODO(T22)`; escalation is `escalate_run` (worker, sweeper; absent) and the sweeper's
    per-tenant "deadline escalation" (SA:520, T14 note `:661`); no setting or column exists (`granted_at` only). SQL
    functions cannot read process settings. Open: whether T47 adds the dispatch deadline to `mark_sent` (needed for
    "before the deadline" in the allowlist and for `expired` → `request_abort`), where the 5/30-minute values live (a
    table, a function constant, a revision parameter), and whether escalation stays wholly T22's.
18. **Backoff inside the tool.** SA:242 / BS:502: "`get_incident_receipt` with backoff 1, 2, 4, 8 s + jitter, then
    scheduled `recover` jobs" "inside one recovery attempt". Open: whether the backoff loop runs inside mcp-write's
    tool call (holding the worker's call, lease effect and 60 s handle), in the worker's recover handler (T22), or as
    the T22 graph's `reconcile_outcome`; and the tool's own HTTP timeout (POST uses 10 s, `destination.py:60`).
19. **Faults the recovery tools must survive.** Plan H debt `:760-761`: the five new faults reach mcp-write only
    through `classify` → T22/T47; `delay_receipt` hides a row on GET (404 → UNKNOWN); the abort route has no hooks;
    `outbox_sink_fail` can be armed at incident-sim and is never consumed (Plan I debt `:818-819`, → T47). Open: which
    faults T47's tests drive against `get_incident_receipt`/`abort_incident`, whether the abort route gains hooks,
    and whether incident-sim's fault route is narrowed to the destination's eight kinds.
20. **The pre-SENT `STALE_RUN` / `HASH_MISMATCH` envelopes** (Plan E/H debt → T47). `VersionConflict` maps to
    `STALE_RUN` and `HashMismatch` to `HASH_MISMATCH` (`server.py:194-199`); neither has a test. `grant_execution`
    raises no `OC003` or `OC007` (its `_transition` call passes no expected version, `0003:208-211`; an `OC004`
    `IllegalTransition` from it is unmapped in `server.py`); `mark_sent` raises `OC003` when the run ≠ EXECUTING. Open: which calls
    can actually produce each envelope through the tool today, and whether an unreachable mapping is tested, removed or
    kept.
21. **The EXECUTING re-send test (T47 review note 3).** It needs a run in EXECUTING with a SENT (or INTENT) attempt
    and an open execute job, a fresh handle, the real tool over HTTP and a real incident-sim, asserting the same
    `action_id` and one incident. Open: how the state is staged (a `drop_before_commit`/`lose_after_commit` fault on
    the first call, then a re-queued job; or direct definer calls), whether the worker process or the test is the
    client, and how it interacts with Q5.
22. **The outcome-truth trust statement (T47 review note 2).** "v1 states plainly in the threat model that mcp-write is
    trusted for outcome truth, with T10's detective check as the control." No threat-model file exists (§1.1);
    `scripts/skeleton.py keys` is the detective check (Plan E ruling 14), unscheduled (→ T32). Open: where the
    statement goes (a new `docs/` file, ARCHITECTURE.md, the mcp-write README or runbook) and whether the HMAC v1.1
    option is recorded as debt.
23. **Recover handles in the worker.** The worker finishes every `recover` job unhandled (`handlers.py:305`); without a
    handler no production path mints a recover handle; the T15 live test stages one with the superuser
    (`test_mcp_read_t15_live.py:217-229`). T22 owns recover handling (Plan E/H/I debt). Open: whether T47's live tests
    stage recover jobs and handles directly (as T15 did), or T47 adds a minimal worker recover path; and whether
    `mark_unknown`'s recover job (`:timeout`) is the only staged trigger.
24. **The `cancelled` branch of `create_incident`.** `mark_sent` returns `cancelled` and mcp-write answers UNKNOWN,
    making the worker call `mark_unknown` and queue a recover job "although nothing was sent: conservative"
    (`execution.py:96-100`); SA:348 says `create_incident` itself calls `request_abort`, POSTs the abort and returns
    FAILED_NO_COMMIT (`cancelled_before_send` or `expired`). R118 (T22) proves it. Open: whether T47 replaces the
    branch (with Q2/Q3) or it stays `TODO(T22)`.
25. **Revision 0010 and startup guards.** Any of Q2, Q3, Q6, Q7, Q12, Q17 changes definer bodies or adds one. Open:
    whether T47 ships `0010_…` (frozen bodies and callers, exact downgrade by re-running applied bodies), what marker
    mcp-write's startup then asserts (a relation or `assert_function_text` on a changed body, the `HANDLE_BINDING`
    pattern), whether mcp-read must refuse below it too, and the owner's migrate instruction (dev still at 0005).
26. **`lookup_action` and the allowlist.** `lookup_action` resolves the handle with its own `_resolve_handle` call and
    no tool or run-state check (erratum 76: "the definers' own resolutions … do not apply it"); a recover handle used
    by `get_incident_receipt` would be checked once in Python (`persistence.resolve_invocation`) and again in SQL
    without the allowlist. Open: whether the recovery tools call `resolve_invocation` first like `create_incident`
    does (`server.py:183-186`), and whether the returned `Invocation` (today discarded) drives the attempt rule.
27. **Acceptance bookkeeping and layout.** R030 (T47 only) and R131 (T15, T47) are `NOT_IMPLEMENTED_OR_NOT_TARGET_
    VERIFIED`; R025/R031's notes hand their mcp-write halves to T47 although T47 does not own them; Plan J kept unit
    tests in `tests/plan_j/` and live tests in `tests/e2e/` (per-service `tests/` → T30). Open: which rows T47 marks
    and with what status (R131 complete only if Q2/Q13 resolve), the `tests/plan_k` testpath, the evidence directory,
    and whether R025's owners gain T47.

---

## 6. Glossary of exact names

- mcp-write: `server.py` — `tool_error :61`, `refusal_error :66`, `envelope :73`, `McpVerifier :103`, `strict_tool
  :128`, `outcome_envelope :155`, `State :165`, `build_server :172` (tool `create_incident :176`), `build_app :214`,
  `production_app :279`; `execution.py` — `_POST_SENT_REFUSALS :37`, `next_step :40`, `Deps :52`, `_read_back :68`,
  `create_incident :84`; `destination.py` — `Reply :30`, `post_incident :37`, `unknown :70`, `classify :93`.
- `ops_core.persistence`: `Invocation :383`, `allowed_tool :395`, `resolve_invocation :414`, `Grant :434`,
  `grant_execution :463`, `lookup_action :471`, `mark_sent :479`, `record_outcome :488`, `mark_unknown :319`,
  `HANDLE_BINDING :183`, `assert_function_text :186`, `translate :84`. `ops_core.jobs`: `Tool :19`, `JobRule :51`
  (TODO(T47) `:56`), `JOB_RULES :70` (`EXECUTE :87`, `RECOVER :95`), `RECOVER_CADENCE :109`. `ops_core.outcomes`:
  `outcome_from_destination :43`, `ActionOutcome :97`. `ops_core.states`: `Reason :45`, `AttemptState :60`.
  `ops_core.tokens`: `TokenVerifier :77`, `WorkloadTokenSource :215`. `ops_core.privileges.DEFINER_FUNCTIONS :185`.
- Definers: `resolve_invocation(text, text)` `0004:239`; `_resolve_handle(text, text, text)` `0009` (from `0007:123`);
  `grant_execution(text, uuid)` `0005:82`; `lookup_action(text)` `0004:335`; `mark_sent(text, uuid)` `0007:184`;
  `record_outcome(text, uuid, text, jsonb)` `0007:228`; `mark_unknown(uuid, bigint)` `0007:317`. Not created:
  `request_abort`, `escalate_run`, `resolve_escalation`.
- incident-sim: `POST /internal/incidents` (`app.py:180`), `POST /internal/actions/{action_id}/abort` (`:232`), `GET
  /internal/actions/{action_id}` (`:264`), `POST /internal/faults/{kind}` (`:251`); `keys.document` (`keys.py:112`).
- Worker: `handlers.execute :212`, `_mark_unknown :269`, `handle :296`; `mcp.HttpMcpCaller :51`.
- Keycloak client `ops-mcp-write` (mapper "aud incident-sim"), `ops-worker` (mappers "aud mcp-read resource", "aud
  mcp-write resource"); secret file `kc_client_secret_ops_mcp_write`. Settings `MCP_WRITE_RESOURCE_URL`,
  `OPS_MCP_WRITE_URL`, `OPS_MCP_WRITE_PORT` (8082), `OPS_INCIDENT_SIM_URL`.
- Schemas: `schemas/tools/{create_incident,get_incident_receipt,abort_incident}.input.schema.json`,
  `schemas/tool-result.schema.json`, `schemas/examples/tool-{create_incident,get_incident_receipt,abort_incident}-*.json`.

# Plan G inputs: T12 (durable admission API and error mapping) — fact sheet

Prepared 2026-10-09 on branch `plan-f` at `bcae618` (clean tree; read-only on the repository). Facts only, no design.
Citations: `SA:<line>` = `SPEC_AMENDMENTS.md`, `BS:<line>` = `BUILD_SPEC.md` (line numbers as of `bcae618`); the
amendments win wherever the two conflict. Repository files are cited as `path:line`. Nothing was run against a
database, Keycloak or a service for this sheet: every fact below is read from the files, and no secret, token or
cookie value was opened.

Note on line numbers in the brief: the AM-16 admission router is SA:362–375 (heading SA:360, table SA:366–373); the
`create_run` row is SA:450; the `idempotency_request` grant row is SA:429 and its RLS note SA:523; the `error.schema`
row is SA:764. The schemas are under top-level `schemas/`, not `handoff/schemas/` (`handoff/` holds only
`ACCEPTANCE.md`, `BUILD_BACKLOG.md`, `KICKOFF_PROMPT.md`, `acceptance-matrix.json`, `prompts/`, `tasks.json`).

---

## 1. T12 verbatim, its acceptance-matrix rows, and related rows/tasks

### 1.1 T12 (`handoff/tasks.json:575-602`)

- **id/milestone/title:** `T12`, `M03` ("Identity, sessions and durable admission", `:46-53`), "Durable admission API
  and error mapping". `status: "PLANNED"`, `external_approval_required: false`.
- **instructions:** "/api/v1 conversations/messages/runs; message+run+job+event committed before 202; scoped
  Idempotency-Key (24 h); one active run per conversation; interval resolved once; safe error schema and
  401/403/404/409/422/429/503 mapping; the AM-16 admission router with its six routes (investigate,
  clarification_reply, status_question, readonly_answer, clarify, reject) as a table in core/routing.py,
  deterministic-first; a model hint can only produce clarify; investigate/readonly_answer go through create_run with
  intent; status questions and conversation-level clarifications are stored by the API as messages
  (kind=status_question/status_answer/clarification_question)."
- **depends_on:** `["T09"]` (`DONE`). T12 does not depend on T11; T11 is `DONE` on this branch anyway.
- **requirement_ids:** `R015, R016, R017, R018, R115, R129`.
- **definition_of_done:**
  1. "Crash-before-commit leaves no ack; after commit the job exists."
  2. "Replay same body returns same result; different body 409."
  3. "Each status code has a test proving the mapping."
  4. "Every admission route has a test; conflicting text/fields yields a stored clarification (R018) and never a job;
     unroutable kinds yield 422 (R129)."
- **review_notes:**
  1. "Slot rule: partial unique index on runs(conversation_id) over AM-10 active states, plus a concurrent admission
     test."
  2. "Status answers and conversation-level clarifications are messages
     (kind=status_question/status_answer/clarification_question), not events; the clarify route is evaluated after
     the active-run check (1.3.6)."
- There is no "Plan …" review note on T12 yet (T11's last review note, `:572`, is the Plan F close-out record).

### 1.2 Acceptance-matrix rows (`handoff/acceptance-matrix.json`)

All six are `NOT_RUN` / `NOT_IMPLEMENTED_OR_NOT_TARGET_VERIFIED`, `blocking_for_v1: true`.

- **R015 (:256)** — milestone / category: M03 / durability; requirement: "Accepted work is committed before
  acknowledgement"; expected_evidence: "In one transaction the API inserts the message and calls create_run(tenant_id,
  ...) which inserts run, directory, history, job and run.accepted; the 202 follows the commit; a crash before commit
  leaves nothing; no other path creates a run."; owners: T12; suggested_test:
  `tests/acceptance/test_r015_accepted_work_is_committed_before_acknowledgemen.py`
- **R016 (:271)** — milestone / category: M03 / idempotency; requirement: "HTTP replay resolves once and conflicting
  body fails"; expected_evidence: "Repeat same scoped key/body then changed body; one logical run then 409."; owners:
  T12; suggested_test: `tests/acceptance/test_r016_http_replay_resolves_once_and_conflicting_body_f.py`
- **R017 (:286)** — milestone / category: M03 / workflow; requirement: "Only one active mutating run per conversation";
  expected_evidence: "Concurrent requests cannot start two mutating investigations; status question makes no incident
  job."; owners: T12; suggested_test: `tests/acceptance/test_r017_only_one_active_mutating_run_per_conversation.py`
- **R018 (:301)** — milestone / category: M03 / domain; requirement: "Relative intervals resolve once and ambiguity
  clarifies"; expected_evidence: "Retry after clock advance and conflict text/form asset; interval remains fixed and
  ambiguity pauses."; owners: T12; suggested_test:
  `tests/acceptance/test_r018_relative_intervals_resolve_once_and_ambiguity_cl.py`
- **R115 (:1846)** — milestone / category: M03 / api, `source: SPEC_AMENDMENTS.md`; requirement: "Errors use the safe
  schema and documented status mapping"; expected_evidence: "Tests for 401/403/404/409/422/429/503 cases; no stack
  traces or unauthorized IDs."; owners: T12; suggested_test:
  `tests/acceptance/test_r115_errors_use_the_safe_schema_and_documented_status.py`
- **R129 (:2085)** — milestone / category: M03 / routing, `source: SPEC_AMENDMENTS.md`; requirement: "Every route is
  enumerable and unroutable input never starts work"; expected_evidence: "Admission router: each of the six routes
  tested; conflicting text/fields yields a stored clarification and no job; unroutable kinds 422. Graph router: a test
  walks every row of the route table and asserts the node reached; a model hint can only produce clarify."; owners: T12,
  T20; suggested_test: `tests/acceptance/test_r129_every_route_is_enumerable_and_unroutable_input_n.py`

`handoff/ACCEPTANCE.md:21-24` carries older evidence text for R015 ("Kill around admission commit; every acknowledged
run has message/run/job; no volatile acceptance.") and the same text as the matrix for R016–R018; it has no R115 or
R129 line. `tests/acceptance/` does not exist; `pyproject.toml:48-51` `testpaths` lists `tests/plan_a` … `tests/plan_f`
and `tests/e2e` (Plan D ruling 26: `tests/plan_<letter>/` for unit tests, `tests/e2e/` for live tests).

### 1.3 Other rows and tasks that name admission, idempotency, the slot or error codes

- **T14 depends_on** — Text (verbatim): `["T13", "T12"]` (`tasks.json:638-648`); Relation to T12: T14 (journal,
  wake-ups, outbox) waits for T12
- **T21 review note 2** — Text (verbatim): "Revision from BLOCKED_REVIEW requires a free conversation slot
  (SLOT_OCCUPIED 409)." (`:899`); Relation to T12: same slot index, T21's route
- **T20 instructions** — Text (verbatim): "Nodes per AM-12 incl. the route_request graph router whose conditional edges
  are generated from the core/routing.py table; … ANSWERED path." (`:837`); Relation to T12: T20 adds the graph table to
  the same module; R129 co-owned
- **R114 (T20)** — Text (verbatim): "Read-only answers complete as ANSWERED without proposals" — "Answer path cites
  evidence, creates no proposal or grant, ends ANSWERED." (`:1830-1838`); Relation to T12: T12 creates the `answer_only`
  run; T20 ends it
- **R042 (T20)** — Text (verbatim): "Actual checkpoint pause/resume survives restart" — "Restart graph process during
  clarification/review and resume from committed event under same run."; Relation to T12: the `resume_input` consumer is
  T20's
- **R052 (T26)** — Text (verbatim): "operate actual browser request/clarify/evidence/review/submit/result path";
  Relation to T12: browser half of admission
- **R053 (T27)** — Text (verbatim): "SSE reconnect replays safely without duplicate work"; Relation to T12: the 202's
  stream location points at T27's route
- **T45 (`DONE`)** — Text (verbatim): AM-80 rows incl. "message/revision schemas with structured supersedes_run_id and
  kind enum incl. ask/status, route schema" (`:415`); Relation to T12: schemas T12's bodies must conform to (§3.9)
- **T11 review note 3** — Text (verbatim): "exempt the endpoint from CSRF/Idempotency-Key with a forged-token negative
  test" (`:570`); Relation to T12: the one written exemption
- **T11 Plan F note** — Text (verbatim): "Deferred: Idempotency-Key -> T12" (`:572`); Relation to T12: —
- **Plan F ruling 20** — Text (verbatim): "**Idempotency-Key (Q22): none in T11**, declared debt → T12. Logout is
  naturally idempotent (a second POST has no session → 401)."
  (`docs/superpowers/plans/2026-10-08-first-slice-f-sessions-login-sync.md:61`); Relation to T12: logout's status under
  T12 is open (§5)
- **SA:542** — Text (verbatim): "(b) **Every** decision, revision, cancel and manual-proposal mutation checks the
  user's enabled status through the Keycloak admin API."; Relation to T12: admission is not in that list, so no
  Keycloak enabled check is required on it
- **SA:690** — Text (verbatim): "T12 implements the admission router (R129); T20 the graph router node (R129); T19 the
  model router and run-manifest recording (R130). T25 reads the manifest."; Relation to T12: —

---

## 2. Spec requirements

### 2.1 AM-16 admission router (SA:362–375), verbatim

- SA:362: "Routing is explicit, enumerable and deterministic-first. Model output may hint at a route; it never selects
  one. An input the router cannot classify becomes a clarification or a 422 and never starts work (R129)."
- SA:364: "**Admission router** (`api`, replaces the implicit §7 rules):"
- SA:366–373, the table (one bullet per row: route — trigger; effect):

- `investigate` — Trigger: `kind=investigate` with a resolvable asset and interval, no active run in the conversation;
  optional structured `supersedes_run_id`; Effect: `create_run(intent='investigate', …)`: message + run + directory +
  history + `investigate` job + `run.accepted` in one transaction, 202
- `clarification_reply` — Trigger: reply bound to an outstanding clarification ID and expected version; Effect: message
  + `resume_input` job, 202
- `status_question` — Trigger: `kind=status`; Effect: answered from recorded events and state; the API inserts the
  question and the answer as `messages` (`kind=status_question`, `kind=status_answer`); **no run, no job, no run event**
  [R8-R3]
- `readonly_answer` — Trigger: `kind=ask` (a question about evidence, no incident intent); Effect:
  `create_run(intent='answer_only', …)`; the graph can end ANSWERED; `freeze_proposal` refuses runs with this intent
- `clarify` — Trigger: structured fields and text disagree (asset or interval), or a required field is missing;
  evaluated **after** the active-run check, so a busy conversation gets `reject`/409 first (R017); Effect: the API
  inserts a `messages` row with `kind=clarification_question`, 200; no run. The requester's reply re-enters admission as
  a new message (R018: ambiguity clarifies, never guesses) [R7-S1, R8-R5]
- `reject` — Trigger: unroutable `kind`, over limits, or a second active run; Effect: 422 / 409 with a safe error;
  nothing written except the idempotency record

- SA:375: "Optional model-assisted intent classification runs **after** the deterministic rules and can only turn a
  route into `clarify`; it can never produce `reject`, `investigate` or `readonly_answer` on its own."
- SA:377 (graph router, T20's): "a route table in `core/routing.py` maps `(run state, runs.intent, context resolved?,
  evidence sufficient?, validated draft kind, decision present?, attempt state)` to exactly one of `clarify`,
  `retrieve`, `draft`, `answer_only`, `abstain`, `freeze`, `await_decision`, `execute`, `recover`, `publish`.
  Conditional edges are generated from that table; a test enumerates every row and asserts the node reached (R129)."
- SA:686: "`create_run` and `record_status_answer` functions (the latter removed again in 1.3.6: status answers are
  messages)". No function writes messages; the API's own `messages` grant (SA:414) is the path.
- Status codes the table fixes: `investigate` 202, `clarification_reply` 202, `clarify` 200, `reject` 422/409. The
  `status_question` and `readonly_answer` rows name **no** status code.

### 2.2 The admission transaction, `create_run`, the slot (SA, BS)

- SA:450, `create_run` row, verbatim: "| `create_run(tenant_id, conversation_id, request, intent,
  supersedes_run_id)` | `api` | `tenant_id` from the authenticated session (the API is the identity trust anchor, as
  for `record_decision`); the validated admission request | `runs` (conversation slot index) | Sets `app.tenant_id`
  from the argument after checking the conversation belongs to that tenant; inserts `runs` (QUEUED, `intent`,
  `supersedes_run_id` validated against the tenant/asset), `run_directory`, the first `run_state_history` row and the
  `investigate` job (dedup `run_id:1`) in one transaction; the API inserts the message in the same transaction [R7-H3,
  R8-R1] | `run.accepted` |"
- SA:134: "| ∅ (creation) | → QUEUED only via `create_run` (AM-20.3), which inserts the run, its directory row, the
  first `run_state_history` row, the first job and `run.accepted` in one transaction [R7-H3] |"
- SA:145: "**Active states** (the ones that hold the conversation slot): QUEUED, AWAITING_INPUT, RETRIEVING,
  DRAFTING, AWAITING_APPROVAL, APPROVED, EXECUTING, OUTCOME_UNKNOWN." SA:139: BLOCKED_REVIEW "Frees the conversation
  slot." SA:120: ESCALATED "frees the conversation slot".
- SA:451 (`transition_run`): "maintains `slot_held` and the conversation slot (partial unique index on
  `runs(conversation_id) WHERE slot_held`)".
- SA:153: "**The ANSWERED path** … is selected by `runs.intent = 'answer_only'`, set by the admission router;
  `freeze_proposal` refuses such runs, so a read-only run can never produce a proposal [R7-S2]."
- SA:154: "**Requester-asserted fields on `runs`** [R7-H1]: `intent ∈ {investigate, answer_only}` and optional
  `supersedes_run_id` are written only by `create_run`/`create_revision` from the authenticated request's structured
  fields. Model output is never a source for either".
- SA:188: "**Lock order:** `asset guard advisory lock → run_lease → runs → messages → proposals → decisions →
  memberships → execution_grant → action_attempt → operator_resolutions → events → outbox`. Idempotency rows are
  written last, before commit."
- SA:342–343 job types: "| `investigate` | API at admission and after a revision | Retrieval, drafting, freezing |
  read tools | QUEUED, RETRIEVING, DRAFTING |"; "| `resume_input` | API with a clarification reply | Resume after a
  clarification | read tools | AWAITING_INPUT → QUEUED |".
- SA:494, SA:500–501: "`jobs(id, type, run_id, dedup_key UNIQUE, available_at, claimed_by, claimed_at, attempts,
  done_at)`"; "| `investigate` | `api` (admission), `create_revision` | `run_id:revision` |"; "| `resume_input` |
  `api` | `run_id:clarification_event_id` |".
- BS:271: "| `POST /api/v1/conversations/{id}/messages` | Persist ordinary message; if investigation intent, atomically
  create run/job and return 202; status questions do not duplicate runs |".
- BS:334: "Admission transaction: message + run + job + initial event. … commit before network/model work."
- BS:336: "Serialize state-changing operations per run/conversation. One active investigation per conversation in v1;
  unrelated status questions do not start work. A new request while a proposal is pending must explicitly
  cancel/revise or open another conversation. Limit global active compute separately from queue length."
- BS:548: "| Active runs | One state-mutating run per conversation; one active compute lease per requester |".
- BS:681: "| Database outage | Reject uncommitted admission; no volatile accepted job; recover lease/outbox safely |".
- BS:96: "2. API and workflow orchestration: authenticated durable admission, jobs, LangGraph, state."
- BS:704: "| M03 — Identity and API | Keycloak/OIDC sessions, CSRF, current memberships, versioned durable admission |
  Login/session negatives, no lost accepted job, request replay conflicts |".

### 2.3 Interval resolved once, clarification, clock

- BS:297: "Structured form fields take precedence only when they agree with the confirmed user request. If text and
  explicit asset/time conflict, ask for clarification rather than guessing. Resolve “last 24 hours” once against an
  injected server clock into `[start_at, end_at)`; store the interval so retrying does not move the investigation
  window. A later change is a revision."
- BS:287–295 sample: `{"kind": "investigate", "text": "Investigate the alerts on Asset A17 over the last 24 hours.",
  "context": {"asset_id": "A17", "hours": 24}}`.
- BS:547: "| Investigation interval | 1–168 hours, resolved once to absolute UTC |".
- BS:389: "The target uses absolute timestamps for alerts so retries keep the same interval. The historical `hours`
  argument is a reference-only input; convert at the admission boundary, not repeatedly inside retrieval."
- BS:42: "A successful task has the correct asset and fixed time interval …".
- BS:112 (flowchart): "C -->|No| Q[Persist clarification and pause]".
- BS:273: "| `POST /api/v1/runs/{id}/clarifications` | Bind reply to outstanding question ID and expected version;
  commit before resume enqueue |" (a separate route in BS §7; AM-16's `clarification_reply` is a route of the admission
  router, which BS:271's messages endpoint feeds).
- BS:510: "The user can submit an investigation, answer a stored question, ask read-only status/evidence questions,
  revise before dispatch, reject, approve when authorized, cancel remaining work, and provide feedback. … All user
  commands reenter authenticated API validation."
- Clock rule SA:157–159: "Every lease, expiry, freshness and deadline comparison uses `clock_timestamp()`, evaluated
  **after** the relevant row locks are acquired. Never use `now()`, which is the transaction start time." "Tests inject
  time through the database function `app.current_time()`. It wraps `clock_timestamp()` plus an offset read from the
  table `app.test_clock`." "**Only the Alembic branch `testclock` creates `app.test_clock`** (AM-20.6). In dev and
  demo it does not exist, and the function returns `clock_timestamp()` unchanged."
- AM-10 clarification signal (SA:147): "a draft asks for clarification with `kind=abstain` **plus** a non-empty
  `question` (AM-80)." AM-10 row: "| AWAITING_INPUT | → QUEUED by the worker's `resume_input` job through
  `transition_run`, after the clarification event is committed |".

### 2.4 Idempotency-Key, 24 h, the scoped key

- BS:264: "Every mutation requires an authenticated current session, CSRF/origin protection in cookie mode, a bounded
  body, and `Idempotency-Key`. State-specific mutations include `expected_version` or expected proposal
  revision/hash. The server sets actor, tenant, roles, timestamps and authority fields; reject client attempts to
  supply them. UUIDs and unguessable keys are not access control."
- BS:299: "Accepted response contains `conversation_id`, `message_id`, `run_id`, `status`, `state_version`, and
  authorized relative status/stream locations. Return success only after the transaction commits. Same key/body
  returns the same logical result; same key/different body returns 409. Retain request dedup records for at least the
  documented replay window; incident deduplication is independent and longer lived."
- BS:244: "| idempotency_request | tenant, subject, route, key, body hash, accepted result identifiers; unique scoped
  key |".
- SA:297: "| Request-dedup replay window | 24 hours |" (AM-13 defaults: "configurable; tests use
  `app.current_time()`").
- SA:429, the grant row: "| `idempotency_request` | sel, ins | — | del (expired) | — | — |" (columns `api` /
  `worker` / `sweeper` / `app_definer` / `mcp_read`·`mcp_exec`·`operator`). No UPDATE for anyone; `app_definer` holds
  nothing on it, so no definer function can read or write it.
- SA:523: "`run_directory`, `invocation_context`, `run_lease`, `sessions`, `idempotency_request`,
  `operator_resolutions`, `model_permit`, `tenants` and `app.test_clock` have **no RLS**; their grants (AM-20.2) are
  the control."
- SA:408: "Only these grants exist. Anything not listed is denied."
- SA:454: `record_decision(proposal_id, expected_payload_sha256, decision, reason, idempotency_key)`; BS:235 decision
  record carries an "idempotency key"; BS:466 "Same idempotent replay returns its recorded result".
- Proposed erratum 25 (`SESSION_STATE.md:188`): "The sweeper's `del` without `sel` on `sessions` and
  `idempotency_request` cannot run a `DELETE ... WHERE expires_at < ...` (spike section 3); flagged for T11/T12."
  T11 resolved it for its three tables only (0005 gives the sweeper SELECT; §3.6).
- `docs/ARCHITECTURE.md:60` (`api` row): "INSERT on messages, idempotency, feedback, outbox, `resume_input` jobs; …
  status answers and conversation clarifications are plain messages"; `:62` (sweeper): "expired sessions and
  idempotency rows".

### 2.5 Error mapping and the safe error

- BS:301, verbatim: "Safe errors use `{code, message, retryable, request_id}`; no stack traces, raw queries, tokens,
  or unauthorized IDs. Use 401 for missing/expired identity, 404 for inaccessible resource existence, 403 for a known
  permitted resource with a disallowed operation, 409 for stale versions/key conflicts, 422 for shape/content limits,
  429 for bounded capacity, and 503 for unavailable durable admission. A write transport timeout is represented in
  the run as unknown, not translated into a claim of no effect."
- SA:764: "| `error.schema.json` | Codes `ASSET_ACTION_UNRESOLVED`, `ASSET_INCIDENT_EXISTS`, `GRANT_EXISTS` (409 on
  revision after grant), `SLOT_OCCUPIED`, `AUTHORITY_VIOLATION` |".
- SA:355 (tool results, AM-15): "authentication and authorization failures always return a plain safe error, never
  with an `action_id`." SA:289: "A refusal returns 409 `ASSET_ACTION_UNRESOLVED` or `ASSET_INCIDENT_EXISTS`, listing
  the blocking run only if the caller may see it."
- SA:545: Keycloak down or slow → "503 `retryable`" (decision-class only). SA:549: "a disabled user's next
  decision-class mutation gets 401".
- BS:564: "Database unavailable: do not acknowledge uncommitted work or fall back to local SQLite in the target.
  Overload: bound queue and return clear 429/503 behavior." BS:687: "| Overload | Bounded queues/concurrency, clear
  rejection, no retry storm or unbounded model loop |". BS:562: "Do not retry validation, authorization, stale version
  or content conflicts as transient errors."
- BS:587 (§19 test layer 2): "API/session tests: issuer/session/CSRF/origin, deduplication, expected versions,
  projections, no unauthorized existence leaks."
- The spec names no 400, 405, 413 or 500 status; the code uses 400 for the back-channel endpoint (erratum 34).

### 2.6 Limits (BS §17, BS:542–550), verbatim rows

- BS:542: "All numeric limits below are **starting project defaults**, not measured performance promises. Put them in
  validated configuration and write boundary tests."
- BS:546: "| Request text / inbound body | 4,000 characters / 64 KiB; reject unexpected large data |"
- BS:547: "| Investigation interval | 1–168 hours, resolved once to absolute UTC |"
- BS:548: "| Active runs | One state-mutating run per conversation; one active compute lease per requester |"
- BS:549: "| Global model concurrency | 1 initially; increase only after measured capacity |"
- BS:550: "| Queued work | 100 total initially; bounded tenant quotas; reject clearly when full |"
- BS:372: "Use request/body limits, strict output parsing, … disabled cross-origin access unless explicitly configured";
  BS:374 threat tests include "oversized content".
- The spec names no request-rate limit (requests per second/minute); the only 429 sources it names are "bounded
  capacity" (BS:301), the queued-work bound (BS:550) and overload (BS:564, BS:687).

### 2.7 The HTTP API (BS §7, BS:262–285)

- BS:262: "Target API prefix: `/api/v1`. The historical reference endpoints are not these target contracts; migrate or
  version them explicitly."
- BS:270: "| `POST /api/v1/conversations` | Create authorized conversation, return 201 |"
- BS:271: messages row (§2.2). BS:272: "| `GET /api/v1/runs/{id}` | Authorized run snapshot, version, active
  proposal, safe status and timestamps |". BS:277: "| `GET /api/v1/runs/{id}/events` | Bounded authorized cursor
  history |". BS:278: `GET /api/v1/runs/{id}/stream` (T27). BS:283: health.
- BS:285: "`schemas/` defines target message, clarification, decision, cancellation, draft, event, tool-result,
  proposal and receipt shapes. Generate OpenAPI from implemented Pydantic contracts and check it against reviewed
  snapshots; do not maintain conflicting hand-edited OpenAPI and generated models."
- BS:224: "Use UUID identifiers generated in application code for externally visible entities".
- BS:230: "| conversation / message | tenant_id, owner, immutable message sequence, kind, content, timestamps; unique
  `(conversation_id, sequence)` |".

### 2.8 Message kinds

- Request kinds (SA:769, AM-80 message row): "`kind ∈ {investigate, ask, status, clarification}`".
- Stored kinds named by AM-16 and T12: `status_question`, `status_answer`, `clarification_question` (SA:370, SA:372;
  T12 instructions and review note 2). `clarification_reply` is a **route** name, not a message kind.
- Neither spec file lists the full vocabulary of `messages.kind` values (request kinds plus stored kinds), and neither
  says which `kind` the stored row of an ordinary `investigate`/`ask`/`clarification` request carries.

### 2.9 Grants and RLS that bind the API's admission writes (SA:408–438, SA:510–523)

- `conversations`, `messages` (SA:414) — `api`: sel, ins; `worker`: sel; `sweeper`: —; `app_definer`: sel
- `runs` (SA:415) — `api`: sel, upd(`cancel_requested`, `cancel_requested_at`) (insert only via `create_run`); `worker`:
  sel, upd(`checkpoint_id`, `budget_used`); `sweeper`: sel; `app_definer`: ins, sel, upd(…`slot_held`…)
- `jobs` (SA:419) — `api`: ins (`resume_input` only); `worker`: sel, ins, upd(…); `sweeper`: sel, ins, upd(same);
  `app_definer`: ins, sel
- `events` (SA:426) — `api`: sel; `worker`: sel; `sweeper`: sel; `app_definer`: ins, sel
- `feedback` (SA:428) — `api`: ins, sel; `worker`: —; `sweeper`: —; `app_definer`: —
- `idempotency_request` (SA:429) — `api`: sel, ins; `worker`: —; `sweeper`: del (expired); `app_definer`: —

- SA:510: `conversations`, `messages`, `runs`, `jobs`, `events` are tenant tables with ENABLE + FORCE RLS and the
  `tenant_isolation` policy; SA:522: "`api`, `worker` and `sweeper` set `app.tenant_id` themselves per transaction".
- SA:446: every definer function "first resolves `tenant_id` through `run_directory` (or the handle) and sets
  `app.tenant_id` with `set_config(name, value, true)`".

---

## 3. The tree as it is (branch `plan-f`, `bcae618`)

### 3.1 `api/src/ops_api/app.py` (604 lines)

- Module docstring (`:1-9`): "… Idempotency-Key stays declared debt (T12)." `:11-12`: no `from __future__ import
  annotations` (FastAPI resolves dependency annotations at import time).
- `bearer = HTTPBearer(auto_error=False)` (`:42`).
- `ApiError(status, code, message, *, clear_session, clear_login)` (`:45-54`); `safe(status, code, message)` (`:57-61`)
  builds `SafeError(code, message, retryable=status == 503, request_id=uuid4())` and adds `WWW-Authenticate: Bearer`
  on 401. The body is exactly `{code, message, retryable, request_id}`. `request_id` is a fresh random UUID per error
  response; it is not logged and not correlated with anything.
- `Identity(subject, username, membership, session)` (`:86-107`): `tenant_id`/`roles` from the membership; `auth` is
  `"bearer"` or `"session"`; `require(role)` raises 403 `FORBIDDEN` "the {role} role is required".
- Dependencies inside `create_app` (`:110`):
  - `identity` (`:143-183`): bearer first (cookie ignored when a bearer is present, ruling 7): `TokenRejected` → 401
    "token rejected"; non-UUID `sub` → 401; `store.membership(issuer, subject)` `None` → **401** "no active
    membership" (Plan F ruling 21). Cookie path: no cookie → 401 "a session or bearer token is required";
    `store.live_session` miss → expire/end provider session → 401 `clear_session`; membership `None` or another tenant
    than the session row → revoke + 401. Membership is resolved **per request** on both paths.
  - `browser_mutation` (`:185-195`): bearer path exempt; cookie path needs `same_origin(headers, sessions.origin)`
    (403 "cross-origin request refused") and `X-CSRF-Token` matching the session's `csrf_secret_sha256` (403 "missing
    or invalid CSRF token").
  - `enabled_identity` (`:197-210`): `browser_mutation` plus `deps.admin.enabled(subject)`; `AdminUnavailable` → 503
    `UNAVAILABLE` "identity provider unavailable"; disabled → revoke session + 401. Used only by the decision route.
- Exception handlers (`:212-244`): `ApiError` → its status (clearing cookies when flagged); `AuthorityViolation` → 503
  "service misconfigured"; `st.Internal`, `PersistenceError`, `IllegalTransition`, `EventRuleViolation` → 503
  "service error"; `psycopg.Error` → 503 "database unavailable"; `RequestValidationError` → 422 `INVALID_INPUT`
  "request is not valid". There is **no** handler for Starlette's `HTTPException` (an unknown path or wrong method
  answers FastAPI's default `{"detail": …}` 404/405) and **no** catch-all `Exception` handler (an unexpected exception
  is uvicorn's plain-text 500).
- `body(request, model)` (`:246-250`): `load(model, (await request.body()).decode("utf-8"))`; `UnicodeDecodeError`,
  `DuplicateKey`, `ValidationError`, `ValueError` → 422 "request body is not valid". The whole body is read; there is
  no size check before or after the read.
- Routes (all on the one app; no middleware is installed — no CORS, no body limit, no trusted host):

- `GET /health/live` (`:252`) — Dependency: none; Status: 200; Request: —; Response: `{"status": "live"}`
- `GET /health/ready` (`:256`) — Dependency: none; Status: 200/503; Request: —; Response: `{"status": "ready"}` or
  SafeError 503
- `GET /` (`:266`) — Dependency: none; Status: 200; Request: —; Response: `{"status": "ok", "login_url": "/auth/login"}`
- `GET /auth/login` (`:276`) — Dependency: none; Status: 303; Request: —; Response: redirect
- `GET /auth/callback` (`:299`) — Dependency: none; Status: 303; Request: query; Response: redirect + cookies
- `POST /auth/logout` (`:362`) — Dependency: `browser_mutation`; Status: 204; Request: —; Response: — (bearer → 403)
- `POST /auth/backchannel-logout` (`:380`) — Dependency: none; Status: 200/400/503; Request: form `logout_token`;
  Response: —
- `GET /api/v1/me` (`:415`) — Dependency: `identity`; Status: 200; Request: —; Response: `{subject, tenant_id, roles,
  username, auth}`
- `POST /api/v1/conversations` (`:425`) — Dependency: `browser_mutation`; Status: 201; Request: no body read; Response:
  `{"conversation_id"}`
- `POST /api/v1/conversations/{conversation_id}/messages` (`:432`) — Dependency: `browser_mutation` +
  `require("requester")`; Status: 202; Request: `MessageRequest`; Response: see below
- `GET /api/v1/runs/{run_id}` (`:471`) — Dependency: `identity`; Status: 200/404; Request: —; Response: `{run_id,
  conversation_id, status, state_version, active_proposal_id, asset_id, start_at, end_at, created_at}`
- `GET /api/v1/proposals/{proposal_id}` (`:488`) — Dependency: `identity`; Status: 200/404; Request: —; Response:
  `{proposal_id, run_id, revision, payload, payload_sha256, authored_by, expires_at}`
- `POST /api/v1/proposals/{proposal_id}/decisions` (`:505`) — Dependency: `enabled_identity`; Status: 200; Request:
  `DecisionRequest`; Response: `{proposal_id, run_id, decision, status, state_version}`
- `GET /api/v1/runs/{run_id}/events` (`:538`) — Dependency: `identity`; Status: 200/404; Request: `after` ≥ 0, `limit`
  1–500 (default 100); Response: `{"events": [...]}`

- `post_message` (`:432-469`), in order: `who.require("requester")` (403) → `body(request, MessageRequest)` (422) →
  route check: anything but `kind is INVESTIGATE` with `context.asset_id` and `context.hours` both set → 422
  `INVALID_INPUT` "only an investigate request with asset_id and hours is routed" (`:438-446`; comment: "T08 routes
  only `investigate` … the admission router (T12) adds the rest.") → `st.resolve_interval(message.context.hours,
  datetime.now(UTC))` (`:447`, the **Python wall clock**, not `app.current_time()`) → `store.admit(...)` →
  `st.NotFound` → 404 "no such conversation or superseded run"; `st.Conflict` → 409 `ErrorCode(exc.code)` "the
  conversation already has an active run". The 202 body (`:461-469`): `conversation_id`, `message_id`, `run_id`,
  `status`, `state_version`, `status_url` = `/api/v1/runs/{run_id}`, `events_url` = `/api/v1/runs/{run_id}/events`.
  No stream URL (no stream route exists). The route decorator fixes `status_code=202`.
- `create_conversation` (`:425-430`) reads no body and calls `store.create_conversation(who.tenant_id, who.subject)`.
- `production_app()` (`:555-604`): bearer `TokenVerifier(audience=OPS_API_AUDIENCE default "ops-api",
  allowed_azp={"ops-dev-direct"})`; store `st.DbStore(await persistence.connect(settings.app_postgres(Role.API)))`;
  auth deps (authlib OIDC, ID/logout token verifiers, `keycloak_admin.admin_users`, `TokenBox`, `CookiePolicy`).
- The lifespan (`:117-138`) asserts the clock profile and `persistence.assert_relation(conn, "app.login_state")`
  (`:124`, "revision 0005"): the API refuses to start on a database without the newest relation it needs.
- `api/src/ops_api/__main__.py:14-27`: uvicorn on `127.0.0.1:OPS_API_PORT` (8000), `log_level="warning"`,
  `redaction.install()` first, selector loop on win32. `api/pyproject.toml` dependencies: `ops-core`, `fastapi`,
  `uvicorn`, `authlib`, `cryptography`, `python-multipart`; no rate-limit or body-limit library.

### 3.2 `api/src/ops_api/auth.py` (474 lines) — what T12 touches

- Constants (`:33-36`): `SESSION_COOKIE = "ops_session"`, `CSRF_COOKIE = "ops_csrf"`, `LOGIN_COOKIE = "ops_login"`,
  `CSRF_HEADER = "X-CSRF-Token"`. `digest()` (`:41`), `new_token()` (`:46`), `matches()` constant-time (`:52-54`),
  `same_origin()` (`:80-88`: `Origin` must equal the configured origin exactly; else the `Referer`'s origin; else
  refuse). No `Idempotency-Key` constant or helper exists anywhere in `api/` or `core/`.

### 3.3 `api/src/ops_api/store.py` (477 lines)

- Module docstring (`:1-8`) ends "`TODO(T12): Idempotency-Key, admission router.`" (`:7`). The only other T12 markers
  in code: `app.py:8`, `app.py:438` (comment), `core/src/ops_core/persistence.py:467`,
  `core/src/ops_core/routing.py:4,18`,
  `core/src/ops_core/privileges.py:8`, `migrations/app/versions/0001_walking_skeleton.py:27`, `api/README.md:21`.
- Exceptions (`:23-41`): `Forbidden` (403), `NotFound` (404), `Conflict(code)` (409; `code` is the `ErrorCode`
  value), `Internal` (503).
- `Accepted(conversation_id, message_id, run_id, status, state_version)` (`:52-60`).
- `resolve_interval(hours, now)` (`:97-100`): `end = now.replace(microsecond=0)`; returns `(end - hours, end)`.
- `map_refusal(exc)` (`:120-128`): `NOT_REVIEWER`/`SELF_REVIEW`/`MEMBERSHIP_INACTIVE` → `Forbidden`; `SLOT_OCCUPIED`
  → `Conflict("SLOT_OCCUPIED")`; `INVALID_ARGUMENT` → `Internal`; anything else → `Conflict("VERSION_CONFLICT")`.
  (Its docstring cites "BUILD_SPEC §16"; the mapping is BS §7, BS:301.)
- `Store` protocol (`:131-212`): T08's seven operations (`membership`, `create_conversation`, `admit`, `run`,
  `proposal`, `decide`, `events`) plus T11's seven session operations. The unit tests fake it (§3.11).
- `DbStore` (`:215-219`): `self.session = persistence.Session(conn)` over **one** autocommit connection (Plan D
  ruling 24). Every unit takes the process-wide `asyncio.Lock`, so two HTTP requests to one API process never run
  database work concurrently; a "concurrent admission" through one API process is serialised before PostgreSQL sees
  it.
- `DbStore.membership` (`:221-225`): tenant-less unit → `persistence.resolve_identity` → `single_tenant` (two
  tenants → `None`, `:111-117`).
- `DbStore.create_conversation` (`:227-235`): `uuid4()` in Python, plain `INSERT INTO app.conversations
  (conversation_id, tenant_id, created_by)` under the tenant unit (no definer function).
- `DbStore.admit` (`:237-289`), one tenant unit: `SELECT 1 FROM app.conversations WHERE conversation_id = %s AND
  tenant_id = %s` (absent → `NotFound`) → `INSERT INTO app.messages (message_id, tenant_id, conversation_id, kind,
  text, context, author)` with `kind = request.kind.value` (the request kind, `investigate`), `context` as JSONB,
  `author = requester` → `persistence.create_run(..., intent=Intent.INVESTIGATE, ...)`; `persistence.NotFound` →
  `NotFound`; `persistence.Refused` → `map_refusal`. It raises `ValueError` if called without `asset_id` (`:248-249`).
  No idempotency read or write; no active-run read before the insert (the slot is the function's unique index).
- `DbStore.decide` (`:310-338`) passes no `idempotency_key` to `record_decision` (the parameter defaults to `None`).

### 3.4 `core/src/ops_core/persistence.py` (562 lines)

- `OC_CODES` (`:70-79`): `OC001` `AuthorityViolation`, `OC002` `NotFound`, `OC003` `VersionConflict`, `OC004`
  `IllegalTransition`, `OC005` `Refused` (DETAIL is the code), `OC006` `EventRuleViolation`, `OC007` `HashMismatch`,
  `OC008` `HandleRejected`. `translate()` (`:82-92`) maps a psycopg error by SQLSTATE; anything else re-raises (and
  the API's `psycopg.Error` handler makes it 503). A plain `unique_violation` (23505) is **not** translated.
- `connect()` (`:119-122`): one autocommit connection, `row_factory=dict_row`. `set_tenant()` (`:125-133`) refuses
  outside a transaction. `Session` (`:136-157`): `unit(tenant_id=None)` = lock + `conn.transaction()` + optional
  `set_tenant`; `TODO(T13): a pool`.
- `assert_relation(conn, name)` (`:168-173`): refuses to start when `to_regclass(name)` is NULL.
- `create_run(conn, *, tenant_id, conversation_id, message_id, requester, intent, asset_id, start_at, end_at,
  supersedes_run_id=None) -> (run_id, state_version)` (`:198-226`): builds `p_request = {"message_id", "requester",
  "asset_id", "start_at", "end_at"}` (ISO strings) and calls `SELECT * FROM app.create_run(%s, %s, %s, %s, %s)` with
  `(tenant_id, conversation_id, Jsonb(request), intent.value, supersedes_run_id)`.
- `append_event` wrapper (`:265-279`) for non-reserved types (callers `api`, `worker`, `sweeper`).
- `record_decision(..., idempotency_key=None)` (`:326-345`).
- `insert_job(conn, *, job_type, run_id, **ids)` (`:459-474`): reads `run_directory`, then `INSERT … ON CONFLICT
  (dedup_key) DO NOTHING RETURNING id`; comment `:466-467`: "ON CONFLICT (target) and RETURNING need SELECT (spike
  §3): this helper serves the tests and the superuser; the API's `resume_input` insert (T12) goes through a definer
  function or a target-less ON CONFLICT DO NOTHING."
- `insert_maintenance_job(conn, job_type, minute_bucket)` (`:515-533`): tenant-less sweeper job, key
  `<type>:<minute bucket>`, `available_at = app.current_time()`; `None` if the minute exists.
  `claim_maintenance_job(conn, *, job_type, worker_name, job_id=None)` (`:536-549`): `FOR UPDATE SKIP LOCKED`.

### 3.5 `create_run` in SQL

Source: `migrations/app/versions/0003_run_path_functions.py:237-320`; not redefined in 0004 or 0005.

- Signature: `app.create_run(p_tenant_id uuid, p_conversation_id uuid, p_request jsonb, p_intent text,
  p_supersedes_run_id uuid) RETURNS TABLE (run_id uuid, state_version integer)`; SECURITY DEFINER header; callers
  `("api",)` (`:425`; `privileges.DEFINER_FUNCTIONS["create_run"]`, `core/src/ops_core/privileges.py:168`).
- Order inside: `_authority('create_run', ['api'])` → `set_config('app.tenant_id', p_tenant_id, true)` → `p_intent NOT
  IN ('investigate','answer_only')` → OC005 `INVALID_ARGUMENT` → parse `message_id`, `requester`, `asset_id`,
  `start_at`, `end_at` from `p_request` (bad casts → OC005 `INVALID_ARGUMENT`) → **any of them NULL, `asset_id = ''`
  or `start >= end` → OC005 `INVALID_ARGUMENT`** (so an `answer_only` run also needs an asset and an interval) →
  conversation in tenant else OC002 `conversation` → message in that conversation and tenant else OC002 `message` →
  `supersedes_run_id` must be a run in the same tenant **and the same conversation** (not "tenant/asset" as SA:450
  says) else OC002 `supersedes_run_id` → creation row in `app.transitions` else OC004 → `INSERT INTO runs (…, state
  'QUEUED', state_version 1, slot_held true, next_event_seq 0)` with `run_id := gen_random_uuid()` (generated in the
  database, not in application code as BS:224 asks); a `unique_violation` on constraint
  `runs_one_active_per_conversation` → OC005 `SLOT_OCCUPIED`, any other unique violation re-raised → `run_directory`
  → `run_state_history` (seq 1, `at = app.current_time()`) → `jobs` (`investigate`, dedup `'<run_id>:1'`,
  `available_at = app.current_time()`) → `_append_event(…, 'run.accepted', 'application', '{}')` (empty payload).
- It takes no explicit lock; the slot is enforced by the partial unique index at INSERT time. `slot_held` is `true`
  for **both** intents, so an `answer_only` run holds the conversation slot exactly like an investigation.
- Live proof that the slot refusal is OC005 and that wrong callers are refused:
  `tests/e2e/test_definers_run_path_live.py:99-147`.

### 3.6 Tables (revisions 0001, 0002, 0005)

- `app.conversations` (`0001_walking_skeleton.py:52-58`): `conversation_id uuid PK`, `tenant_id uuid NOT NULL`,
  `created_by uuid NOT NULL`, `created_at timestamptz DEFAULT now()`, `UNIQUE (tenant_id, conversation_id)`. No title,
  no message counter.
- `app.messages` (`:60-70`): `message_id uuid PK`, `tenant_id`, `conversation_id`, `kind text NOT NULL` (**no CHECK**:
  any string is accepted), `text text NOT NULL`, `context jsonb`, `author uuid NOT NULL`, `created_at timestamptz
  DEFAULT now()`; FK `(tenant_id, conversation_id)`. No `sequence` column and no `UNIQUE (conversation_id, sequence)`
  (BS:230); no `run_id`; ordering is only `created_at`, which is the transaction-start `now()`, so two messages
  inserted in one transaction carry the same `created_at`. 0002 adds `UNIQUE (tenant_id, message_id)` and the
  composite FK from `runs` (`0002_roles_grants_rls.py:215-219`).
- `app.runs` (`0001:72-93`, `0002:199-208`): `message_id NOT NULL`, `requester`, `intent CHECK IN ('investigate',
  'answer_only')`, `supersedes_run_id`, `asset_id text NOT NULL`, `start_at`/`end_at timestamptz NOT NULL`, `CHECK
  (start_at < end_at)`, `state`, `state_version`, `reason`, `active_proposal_id`, `cancel_requested`, `created_at`,
  `updated_at` (both `DEFAULT now()`), plus 0002's `slot_held boolean`, `next_event_seq`, `cancel_requested_at`,
  `checkpoint_id`, `budget_used`. No `workflow_version` (BS:231).
- **Slot index:** 0001 created `runs_one_active_per_conversation ON app.runs (conversation_id) WHERE state IN
  (<the eight AM-10 active states>)` (`0001:27-30`, `:94`); 0002 dropped it and recreated it as `… WHERE slot_held`
  (`0002:212-213`; Plan E ruling 2). `_transition` sets `slot_held = (p_dst = ANY (v_active))` on every transition
  (`0003:222`). So T12 review note 1's index already exists, expressed through `slot_held`.
- `app.jobs` (`0001:107-119`, `0002:230-236`): `dedup_key text NOT NULL UNIQUE`; `run_id`/`tenant_id` nullable
  together (`jobs_tenant_iff_run_check`).
- `app.events` (`0001:197-208`): `run_id uuid NOT NULL` — an event cannot exist without a run, so a conversation-level
  clarification or status answer cannot be an event.
- `app.idempotency_request`: **no revision creates it** (grep over `migrations/`, `core/src`, `api/src`,
  `sweeper/src`: the only `idempotency` hits are `decisions.idempotency_key` (`0002:255`), `record_decision`'s
  parameter (`0004:173,213-215`), `ErrorCode.IDEMPOTENCY_CONFLICT` and comments). Its intended row is SA:429 (§2.4);
  its intended columns are BS:244 ("tenant, subject, route, key, body hash, accepted result identifiers; unique
  scoped key").
- Revision 0005 (`0005_sessions_login_logout.py`, the head) is the precedent for a T-owned table outside the printed
  matrix: `login_state` and `logout_jti` with frozen `GRANTS_0005` (`:30-42`), both owned by `migrator`, no RLS, and
  the sweeper given SELECT beside DELETE (erratum 25/27). The owner migrated the dev database to 0005 on 2026-10-09
  (`SESSION_STATE.md:5`); a T12 revision 0006 is a new owner input for the dev database.

### 3.7 `core/src/ops_core/privileges.py` (278 lines)

- Docstring (`:7-9`): "the owners of later tables (outbox → T14, feedback and idempotency_request → T12,
  operator_resolutions → T22, documents/chunks/embeddings → T17, model_permit → T13) add their rows." The docstring
  lists six departures from the printed table (`:9-16`).
- `GRANTS` (`:66-126`): `messages`/`conversations` `api` `Grant(sel, ins)` (`:82-83`); `runs` `api` sel +
  `upd(cancel_requested, cancel_requested_at)` (`:85`); `jobs` `api` `_INS` = INSERT only, **no SELECT** (`:111`);
  `events` `api` sel (`:123`). No `idempotency_request` or `feedback` row.
- `RLS_TABLES` (`:129-143`); `NO_RLS` (`:145-155`) has `sessions`, `login_state`, `logout_jti` and not yet
  `idempotency_request`. `DEFINER_FUNCTIONS` (`:164-180`): `api` may EXECUTE `current_time`, `resolve_identity`,
  `create_run`, `append_event`, `record_decision`. Each revision freezes its own copy of the cells;
  `tests/plan_e/test_transitions_table.py` checks the newest revision's cells equal the live matrix (`0002:53-54`).
- Consequences of `jobs` = INSERT only for `api`: an `INSERT … ON CONFLICT (dedup_key)` with a target, or with
  `RETURNING`, needs SELECT (spike §3) and is refused; a target-less `ON CONFLICT DO NOTHING` (rowcount as the verdict,
  as `record_logout` does for `logout_jti`, `store.py:451-464`) needs INSERT only. The column grant cannot restrict
  the `type` value to `resume_input` (SA:419's "(`resume_input` only)" is not enforceable by GRANT).
- A row lock needs UPDATE on the table (Plan E ruling 23, erratum 17): the `api` role can take `FOR UPDATE` on `runs`
  (it holds a column UPDATE) but **not** on `conversations` or `messages` (sel, ins only).

### 3.8 `core/src/ops_core/contracts.py` (446 lines), `routing.py` (70), `states.py` (298)

- `load(model, text)` (`contracts.py:104-119`): duplicate-key pre-scan, then `model.model_validate_json(text)`
  strict. `_Strict = ConfigDict(frozen=True, extra="forbid", strict=True)` (`:75`); `Text` = 1–4000 chars, stripped,
  NFC (`:77`); `Short` = 1–500 (`:78`); `AssetId` = `^[A-Z][A-Z0-9_-]{0,31}$` (`:81`).
- `AUTHORITY_FIELDS` (`:40-53`): `tenant_id, actor, actor_id, role, roles, approved, approved_by, destination,
  reviewer, requester`.
- `MessageKind` (`:142-148`): `INVESTIGATE`, `ASK`, `STATUS`, `CLARIFICATION`. `MessageContext` (`:151-156`):
  `asset_id: AssetId | None`, `hours: int | None` (1–168, strict). `MessageRequest` (`:159-166`): `kind`, `text`,
  `context: MessageContext | None`, `supersedes_run_id: UUID | None`. It has **no** `question_id` or
  `expected_version`, so a `kind=clarification` message cannot name the clarification it answers.
- `RunRequestFields(intent, supersedes_run_id)` (`:169-179`): unused by the API today.
- `ClarificationReply(question_id, expected_version ≥ 1, context)` (`:182-194`; context must carry `asset_id` or
  `hours`): the BS:273 `POST /runs/{id}/clarifications` body; no route uses it.
- `DecisionRequest`, `RevisionRequest`, `CancelRequest`, `CancelResponse`, `FeedbackRequest`,
  `ManualProposalRequest` (`:197-297`) exist for T21's routes.
- `ErrorCode` (`:421-436`): `UNAUTHENTICATED, FORBIDDEN, NOT_FOUND, VERSION_CONFLICT, IDEMPOTENCY_CONFLICT,
  INVALID_INPUT, RATE_LIMITED, UNAVAILABLE, ASSET_ACTION_UNRESOLVED, ASSET_INCIDENT_EXISTS, GRANT_EXISTS,
  SLOT_OCCUPIED, AUTHORITY_VIOLATION`. `SafeError(code, message: Short, retryable, request_id: UUID)` (`:439-446`).
  Codes no code path emits today: `IDEMPOTENCY_CONFLICT`, `RATE_LIMITED`, `GRANT_EXISTS`, `ASSET_*`,
  `AUTHORITY_VIOLATION` (the API maps `AuthorityViolation` to 503 `UNAVAILABLE`, `app.py:223-226`).
- `routing.py`: `AdmissionRoute` (`:17-25`: `INVESTIGATE, CLARIFICATION_REPLY, STATUS_QUESTION, READONLY_ANSWER,
  CLARIFY, REJECT`), `GraphRoute` (`:28-40`), `ModelRoute` (`:43-47`: `fake`, `qwen3:8b`), `RunManifest` (`:50-70`).
  Docstring `:3-5`: "The tables that map inputs to these routes arrive with their owners (T12 admission, T20 graph, T19
  model)". No route table exists yet. `tests/plan_c/test_jobs_routes_outcomes.py:210` pins the enum values.
- No Python enum or constant names the stored message kinds `status_question`, `status_answer`,
  `clarification_question` (grep over `core`, `api`, `worker`, `scripts`, `tests`: only `AdmissionRoute`'s
  `status_question` route value).
- `states.py`: `Intent` (`:69-73`: `investigate`, `answer_only`); `ACTIVE_STATES` (`:211-222`, the AM-10 eight);
  `SlotOccupied(IllegalTransition)` (`:102-103`); `revision_allowed` (`:271-283`).
- `canonical.py` provides `canonical_sha256` (imported by `contracts.py:37`), the existing canonical-JSON v1 hash.

### 3.9 Schemas and examples an admission request/response must conform to (`schemas/`, generated)

- `schemas/README.md`: every schema, example and `examples/index.json` is generated by `scripts/build_schemas.py` from
  the `ops_core` vocabularies; `tests/plan_c/test_schemas_generated.py` fails on drift.
  `tests/plan_c/test_schema_conformance.py:26-34` maps `schemas/message.schema.json` → `MessageRequest`,
  `schemas/clarification.schema.json` → `ClarificationReply`, `schemas/error.schema.json` → `SafeError`, and checks
  every example and every mutation of a valid one gets the same verdict from schema and model (T45's gate). A change
  to `MessageRequest`, `ClarificationReply`, `SafeError` or `ErrorCode` therefore means a `build_schemas.py` change
  and regenerated files.
- `message.schema.json`: closed; `kind` enum `investigate, ask, status, clarification`; `text` 1–4000; `context`
  closed `{asset_id (pattern, ≤32), hours (1–168)}`; `supersedes_run_id` uuid; required `kind`, `text`.
- `clarification.schema.json`: closed; `question_id` uuid, `expected_version` ≥ 1, `context` (minProperties 1);
  all three required.
- `error.schema.json`: closed; `code` enum (the thirteen above), `message` 1–500, `retryable` boolean, `request_id`
  uuid; all required.
- `route.schema.json`: `admission` enum = the six routes, `graph`, `model`; `minProperties 1`.
- Examples: `message-valid.json` (the BS sample), `message-clarification-needed.json` (valid: `kind investigate`,
  text "Investigate A17.", `context {asset_id: A17}` — no hours), `message-invalid-authority.json` (`tenant_id`),
  `message-invalid-bool-hours.json`, `message-invalid-kind-question.json` ("The 1.0 kind question is gone."),
  `message-invalid-asset-id-newline.json`; `clarification-valid.json`; `error-valid.json` (`VERSION_CONFLICT`),
  `error-invalid-unknown-code.json`; `route-valid.json`.
- **No schema exists for any response**: not the 202 accepted body, not the clarify 200 body, not a status answer,
  not a conversation. Nothing under `schemas/` names `Idempotency-Key`.

### 3.10 The walking skeleton drives admission like this

- `tests/e2e/test_r105_walking_skeleton.py:102-131`: persona tokens from the direct grant (`kc.token_password(base,
  "ops-dev-direct", "alex"|"sam", secret(...))`), `Authorization: Bearer`; `POST /api/v1/conversations` (no body, no
  `Idempotency-Key`), then `POST /api/v1/conversations/{cid}/messages` with `{"kind": "investigate", "text":
  "Investigate the alerts on Asset A17 over the last 24 hours.", "context": {"asset_id": "A17", "hours": 24}}`,
  expecting 202; then polls `GET /api/v1/runs/{id}` until `AWAITING_APPROVAL`, decides as sam (403 for alex, 409
  `VERSION_CONFLICT` for a stale hash, 200 `APPROVED`, 409 for a second decision) and waits for `SUCCEEDED`. The event
  list must equal nine `(type, source)` pairs starting `("run.accepted", "application")` (`:30-40`). The module is
  marked `sweeper_stamps` (`:41`) and runs the six processes through `scripts.skeleton.Skeleton` (`:44-61`).
- `tests/e2e/kc_browser.py`: the cookie path; `Browser.login(username, password)` drives the Keycloak form and returns
  a `Session(api, csrf)` whose `mutation_headers()` are `{"Origin": "http://localhost:8000", "X-CSRF-Token": csrf}`
  (`:36-38`); the API client dials `127.0.0.1:8000` with `Host: localhost:8000` (`:44-48`). `TestAdmin` (`:98-118`) is
  the dev/test-only `ops-test-admin` account (enable/disable a persona). `tests/e2e/test_auth_live.py:106-118` posts
  `POST /api/v1/conversations` with and without the CSRF/Origin headers.
- incident-sim (the destination, not an admission caller): `POST /internal/incidents` body `IncidentRequest(action_id,
  payload_sha256, payload_canonical)` (`incident-sim/src/ops_incident_sim/app.py:75-79`, `:178`), `POST
  /internal/actions/{id}/abort` (`AbortRequest(payload_sha256, reason)`, `:82-87`, `:218`), `GET
  /internal/actions/{id}`, and under `PROFILE=test` only `POST /internal/faults/{kind}` with `{"count": n}` (`:237`).
  The fault factory `core/src/ops_core/testing/faults.py` has `reject_next`, `drop_before_commit`,
  `lose_after_commit` (`:14-19`) and only incident-sim uses it: the API has no fault hook, so nothing can stop an
  admission between the message insert and the commit from outside today.

### 3.11 Test conventions

- Unit tests: `tests/plan_<letter>/`, one package per plan (`tests/plan_f/` holds `auth_fakes.py`, `test_api_auth.py`,
  `test_admin_users.py`, `test_auth_helpers.py`, `test_grant_deferred.py`, `test_id_and_logout_tokens.py`,
  `test_privileges_f.py`, `test_redaction.py`, `test_settings_auth.py`, `test_sweeper.py`, `test_tokens_knobs.py`).
  The API is unit-tested with `fastapi.testclient.TestClient` over `create_app(StubVerifier(), store_factory=lambda:
  FakeStore(), auth_factory=...)` (`tests/plan_f/test_api_auth.py:28-33`); `tests/plan_d/test_api.py` owns
  `StubVerifier` (`:49`), `FakeStore` (`:73`, with a `slot_occupied` flag), `auth(name)` (`:228`) and the current
  admission test `test_admission_validates_the_body_and_returns_202` (`:270-304`: 202 body keys, 24 h interval with
  whole seconds, 422 for an authority field, for `kind: "ask"` ("not routed in T08 (admission router is T12)"), for no
  asset/interval and for `a17`; 422 `INVALID_INPUT` for a duplicate key; 403 for sam; 404 for an unknown
  conversation; 409 `SLOT_OCCUPIED`).
- Live tests: `tests/e2e/`, gated by `OPS_LIVE=1` (`conftest.py:32-35`); `env` exports `.env` and sets `PROFILE=test`
  and the per-session databases `ops_test` / `incident_test` (`:29`, `:38-48`); `migrated` drops, recreates and
  migrates both under the test profile, so `app.test_clock` exists there (`:68-73`); `app_conn` is the superuser
  (`:76-84`); `role_conn(Role.X)` opens autocommit connections as a runtime role (`:87-101`); the autouse
  `fresh_memberships` stamps `memberships.synced_at = app.current_time()` before every live test unless the module is
  marked `sweeper_stamps` (`:114-126`; marker declared in `pyproject.toml:56-58`); `purge_run` / `purge_tenant`
  clean up (`:129-172`; `PURGE_ORDER` has no `idempotency_request` step). Persona tokens come from
  `tests.plan_b.live.kc.token_password` (stdlib `urllib`).
- Clock-advance tests: only `test_harness` may write `app.test_clock` (`migrations/app/versions/tc_0001_test_clock.py`:
  one row, `clock_offset interval`); `tests/e2e/test_clock_live.py:26-52` sets `UPDATE app.test_clock SET
  clock_offset = interval '3 days'` as `role_conn(Role.TEST_HARNESS)` and resets it to `0`. An offset moves only
  `app.current_time()`; the API's interval (`app.py:447`) and the sweeper's minute bucket use the Python wall clock.
- Concurrency precedent: the slot refusal is proved with two role connections calling the function directly
  (`tests/e2e/test_definers_run_path_live.py:99-147`), not through the API.
- Evidence: plain-text files under `reports/<area>/` written with `encoding="utf-8", newline="\n"` (R105 writes
  `reports/skeleton/r105-walking-skeleton.txt`, `test_r105_walking_skeleton.py:209-210`; T11 wrote
  `reports/auth/t11-sessions-revocation.txt`). `tests/plan_b/test_evidence.py:17` scans `EVIDENCE_ROOTS =
  (reports/bootstrap, reports/skeleton, reports/auth, reports/ci)` for JWT shapes and generated secret values; a new
  `reports/<area>` is scanned only if added there. Live tests bind responses before asserting so pytest never prints
  a header (`test_r105_walking_skeleton.py:116`).

### 3.12 The sweeper's purge hook

- `sweeper/src/ops_sweeper/main.py:111-117` `tick()`: `run_sync` → `record_sync` (insert, claim and finish this
  minute's `sync_memberships` maintenance job, `:120-135`) → `sync.purge_expired(conn)`. Tick every
  `OPS_SYNC_TICK_SECONDS` (default 30, `:199`); health on `OPS_SWEEPER_HEALTH_PORT` 8071 (`:209`); startup asserts
  `app.logout_jti` (`:189`).
- `sweeper/src/ops_sweeper/sync.py:88-106` `purge_expired`: one transaction, `DELETE FROM app.sessions WHERE
  expires_at < app.current_time() - interval '1 day' OR revoked_at < … - interval '1 day'`, `DELETE FROM
  app.login_state WHERE expires_at < app.current_time()`, `DELETE FROM app.logout_jti WHERE expires_at <
  app.current_time()`; returns counts. This is the shape an expired-idempotency purge would take; the sweeper needs
  SELECT beside DELETE for the `WHERE` (erratum 25).
- `persistence.insert_maintenance_job` / `claim_maintenance_job` (§3.4) take only the four maintenance job types
  (`core/src/ops_core/jobs.py:37-47`, `:102-105`); no `purge_*` job type exists, and SA:504 lists none.

### 3.13 The worker today (what T12's new runs and jobs meet)

- `worker/src/ops_worker/handlers.py:221-235` `handle()`: `INVESTIGATE` and `EXECUTE` are handled; every other type
  (a `resume_input` job included) is logged "not handled by the walking skeleton" and finished.
- An `answer_only` run reaches `_draft_and_freeze` (`:116-123`), where `freeze_allowed(Intent(run["intent"]))` raises;
  the `except Exception` at `:110-114` turns it into `DRAFTING → FAILED` "drafting failed". So a `readonly_answer`
  admitted today ends FAILED, not ANSWERED (R114 is T20's).
- Nothing transitions a run to AWAITING_INPUT today, so no `clarification.requested` event exists for a
  `clarification_reply` to bind to. `transition_run` emits `clarification.requested` on `→ AWAITING_INPUT`
  (`0003_run_path_functions.py:343-348`); `append_event` refuses that type from callers (`:366-371`) but accepts
  `clarification.received` (in the allowlist, `:46`).

---

## 4. Declared debt that names T12 (`SESSION_STATE.md`), verbatim

- `:156` (Plan D shortcuts): "persona bearer tokens instead of sessions (T11/T12); … grant and `mark_sent` without
  membership, cancellation or deadline re-checks, and unbounded bodies (T09/T12/T21/T22)".
- `:162` (open items for Plan E and later): "the request body is parsed before authorisation in the API (T12), and the
  in-memory `FakeStore` does not check the tenant (T09 tests);" — today `post_message` checks the `requester` role
  before parsing (`app.py:436-437`) but parses the body before the conversation's existence/tenant check
  (`store.py:253-258`).
- `:188` (erratum 25): "The sweeper's `del` without `sel` on `sessions` and `idempotency_request` cannot run a
  `DELETE ... WHERE expires_at < ...` (spike section 3); flagged for T11/T12."
- `:233` (walking-skeleton debt): "no asset guard or expiry → T12/T21;"
- `:238`: "the API accepts bearer persona tokens from the dev-only direct grant (audience `ops-api`) instead of browser
  sessions, CSRF and `Idempotency-Key` → T11/T12;"
- `:245`: "the grant re-reads no current membership, and neither grant nor mark_sent re-checks cancellation or the
  dispatch deadline → T09/T21/T22; request bodies are not size-bounded → T12;"
- `:265` (Plan E debt): "`outbox`, `feedback`, `idempotency_request`, `operator_resolutions`,
  `documents`/`chunks`/`embeddings`, `model_permit` are absent, so their AM-20.2 rows are not yet in the grant matrix →
  T14/T12/T22/T17/T13;"
- `:271` (Plan F debt): "no `Idempotency-Key` on the new mutations (`/auth/logout`) or the existing ones;
  `idempotency_request` does not exist → T12;"
- Related lines that do not say T12 but bear on it: `:232` "no idempotency keys, outbox or `next_event_seq` lock →
  T14;" (T08 list); `:239` "wall clock instead of an injected clock; the interval is resolved once at admission and
  stored; expiry and asset freshness are written but not enforced → T09/T21;" — the admission interval is still on
  the wall clock (`app.py:447`); `:244` "the worker claims jobs … no reclaim of a job whose handler crashed (its run and
  conversation slot stay held) → T13/T14;".
- `privileges.py:8` assigns `feedback` to T12 as well; the feedback endpoint (BS:282) is in T21's instructions.

---

## 5. Open questions the planner must rule on

1. **Which mutations carry `Idempotency-Key`, and is it required.** BS:264 says every mutation; T11 note 3 exempts
   only the back-channel endpoint; Plan F ruling 20 left logout to T12. Candidates: `POST /conversations`, `POST
   …/messages`, `POST …/decisions` (whose function already takes `idempotency_key` and stores
   `decisions.idempotency_key`, `store.py:323-331` passes none), `POST /auth/logout`. Required on all of them breaks
   R105 and `test_auth_live.py` until they send one (both edited in the same plan); required on admission only leaves
   BS:264 partly unmet (an erratum or debt line). Missing-key status (422 `INVALID_INPUT` vs 400) and bounds (the
   reference used 8–128 chars, `reference/src/operations_copilot/service.py:24-25`) are unset.
2. **The scope of the key.** BS:244 lists tenant, subject, route, key. Is "route" the method plus path template, or the
   concrete path (with the conversation id)? A concrete path makes the same key reusable across conversations; a
   template makes a reuse across conversations a 409. Does the bearer and the cookie identity of one subject share a
   scope (same `(issuer, subject)`)? The reference scoped by owner only (`service.py:34`).
3. **What the fingerprint covers and where it is computed.** Raw body bytes (whitespace and key order matter, so a
   reformatted retry is a 409) versus `canonical_sha256` of the parsed, NFC-normalised model (a semantically equal
   retry replays, but a body that fails to parse has no fingerprint). Include the path parameters? Computed in the API
   (no definer can touch the table: `app_definer` has nothing on it, SA:429).
4. **What is stored and what a replay returns.** BS:244 says "accepted result identifiers"; BS:299 "the same logical
   result". Store ids only and rebuild the body from current state (a replay of a 202 then shows today's `status`,
   not `QUEUED`), or store the full status and body (byte-identical replay, a JSON column). `api` has no UPDATE on the
   table (SA:429), so the row is written once, in the same transaction as the work and last (SA:188) — there is no
   "in progress" row to update.
5. **Do refusals get a record.** AM-16 `reject`: "nothing written except the idempotency record". So a 422/409
   rejection is recorded and a replay returns the same refusal even after the slot frees. Does that hold for 401/403
   (identity is checked before the key is read?), for 404, for a 503 (no commit happened, so nothing can be recorded),
   and for an over-limit body (is it hashed at all)? Recording only 2xx and 409/422 is one consistent reading; each
   other choice changes what R016's "one logical run then 409" test sees.
6. **Two requests with the same key in flight.** With a unique scoped key, the second transaction's INSERT blocks on
   the first's uncommitted row, then fails with `unique_violation` (23505, not translated by `persistence.translate`,
   so it would surface as 503). Options: catch it, roll back and re-read the winner (needs a second unit, `api` has
   SELECT); or take `pg_advisory_xact_lock` on the scoped key first (an advisory lock needs no grant; it is not in the
   SA:188 lock order, which would need a placement). One API process serialises all units (`persistence.Session`
   lock), so the race is only reachable with two processes or two role connections in a test.
7. **The 24 h window.** An `expires_at` column set from `app.current_time() + 24 h` (testable with the test clock) or
   a `created_at` compared at read time? Does a lookup ignore expired rows (so a key is reusable after 24 h) before
   the purge runs? The purge: a fourth `DELETE` in `sync.purge_expired` (`sweeper/src/ops_sweeper/sync.py:88-106`) plus
   SELECT for the sweeper (erratum 25 extended to this table, against SA:429's bare `del`), or a new maintenance job
   type (not in SA:346/SA:504's list). The 24 h value: a setting (`OPS_*`, BS:542 "validated configuration") or a
   constant.
8. **The table itself.** Columns (BS:244: tenant, subject, route, key, body hash, result identifiers; plus `issuer`?
   status code? body? `expires_at`?), the unique constraint, `tenant_id` kept as a column although there is no RLS
   (SA:523), a `privileges.GRANTS` row and `NO_RLS` entry, and revision 0006 freezing its cells (the 0005 pattern).
   The API's startup `assert_relation` moves to the new relation; the dev database needs the owner's migrate.
9. **The slot rule.** The partial unique index already exists as `WHERE slot_held` (`0002:213`), maintained by
   `_transition`. Review note 1 says "over AM-10 active states": keep `slot_held` (equivalent while `_transition` is
   the only writer) or restate the index on `state IN (…)`? And whether the API also locks: AM-16 evaluates `clarify`
   "after the active-run check", which needs a read of the active run before deciding; without a lock a concurrent
   `investigate` can take the slot between that read and a stored clarification (the clarification then answers a
   conversation that is now busy). `api` cannot `FOR UPDATE` `conversations` (no UPDATE grant); it can `FOR UPDATE`
   `runs` rows that exist but not an absent one; an advisory lock on `(tenant, conversation)` needs no grant but is a
   new entry for SA:188's order. Cost of none: a documented benign race.
10. **Does a read-only run hold the slot.** `create_run` sets `slot_held = true` for `answer_only` too (§3.5), so an
    `ask` blocks a new `investigate` in the conversation until it ends; R017 and BS:548 speak of one "mutating" /
    "state-mutating" run. Keep (one active run of any intent, as SA:145 reads) or make `answer_only` not hold the slot
    (a `create_run` change in a new revision and a `_transition` change).
11. **"Interval resolved once": the clock and the storage.** Today `datetime.now(UTC)` in Python (`app.py:447`). Move
    to `SELECT app.current_time()` inside the admission unit (SA:157–158; then R018's "retry after clock advance" is
    testable with `test_harness`), or keep the wall clock (no test-clock coverage). The interval is stored on `runs`
    only; a `clarify` stores no interval, so the reply re-resolves "last 24 hours" at its own admission. What "retry"
    means in R018: a replay with the same key (the stored record returns the original interval) or a new key (a new
    request, a new interval by design).
12. **What "text and structured fields disagree" means.** No parser exists. A deterministic rule must extract an asset
    id (the `AssetId` pattern, e.g. `A17`) and a relative window ("last N hours/days") from `text`; what counts as a
    disagreement (text names another asset; text names a window and `hours` differs; text names neither); whether a
    field missing from `context` but present in the text is filled from the text (BS:297 "Structured form fields take
    precedence only when they agree") or clarifies; and how days map to hours within 1–168. Each rule needs a test
    row (R129: "each of the six routes tested").
13. **The `clarify` response and stored rows.** AM-16 fixes 200 and one `messages` row with
    `kind=clarification_question`. Is the requester's own message also stored (as which `kind`)? `messages.author` is
    `uuid NOT NULL`: who authors a system-written question (the requester's subject, a fixed system UUID, or a new
    nullable column)? The question text: a fixed template per cause (missing asset, missing interval, asset conflict,
    interval conflict)? The 200 body's keys (no schema exists, §3.9). The route decorator is fixed at 202, so a 200
    needs an explicit response.
14. **`status_question`.** Which run does it describe (the conversation's active run, its latest run, or a
    `run_id` field the request does not have)? What "answered from recorded events and state" produces (a template
    over `runs.state` and the latest event types; `api` has SELECT on both). HTTP status (AM-16 names none; 200?). The
    two rows are inserted in one transaction and get the same `created_at` (`now()`), and `messages` has no
    `sequence` (BS:230), so their order is not recorded; add a sequence (a migration; `api` cannot UPDATE
    `conversations` to keep a counter) or an explicit timestamp from `app.current_time()` (distinct per statement)?
    Is a status question allowed while the conversation is busy (it must be: it makes no run, R017)?
15. **`clarification_reply`.** AM-16: "reply bound to an outstanding clarification ID and expected version" →
    "message + `resume_input` job, 202". `MessageRequest` has no `question_id`/`expected_version`; `ClarificationReply`
    does but serves BS:273's `POST /runs/{id}/clarifications`, which does not exist. Options: add the two fields to
    `MessageRequest` when `kind=clarification` (a `build_schemas.py` change and regenerated schemas/examples), or add
    the BS:273 route and treat it as the route's entry. The "outstanding clarification ID" is a run-level
    `clarification.requested` event (dedup `run_id:clarification_event_id`, SA:501) that nothing emits today (§3.13),
    and the worker ignores `resume_input` jobs; the route can only be tested with a run put into AWAITING_INPUT by
    hand (the worker role's `transition_run`). The job insert must be target-less (`jobs` INSERT only, §3.7). Does it
    also append `clarification.received` (allowed for `api`)? And how does a reply to a **conversation-level**
    `clarification_question` (no run) differ: AM-16 says it "re-enters admission as a new message".
16. **`readonly_answer`.** `create_run` requires an asset and an interval for every intent (§3.5) and `runs` makes
    them `NOT NULL`, so `kind=ask` without them cannot create a run: clarify, reject 422, or a schema/function change.
    Its status code (AM-16 names none; 202 like `investigate`?). Until T20 such a run ends FAILED in the worker
    (§3.13): acceptable for T12's evidence, or does T12 leave `ask` unrouted (a debt line)?
17. **The route table in `core/routing.py`.** Shape (ordered rows of predicates → `AdmissionRoute`, first match wins;
    or a total function plus an enumerable table of cases), where the active-run fact enters (it needs a database
    read, so the table is pure over facts the API gathered), and how R129's "each of the six routes tested" walks it.
    T20 adds the graph table to the same module later.
18. **The model hint.** "a model hint can only produce clarify" (T12, SA:375), but no model runs in the API and the
    model router is T19's (worker). Options: a hint input to the table that can only downgrade to `clarify`, tested
    with a stub hint and no model; or no hint input now (a debt line naming T19). Either way the API gains no model
    dependency.
19. **Body size and the 422.** BS:546: 64 KiB body, 4,000 characters text (the latter already enforced by `Text`).
    Where: an ASGI middleware that checks `Content-Length` and counts streamed bytes, or a check inside `body()` after
    reading (the whole body is then already in memory). Status: BS:301 says 422 for "shape/content limits"; HTTP's
    413 is not in the spec's list. Applies to every route or to the mutation routes only? Is an oversized request an
    AM-16 `reject` with an idempotency record?
20. **429 source.** No limiter exists. BS:550 "Queued work | 100 total initially; bounded tenant quotas": counting
    queued work needs a read the `api` role can do — it has no SELECT on `jobs` (§3.7); `runs` is readable only per
    tenant under RLS; a global count needs a cross-tenant view `api` does not have (`run_directory` has no state).
    BS:548 "one active compute lease per requester" is the worker's. Options: a per-tenant count of active runs (a
    tenant quota, BS:550), a per-subject in-process token bucket (not durable, per process), or a 429 path that exists
    only behind a configured limit with a test that sets it low. Each needs a setting name and a `Retry-After`
    decision.
21. **503 source.** Today: any `psycopg.Error`, `PersistenceError`, `IllegalTransition`, `EventRuleViolation`,
    `AuthorityViolation` → 503 with `retryable: true` (`safe()` sets `retryable = status == 503`). BS:301 says 503 "for
    unavailable durable admission". Is a server defect (`AuthorityViolation`, `Internal`) really `retryable: true`? Is
    an untranslated `unique_violation` (question 6) a 503? Does the R115 503 test stop the database, or inject a
    `psycopg.OperationalError` through a fake store (the unit precedent, `tests/plan_d/test_api.py:388-401`)?
22. **The safe error everywhere.** Unknown path/method answers FastAPI's `{"detail": …}` and an unexpected exception
    a plain 500 (§3.1): add a Starlette `HTTPException` handler and a catch-all (and to what status: 404/405 as
    SafeError `NOT_FOUND`/`INVALID_INPUT`? 500 has no code in the enum). `request_id` is random and unlogged: log it
    with the error line (so an operator can correlate) or keep it opaque. Messages must never name an unauthorized id
    (BS:301): today's "no such conversation or superseded run" names none.
23. **Check order on the messages route.** Today: identity (401) → CSRF/origin (403) → role (403) → body (422) →
    conversation (404) → slot (409). With the key: before or after the body parse (a replay of a malformed body?),
    before or after the membership check (a replay by a subject whose membership was revoked must not return the
    recorded success — BS:264 "authenticated current session"). Does a reader (no `requester` role) get 403 before a
    404 for a conversation of another tenant (existence leak is not possible across tenants either way, RLS hides it)?
24. **Conversations.** `POST /api/v1/conversations` is a plain INSERT by `api` (no definer function; SA:414 allows
    it); body none; 201 `{conversation_id}`. With an `Idempotency-Key` a replay returns the same id. Does it take a
    body (title?) — none in the spec or schemas; `created_by` stands in for BS:230's "owner".
25. **The accepted 202 body.** BS:299: "`conversation_id`, `message_id`, `run_id`, `status`, `state_version`, and
    authorized relative status/stream locations". Today's `status_url`/`events_url` exist; the stream route is T27's.
    Add a `stream_url` that 404s until T27, or omit it (a debt line)? `status` on replay: the recorded `QUEUED` or the
    current state (question 4).
26. **"Crash-before-commit leaves no ack" (DoD 1, R015).** The API has no fault hook (§3.10). Options: a unit test
    with a fake store that raises after the message insert and before commit (proves no 202, not durability); a live
    test that holds the unit open and kills the connection (`pg_terminate_backend` from the superuser) mid-admission;
    or a test-profile fault in the API through `core.testing.faults` (R098: refuses outside `PROFILE=test`). "After
    commit the job exists" is a read of `app.jobs` by the superuser after a 202.
27. **`supersedes_run_id`.** `create_run` validates it against tenant **and conversation**, not tenant/asset
    (SA:450, SA:154). A requester superseding an incident from another conversation on the same asset is refused
    (404). Keep (erratum) or change the function (new revision)?
28. **Message `kind` stored for ordinary requests.** Today the request kind (`investigate`) is stored. With the stored
    kinds `status_question`, `status_answer`, `clarification_question`, is a `kind=status` request stored as
    `status_question` (AM-16) and an `ask` as `ask`? Add a CHECK constraint on `messages.kind` listing the vocabulary
    (a migration) or keep it free text with a Python enum only?

---

## 6. Glossary of exact names

- `Idempotency-Key` — Where: BS:264, T12; What: the request header; not read anywhere in the code today
- `idempotency_request` — Where: BS:244, SA:429, SA:523; What: the dedup table; does not exist
- `IDEMPOTENCY_CONFLICT` — Where: `ErrorCode`, `error.schema.json`; What: the 409 code for same key, different body;
  never emitted today
- `SLOT_OCCUPIED` — Where: `ErrorCode`; OC005 DETAIL in `create_run`; What: 409 when the conversation holds an active
  run
- `RATE_LIMITED`, `UNAVAILABLE`, `INVALID_INPUT` — Where: `ErrorCode`; What: the 429, 503, 422 codes
- `SafeError` — Where: `contracts.py:439-446`; What: `{code, message, retryable, request_id}`
- `ApiError`, `safe()` — Where: `app.py:45-61`; What: the API's refusal type and response builder
- `runs_one_active_per_conversation` — Where: `0002:213`; What: `UNIQUE (conversation_id) WHERE slot_held`
- `slot_held` — Where: `runs` (0002); What: true while the run is in an AM-10 active state
- `ACTIVE_STATES` — Where: `states.py:211`; What: the AM-10 eight
- `create_run` — Where: `0003:237-320`; `persistence.py:198-226`; What: `(uuid, uuid, jsonb, text, uuid) → (run_id,
  state_version)`
- `Intent.INVESTIGATE` / `Intent.ANSWER_ONLY` — Where: `states.py:69-73`; What: `runs.intent` values `investigate` /
  `answer_only`
- `AdmissionRoute` — Where: `routing.py:17-25`; What: `investigate`, `clarification_reply`, `status_question`,
  `readonly_answer`, `clarify`, `reject`
- `MessageKind` — Where: `contracts.py:142-148`; What: request kinds `investigate`, `ask`, `status`, `clarification`
- `status_question`, `status_answer`, `clarification_question` — Where: AM-16, T12; What: stored `messages.kind` values;
  no code constant
- `MessageRequest`, `MessageContext` — Where: `contracts.py:151-166`; What: the messages body
- `ClarificationReply` — Where: `contracts.py:182-194`; What: `{question_id, expected_version, context}`; unused
- `resume_input` — Where: `JobType`, SA:501; What: job for a clarification reply; dedup `run_id:clarification_event_id`
- `clarification.requested` / `clarification.received` — Where: `outcomes.py:147,160`; What: run events; the first only
  via `transition_run`
- `run.accepted` — Where: `create_run`; What: the admission event, payload `{}`
- `resolve_interval` — Where: `store.py:97-100`; What: `(end - hours, end)`, `end` truncated to seconds
- `app.current_time()` / `app.test_clock` / `test_harness` — Where: AM-20.6; `tc_0001`; What: the injectable clock and
  its only writer
- `Session.unit(tenant_id)` — Where: `persistence.py:136-151`; What: one locked transaction on the process's one
  connection
- `identity` / `browser_mutation` / `enabled_identity` — Where: `app.py:143-210`; What: the three FastAPI dependencies
- `X-CSRF-Token`, `ops_session`, `ops_csrf` — Where: `auth.py:33-36`; What: CSRF header and cookies
- `purge_expired` — Where: `sweeper/src/ops_sweeper/sync.py:88`; What: the sweeper's per-tick expiry deletes
- `insert_maintenance_job` / `claim_maintenance_job` — Where: `persistence.py:515-549`; What: tenant-less sweeper jobs,
  key `<type>:<minute bucket>`
- `OPS_LIVE`, `sweeper_stamps`, `fresh_memberships`, `migrated`, `role_conn`, `app_conn` — Where:
  `tests/e2e/conftest.py`; What: live-test gate, marker and fixtures
- `EVIDENCE_ROOTS` — Where: `tests/plan_b/test_evidence.py:17`; What: the report directories scanned for secrets
- `scripts/build_schemas.py` — Where: —; What: generator of every file under `schemas/`; drift is a test failure

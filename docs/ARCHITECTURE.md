# Architecture: what this project demonstrates

Operations Copilot exists to show four things an interviewer should be able to verify in the code, the tests and the demos: **least privilege**, **routers**, an **orchestrator**, and **MCP servers**. This page is the map. Each section names the components, the requirement IDs whose tests prove the claim (`handoff/acceptance-matrix.json`), and the demo that shows it. The rules themselves live in `SPEC_AMENDMENTS.md` (cited as AM-nn).

> **Status: target design; no code exists yet.** `STATUS.md` says what is built. Every "Planned proof" table names the tests that will exist when the owning task is done, and "Where the code will live" is a plan, not a listing.
>
> **Not claimed for v1:** a tested Kubernetes deployment; multiple fenced worker replicas (one worker runs); a third-party-reviewed holdout (the owner writes it); detection of evaluation differences under about 30 points (n≈25); instant failure after a lost response (abort waits up to 5 minutes); automatic undo of anything (ADR-0002, AM-13, AM-50).

## The system in one picture

```mermaid
flowchart LR
  subgraph browser [Browser]
    UI[React workspace]
  end
  subgraph app [Application trust zone]
    API[api<br/>admission router, decisions, SSE]
    W[worker<br/>LangGraph orchestrator]
    SW[sweeper]
  end
  subgraph mcp [MCP boundary]
    MR[mcp-read<br/>read tools only]
    MW[mcp-write<br/>grant + guarded write]
  end
  subgraph sims [Synthetic domain systems]
    AS[asset-sim]
    IS[(incident-sim<br/>own database)]
  end
  KC[Keycloak]
  PG[(PostgreSQL<br/>app schema, RLS, definer functions)]
  OL[Ollama qwen3:8b]
  UI -->|HTTPS commands| API
  API -->|SSE| UI
  KC -.tokens.-> API & W & MR & MW
  API --> PG
  W --> PG
  SW --> PG
  W -->|read handle| MR
  W -->|execute / recover handle| MW
  W -->|prompts only| OL
  MR -->|functions only| PG
  MW -->|functions only| PG
  MR --> AS
  MW --> IS
```

The model (bottom right) has no credential, no database access, no network reach and no tool it can call. It receives evidence and returns text. Everything that can change the world sits on the left. A write needs an independent reviewer's decision bound to the exact payload hash, and then the final grant inside the database, which re-checks membership, hash, expiry, cancellation and the asset guard in one transaction (AM-13, AM-20.3).

---

## 1. Least privilege

**Claim.** Every principal holds exactly the authority its job needs, enforced by the database, the identity provider and the network, not by application code being careful.

### Principals and what each one holds

| Principal | Credential | Database access | Can reach | Cannot |
|---|---|---|---|---|
| Browser user | Opaque server-side session cookie | none | api only | hold a token, reach MCP or the databases |
| `api` | Keycloak client; DB role `api` | SELECT on conversation and audit tables; INSERT on messages, idempotency, feedback, outbox, `resume_input` jobs; UPDATE on `runs.cancel_requested` only; runs, decisions and revisions only through `create_run`, `record_decision`, `create_revision`; status answers and conversation clarifications are plain messages | PostgreSQL, Keycloak (login, `view-users` check) | update `runs.state`; insert decisions, proposals, grants, attempts or events directly; reach either sim |
| `worker` | Keycloak client; DB role `worker` | run_lease, jobs, drafts, invocation_context (insert), outbox (insert), corpus tables (ingestion), model_permit, checkpoints schema; `runs` columns `checkpoint_id`, `budget_used`; transitions only through `transition_run` (pre-grant states), `freeze_proposal`, `mark_unknown` and `escalate_run`; handle revocation through `revoke_handles` | PostgreSQL, mcp-read, mcp-write, Ollama | write decisions, memberships, grants, attempts or events; mark a run SUCCEEDED; reach either sim |
| `sweeper` | DB role `sweeper`; Keycloak `view-users` service account | leases (reclaim), jobs, memberships (sync), outbox, expired sessions and idempotency rows; expiry and deadline transitions only through `expire_proposal` and `escalate_run`, iterating tenants | PostgreSQL, Keycloak admin API (read) | decisions, grants, attempts, any pre-grant or success transition |
| `mcp-read` | Keycloak client; DB role `mcp_read` | **no tables**; `EXECUTE` on `resolve_invocation`, `asset_scope`, `search_procedures_scoped` | PostgreSQL (functions), asset-sim | any write-path function; incident-sim |
| `mcp-write` | Keycloak client; DB role `mcp_exec` | **no tables**; `EXECUTE` on `resolve_invocation`, `grant_execution`, `mark_sent`, `record_outcome`, `request_abort`, `lookup_action` | PostgreSQL (functions), incident-sim | the search and asset functions; asset-sim; it sees only the frozen payload bytes, never corpus text |
| `operator` CLI | DB role `operator` | `EXECUTE` on `resolve_escalation` only | PostgreSQL | everything else |
| `app_definer` | no login | owns the functions, owns no tables; sees rows only through explicit RLS policies | — | be used by a process |
| Model | **none** | none | nothing outbound; it answers requests from the worker only | call a tool, see a credential, assert an outcome, select a route |

The full grant table is AM-20.2; the function contracts (callers, inputs, locks, transitions, events) are AM-20.3; the policies are AM-20.5.

### Mechanisms

- **Capability handles.** A worker calls an MCP server with a short-lived, hashed handle bound to one run, one lease fence, one server (read or write) and the token's client ID. The server derives the tool allowlist from the job type, run state and attempt state (AM-15, AM-20.3). The worker cannot choose its own allowlist.
- **Token audiences.** Each MCP server verifies `aud` against its own resource URL and `azp` against the allowed workload clients. A browser token or a worker token presented to incident-sim is rejected (AM-20.7).
- **The final gate is a database function.** `grant_execution` re-checks membership, hash, expiry, cancellation and the asset guard inside one transaction, and only `mcp_exec` may call it. Approval text, model text and chat text never grant anything.
- **Append-only audit.** Decisions, proposals, grants, attempt states, events and operator resolutions are insert-only for every runtime role; "state" is the latest row.
- **Network.** Every published port binds to 127.0.0.1 (T05); the worker-to-sims and browser-to-internal paths are denied at the Docker network level (R066); Ollama runs on the host and is restricted to loopback and the Docker subnet by an owner-applied firewall rule (AM-31), so "the model cannot reach the destination" is a host-firewall fact, not a container test.

### Planned proof

| Requirement | What its test will show |
|---|---|
| R084, R124, R128 | `mcp_read`/`mcp_exec` cannot SELECT any table; every role holds exactly its grants; direct writes to audit tables fail |
| R106 | Definer functions are hardened and tenant-isolated by explicit policy text |
| R131 | A read handle presented to mcp-write is rejected; mcp-read cannot execute a write function |
| R026, R027, R085, R100 | Wrong audience, replayed handle, worker-chosen allowlist and cross-run proposal all fail |
| R043, R093, R044 | Self-approval and author-approval denied; approval bound to the exact payload hash |

**Demo 2 (denial):** a cross-team or injected attempt is rejected with no incident written and a clear user state (BUILD_SPEC §28).

---

## 2. Routers

**Claim.** Every path a request can take is enumerable in advance, chosen by deterministic rules first, and no input the router cannot classify ever starts work. Model output may *hint* at a route; it never *selects* one.

There are three routers (AM-16):

| Router | Lives in | Input | Routes | Rule |
|---|---|---|---|---|
| **Admission router** | `api` | an authenticated message | `investigate` (new run), `clarification_reply` (resume), `status_question` (answer from records, no run), `readonly_answer` (read-only run, no proposal), `clarify` (conflicting or missing fields), `reject` | Structured fields and `kind` decide; a status question never creates a job; a conflict between text and structured fields becomes a clarification, not a guess (R018) |
| **Graph router** | the orchestrator's `route_request` node | run state, `runs.intent`, resolved context, evidence sufficiency (a code rule), the validated draft kind | `clarify`, `retrieve`, `draft`, `answer_only`, `abstain`, `freeze`, `await_decision`, `execute`, `recover`, `publish` | A route table in `core/routing.py`; conditional edges only from that table; the model's output can only choose between abstaining and drafting, and `freeze` is additionally gated by the requester's intent |
| **Model router** | `DraftGenerator` factory in the worker | `MODEL_MODE` and policy | `fake` (deterministic, tests), `qwen3:8b` (local), a future larger model | Chosen by configuration, recorded in every run's manifest and `explanation.ready` event; **no silent fallback** between routes |

### Planned proof

| Requirement | What its test will show |
|---|---|
| R129 | Every admission and graph route is enumerated; an unroutable or ambiguous input produces a clarification or a 422 and never a job |
| R017, R018 | One active run per conversation; relative intervals resolve once and conflicts clarify |
| R130, R041 | The model route is recorded; a missing model fails clearly instead of falling back |
| R036, R125 | Instructions found in retrieved documents cannot add a tool or authority, and a draft cannot assert a supersession |

**Demo 1 (success)** shows the admission router creating one run and the graph router moving it through retrieve → draft → freeze → await decision → execute.

---

## 3. Orchestrator

**Claim.** One explicit LangGraph graph coordinates the investigation. It is durable, resumable after a crash, and never the source of authority.

### The graph

```mermaid
flowchart LR
  L[load_run] --> R{route_request}
  R -->|clarify| C[await_clarification<br/>interrupt: ends here,<br/>resumed by a resume_input job]
  R -->|retrieve| E[retrieve_evidence<br/>via mcp-read]
  R -->|draft| D[draft_with_langchain]
  R -->|answer_only / abstain| P[publish_state]
  R -->|freeze| V[validate_and_freeze<br/>freeze_proposal]
  R -->|await_decision| A[await_independent_decision<br/>interrupt: ends here,<br/>resumed by an execute job]
  R -->|execute| X[execute_approved_proposal<br/>via mcp-write]
  R -->|recover| O[reconcile_outcome<br/>via mcp-write]
  R -->|publish| P
  E --> R
  D --> R
  V --> R
  X --> R
  O --> R
```

Every node returns to `route_request`, and every labelled edge is one row of the AM-16 route table (ten routes). The two interrupt nodes end the graph run; a committed human event and its wake-up job start a new run of the graph from the stored checkpoint. Nodes are deterministic Python; only `draft_with_langchain` calls the model, and only `retrieve_evidence`, `execute_approved_proposal` and `reconcile_outcome` call MCP servers.

### Properties

- **Evidence before drafting.** The draft node cannot run until `retrieve_evidence` has returned permitted, versioned evidence (R038).
- **Durable pauses.** Clarification and review are `interrupt()`s with a persisted checkpoint; the human's reply arrives as a committed event and a wake-up job, never as trusted resume content (R022, R023, R042).
- **Crash-safe.** Checkpoints are written synchronously; the accepted checkpoint ID is stored on the run under the lease fence; every node is idempotent because LangGraph re-runs a node from its start on resume (AM-12, R108).
- **Not the authority.** Graph state carries IDs and hashes only (R091). The run's state, the approval and the destination receipt live in PostgreSQL and are rechecked by every node. A checkpoint can never approve or execute anything.
### Planned proof

| Requirement | What its test will show |
|---|---|
| R038 | A trace shows MCP reads complete before the draft node |
| R042, R108 | Pause/resume survives a worker restart from the stored checkpoint; a stray newer head is ignored |
| R087, R088, R107 | Only the current lease fence can write; a 30 s+ model call keeps the lease; a stale worker's write is rejected |
| R094, R109 | Every grant-to-receipt crash window ends in exactly one truthful outcome |

**Demo 3 (recovery):** `docker kill` the worker between destination commit and acknowledgement; the restarted worker reconciles the original action ID and the destination holds exactly one incident.

---

## 4. MCP servers

**Claim.** Tools cross one standard, authenticated protocol boundary, split into two servers so that the server which can *read* evidence cannot *write* incidents and the server which can write cannot read evidence.

| | `mcp-read` | `mcp-write` |
|---|---|---|
| Tools | `get_asset_status`, `get_recent_alerts`, `search_procedures` | `create_incident`, `get_incident_receipt`, `abort_incident` |
| Handle types accepted | `investigate`, `resume_input` jobs | `execute`, `recover` jobs |
| Token audience | `MCP_READ_RESOURCE_URL` | `MCP_WRITE_RESOURCE_URL` |
| DB role | `mcp_read` (3 functions) | `mcp_exec` (6 functions) |
| Downstream | asset-sim, governed corpus (through functions) | incident-sim |
| Cannot | grant, dispatch, abort, see receipts | search, read asset data, see corpus text (it sees only frozen payload bytes) |

- Protocol revision 2026-07-28 over Streamable HTTP; per-request protocol version validated (AM-30).
- Tool inputs have JSON schemas; arguments that try to supply a role, tenant, actor or approval are rejected (AM-15).
- Results are typed envelopes; a transport success can still be an application failure, and the caller verifies receipt hashes before recording success.
- The model never calls either server. The orchestrator's deterministic nodes do, with a handle the server resolves to a run, a fence and an allowlist.
- Neither server is the scheduler or the permission policy; an argument saying "approved=true" is rejected at the schema.

### Planned proof

| Requirement | What its test will show |
|---|---|
| R025 | An independent process lists and calls tools over the network |
| R026, R027 | Wrong or missing audience, browser token, replayed or expired handle rejected |
| R028, R029, R030 | Read tools enforce current access; unexpected tools fail closed; receipt lookup is restricted to recovery |
| R131 | mcp-read holds only the three read-path functions and rejects write handles; mcp-write holds only the six write-path functions and rejects read handles (both share `resolve_invocation`) |
| R096 | The destination's action key is atomic, permanent and accepts only mcp-write's identity |

All three demos cross the MCP boundary.

---

## Where the code will live (not yet written)

| Directory | What to look at first |
|---|---|
| `core/domain/`, `core/routing.py` | the transition table, the route tables, the reason enum, canonical JSON |
| `core/db/migrations/` | roles, grants, definer functions, RLS policies (AM-20 in SQL) |
| `api/` | the admission router and the decision endpoint |
| `worker/graph/` | the orchestrator's nodes and edges |
| `mcp-read/`, `mcp-write/` | the two tool servers and their token verifiers |
| `incident-sim/` | the destination's atomic action-key table |
| `tests/acceptance/` | one file per requirement ID, created by the owning task |
| `docs/PROJECT_HISTORY.md` | the problems found while designing this, and what changed |

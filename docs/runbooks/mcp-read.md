# mcp-read: the authenticated read server, its token checks and invocation handles (T15)

Who this is for: whoever runs mcp-read, calls it, or debugs a worker run that failed with "retrieval failed". The
design is AM-30, AM-20.7 items 6 and 11, AM-15 and AM-20.3 in `SPEC_AMENDMENTS.md`, BUILD_SPEC §9 and §10, and Plan J
(`docs/superpowers/plans/2026-10-15-first-slice-j-mcp-read-verifier-handles.md`).

## What a call must carry

A POST to `http://127.0.0.1:8081/mcp` (Streamable HTTP, protocol revision 2026-07-28, stateless, JSON responses) is
checked in this order; the first failure decides the answer.

1. **`MCP-Protocol-Version: 2026-07-28`**, exactly once. Anything else, an absent header included, is HTTP 400 with
   the JSON-RPC error `-32022` "Unsupported protocol version" before authentication: an unauthenticated client learns
   only this rule. The SDK would otherwise send such a request down its legacy path, where no version is checked.
   mcp-write applies the same guard.
2. **A bearer token** that is the worker's access token: RS256 from the realm's keys, `iss` the realm, not expired,
   `aud` containing `MCP_READ_RESOURCE_URL` (default `http://mcp-read:8081/mcp`), `azp` the worker's client
   (`OPS_WORKLOAD_CLIENT_ID`, default `ops-worker`, T47), a `sub`, and the
   `typ` claim `Bearer` (`read_verifier`); `McpVerifier` refuses again any token whose `aud` lacks this server's URL,
   and only then stamps that URL as the token's resource. The SDK's resource check (`validate_token_resource`) is on
   as a second layer, which cannot refuse anything while the stamp is this server's own URL. Any failure is HTTP 401
   `invalid_token` with a `WWW-Authenticate` header pointing at the protected-resource metadata, which the SDK serves
   at `/.well-known/oauth-protected-resource/mcp` (it stays as the pinned protocol's resource-server metadata; nothing
   else of the authorization spec is in scope).
3. **The SDK's own checks**: the `params._meta` protocol version must equal the header (else 400, `-32020`
   `HEADER_MISMATCH`), `Mcp-Method` and `Mcp-Name` must match the body, the tool must exist (an unknown tool is a tool
   error), and its arguments must match the strict input schema (extra keys such as `tenant_id` are refused).
4. **`X-Ops-Invocation`**, the handle the worker minted for this job. It is a lookup key, never an identity (SA:566),
   and is never logged. `app.resolve_invocation` hashes it and, under the run's lease row lock, requires: the hash is
   known, the handle is not revoked or expired (60 s), its fence is the lease's and the lease is live, its `azp` is
   the token's, its job is its own run's and not finished, and the job type is a read type. Then Python requires the
   tool to be one of the job type's and the run to be in one of the job type's states (`investigate`: QUEUED,
   RETRIEVING, DRAFTING; `resume_input`: AWAITING_INPUT, QUEUED). Every refusal of a presented handle is the same tool
   result: `status` `error`, `error.code` `INVALID_HANDLE`, `error.message` "invocation handle rejected", never a hint
   of the cause and never an action id. A call with no handle at all gets the same code with the message "missing
   invocation handle", which tells the client only what it already knows.

## Starting it

`python -m ops_mcp_read` (or `scripts/skeleton.py up`) needs the database at revision 0013: at start it refuses when
`app.test_clock` exists outside the test profile, when `app._resolve_handle` lacks 0009's job binding, when
`app.search_procedures_scoped` (0011) is missing, when `app.asset_scope` or the search's `retrieved_at` (0012) is
missing, and when the search has no vector branch (0013) ("… predates this service; run scripts/skeleton.py migrate
for this profile"). It contacts no Ollama at start: the embedding pin is checked on each vector call. It also reads
its own workload secret (`kc_client_secret_ops_mcp_read`) at start, for asset-sim. mcp-write makes the 0009 check at its own
start. The search answers from the governed corpus, so a database that was never ingested (`scripts/skeleton.py
ingest`) answers every search with no results and `corpus_version` `none`. Readiness (`/health/ready`) needs the
realm's signing keys and the database; asset-sim is a dependency of a call, not of readiness.

## The three read tools (T16)

Each tool advertises exactly its committed input schema (`schemas/tools/<tool>.input.schema.json`); the worker
compares what it is shown with the same file and refuses to call a server that lists another tool set (R029). It also
refuses an answer over 256 KiB (measured as the UTF-8 JSON of the structured result), one that fails the committed
result contract, and any other failure inside the read session: each is the same failed run, "retrieval failed". Every
call resolves the handle and checks the tool in one committed unit, then reads the run's scope through
`app.asset_scope` in a second (the handle again, and the run's requester must
still hold an active requester membership in the run's tenant: R028); a handle refused at any unit, or a requester who
lost the membership, is the same `INVALID_HANDLE` envelope. The tenant, the asset and the interval come from the run,
never from an argument.

- `get_asset_status(asset_id)` and `get_recent_alerts(asset_id, start_at, end_at, limit 1-100[, cursor])` answer for
  the run's own asset and fixed `[start_at, end_at)` only: another asset is `ASSET_OUT_OF_SCOPE` and another interval
  (compared as instants: `Z` and `+00:00` agree) is `INTERVAL_OUT_OF_SCOPE`, both before asset-sim is asked. Then
  mcp-read calls asset-sim (`OPS_ASSET_SIM_URL`) with its own `ops-mcp-read` token, the run's tenant and the database
  instant `as_of`, outside any transaction, no retry, with one 10-second budget for fetching its token and asking.
  asset-sim unreachable, slow, failing (5xx), refusing the token (401) or a token fetch that fails is `UNAVAILABLE`
  (`retryable: true`); an asset asset-sim does not know for this tenant (another tenant's included) is `NOT_FOUND`; a
  cursor asset-sim refuses is `INVALID_CURSOR`; an answer outside the tool-result contract or the run's scope is
  `UPSTREAM_INVALID`, and so is any HTTP status above that mcp-read has no meaning for (a 403, a 400 to a request
  without a cursor). The scope check holds a status to `observed_at` equal to `as_of` and a page of alerts to at most
  `limit` alerts, all of the run's asset and interval and none after `as_of`. The envelope's `observed_at` is `as_of`
  (to the second); for alerts, `truncated` is true exactly when `next_cursor` is set. The rules asset-sim answers by
  are in `docs/runbooks/asset-sim.md`.
- `search_procedures(query 1-500, limit 1-8, mode[, asset_type])`: `lexical` or `vector_exact` (T18). mcp-read asks
  asset-sim for the run's asset type and
  searches that type (documents of that family or of none), whether or not the caller named one; a caller's
  `asset_type` may only repeat it, compared exactly, case included (`ASSET_TYPE_OUT_OF_SCOPE`). Only when asset-sim
  does not know the run's asset does the caller's `asset_type` stand, or, with none given, any asset type. A third
  unit calls `app.search_procedures_scoped`, which returns the instant it decided permission at: every result's
  `retrieved_at` and the envelope's `observed_at` are that instant. An excerpt is the whole section up to 8000
  characters, and a cut one sets `truncated`. The settings and how to read the ranking are in `docs/retrieval.md`.
  For `vector_exact`, after the asset type and before the third unit, mcp-read reads `data/embedding-pins.json`,
  checks the pinned digest against Ollama's `/api/tags` (`OPS_OLLAMA_URL`) and embeds `search_query: ` + the query
  with `/api/embed`, both within one 10-second budget and outside any transaction, then calls the definer with
  `mode='vector'` and that embedding; the answer says `retrieval_mode` `vector_exact`. It asks Ollama nothing else
  and never a generation. A missing, unreadable or malformed pin, or an installed model that is not the pinned one,
  is `UNSUPPORTED_MODE` (`retryable: false`); Ollama unreachable, slow (the 10 seconds spent), failing (5xx) or not
  configured is `UNAVAILABLE` (`retryable: true`); an answer it cannot use (not 768 finite numbers, none above 1e6
  in magnitude, with a norm of at least 1e-6; a status other than 200 that is not a 5xx; a body that is not a JSON
  object; a tags answer without a model list) is `UPSTREAM_INVALID`; a permitted section without an embedding is `REFUSED` with `EMBEDDINGS_INCOMPLETE`. An invalid handle is refused
  before any of this, and a `lexical` search never contacts Ollama.

## Variables

| Variable | Default | What it is |
|---|---|---|
| `OPS_MCP_READ_PORT` | 8081 | the loopback port it listens on |
| `MCP_READ_RESOURCE_URL` | `http://mcp-read:8081/mcp` | its token audience and resource URL, not the listen URL |
| `OPS_MCP_READ_URL` | `http://127.0.0.1:8081/mcp` | where the worker calls it |
| `OPS_ASSET_SIM_URL` | `http://127.0.0.1:8091` | where it calls asset-sim (T16) |
| `OPS_OLLAMA_URL` | `http://127.0.0.1:11434` | where it asks the embedding model for `/api/tags` and `/api/embed` (T18) |

## Looking at it

As the superuser on the dev database (after the owner's migration to 0009; `app.run_lease` arrives with 0007), a run's
handles (only hashes are stored):

```sql
SELECT ic.job_id, j.type, j.done_at, ic.server, ic.azp, ic.fence, l.fence AS lease_fence, l.lease_until,
       ic.expires_at, ic.revoked_at
FROM app.invocation_context ic JOIN app.jobs j ON j.id = ic.job_id JOIN app.run_lease l ON l.run_id = ic.run_id
WHERE ic.run_id = '<run>' ORDER BY ic.created_at;
SELECT state FROM app.runs WHERE run_id = '<run>';
```

## When something looks wrong

- **The worker logs "retrieval failed" and fails the run**: the call was refused. A 400 or 401 means a deployment
  mismatch (the client's protocol version, the token's audience or client); an `INVALID_HANDLE` envelope means the
  handle no longer fits its run (the lease lapsed or moved to another worker, the job finished, the run moved on).
  Use the query above; the server says nothing more on purpose.
- **mcp-read will not start**: read the message. "predates this service" is the missing revision; "signing keys
  unavailable" is the realm; "secret file kc_client_secret_ops_mcp_read is missing or unreadable" is `OPS_SECRETS_DIR`.
- **Every asset tool answers `UNAVAILABLE`**: asset-sim is down or not at `OPS_ASSET_SIM_URL` (`scripts/skeleton.py
  status`), or it answers 401 to mcp-read's token (its log shows it), or the realm's token endpoint does not answer.
  The search answers `UNAVAILABLE` for the same reasons: it asks asset-sim for the run's type. Today the worker does
  not retry a failed read, even one marked `retryable`: while asset-sim is down, every investigation that reaches
  retrieval ends FAILED ("retrieval failed"); honouring `retryable` with a bounded re-queue is T20's. If the realm's
  `ops-mcp-read` client lost its `asset-sim` audience, asset-sim answers 403 instead, and the tools say
  `UPSTREAM_INVALID`.
- **Every `vector_exact` search answers `UNSUPPORTED_MODE`**: `data/embedding-pins.json` is missing, unreadable or
  malformed, or the installed `nomic-embed-text` is another build than the pin (`curl -s
  http://127.0.0.1:11434/api/tags` shows its digest). Do not edit the pin by hand: a model change is a re-embedding
  (`docs/retrieval.md`).
- **`vector_exact` answers `REFUSED` `EMBEDDINGS_INCOMPLETE`**: chunks were ingested and not embedded; run
  `uv run python scripts/skeleton.py embed` (dev database: the owner's step). Lexical searches are unaffected.
- **`vector_exact` answers `UNAVAILABLE`**: Ollama is not answering on `OPS_OLLAMA_URL` within the 10 seconds (or
  asset-sim is down, as for every search); the worker does not use vector mode today.
- **A handle in a log line** is a bug (SA:566): the live test `tests/e2e/test_mcp_read_t15_live.py` captures every
  record of the server, the SDK, uvicorn and the client at DEBUG, with no redaction filter, and fails if one holds the
  handle. Never run mcp-read with uvicorn's `trace` level: its message logger writes every request's headers, the
  handle and the bearer token included (`serve_app` pins `warning`).

## Not here yet

The worker's choice of vector mode (T20, T25), the worker's own asset reads and the evidence bundle (T20),
recording the status observation for the grant's freshness check (T21), TLS, container host names and the route
from a containerised mcp-read to Ollama (T30). The
worker's check of the tool list sees only what the SDK keeps: the SDK drops a tool whose `x-mcp-header` annotation is
invalid before the check runs, and a check on the raw list waits for T30.
mcp-write's door, with the same verifier rules, is `docs/runbooks/mcp-write.md` (T47).

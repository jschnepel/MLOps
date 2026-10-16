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

`python -m ops_mcp_read` (or `scripts/skeleton.py up`) needs the database at revision 0009: at start it refuses when
`app.test_clock` exists outside the test profile, and when `app._resolve_handle` lacks 0009's job binding ("…
predates this service; run scripts/skeleton.py migrate for this profile"). mcp-write makes the same check at its own
start. The dev database stays at 0005 until the owner migrates it. Readiness (`/health/ready`) needs the realm's
signing keys and the database.

| Variable | Default | What it is |
|---|---|---|
| `OPS_MCP_READ_PORT` | 8081 | the loopback port it listens on |
| `MCP_READ_RESOURCE_URL` | `http://mcp-read:8081/mcp` | its token audience and resource URL, not the listen URL |
| `OPS_MCP_READ_URL` | `http://127.0.0.1:8081/mcp` | where the worker calls it |

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
  unavailable" is the realm.
- **A handle in a log line** is a bug (SA:566): the live test `tests/e2e/test_mcp_read_t15_live.py` captures every
  record of the server, the SDK, uvicorn and the client at DEBUG, with no redaction filter, and fails if one holds the
  handle. Never run mcp-read with uvicorn's `trace` level: its message logger writes every request's headers, the
  handle and the bearer token included (`serve_app` pins `warning`).

## Not here yet

The asset tools and asset-sim (T16), the governed store and vector search (T17), TLS and container host names (T30).
mcp-write's door, with the same verifier rules, is `docs/runbooks/mcp-write.md` (T47).

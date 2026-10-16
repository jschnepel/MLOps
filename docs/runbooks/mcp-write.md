# mcp-write: the authenticated write server and its recovery tools (T47)

Who this is for: whoever runs mcp-write, calls it, or works out what happened to an incident a run asked for. The
design is AM-13, AM-15, AM-20.3 and AM-30 in `SPEC_AMENDMENTS.md`, BUILD_SPEC §10, §13 and §14, and Plan K
(`docs/superpowers/plans/2026-10-16-first-slice-k-mcp-write-recovery-tools.md`). What it is trusted for, and what is
not checked, is in `docs/threat-model.md`.

## What a call must carry

A POST to `http://127.0.0.1:8082/mcp` (Streamable HTTP, protocol revision 2026-07-28, stateless, JSON responses) is
checked in this order, as at mcp-read (`docs/runbooks/mcp-read.md`); the first failure decides the answer.

1. **`MCP-Protocol-Version: 2026-07-28`**, exactly once, or HTTP 400 with JSON-RPC `-32022` before authentication.
2. **The worker's access token**: RS256 from the realm's keys, the realm's `iss`, not expired, `aud` containing
   `MCP_WRITE_RESOURCE_URL` (default `http://mcp-write:8082/mcp`), `azp` the worker's client (`OPS_WORKLOAD_CLIENT_ID`,
   default `ops-worker`), a `sub` and the `typ` claim `Bearer` (`write_verifier`); `McpVerifier` refuses again a token
   whose `aud` lacks this server's URL before it stamps the resource. Any failure is HTTP 401 `invalid_token`.
3. **The SDK's checks**: `_meta` agrees with the header, the tool exists, and its one argument, `proposal_id`, is a
   UUID; any other argument is refused.
4. **`X-Ops-Invocation`**, the handle the worker minted for an `execute` or `recover` job, resolved with the token's
   `azp`: known hash, not revoked or expired, at the lease's fence under a live lease, its own run's open job, a write
   job type. Then the allowlist: the job type's tools and run states, and the attempt state the tool may be called in.

   | Job | Tool | Run states | Latest attempt state |
   |---|---|---|---|
   | `execute` | `create_incident` | APPROVED, EXECUTING | none, INTENT, SENT (a re-send), ABORT_REQUESTED (UNKNOWN) |
   | `recover` | `create_incident` | EXECUTING, OUTCOME_UNKNOWN, ESCALATED, ABANDONED_UNVERIFIED | INTENT |
   | `recover` | `get_incident_receipt` | the same | SENT, ABORT_REQUESTED, RESOLVED |
   | `recover` | `abort_incident` | the same | INTENT, SENT, ABORT_REQUESTED |

   An execute job is admitted at ABORT_REQUESTED so that its re-queue after a failure between the abort request and
   the record (a crash, a database error) is answered UNKNOWN with nothing sent, and the worker's `mark_unknown` parks
   the run in OUTCOME_UNKNOWN with a recover job; a refusal would close the job and leave the run EXECUTING with no
   job. Every refusal of a presented handle is the plain `INVALID_HANDLE` envelope ("invocation handle rejected"), never
   an action id. All three tools are listed to the worker, the only client that can authenticate here; the table is
   what keeps the recovery tools to recover jobs.

## What each tool does

Every definer call carries the raw handle and the token's `azp`; the fence and the binding are checked again inside
each one.

- **`create_incident`**: `grant_execution` (the §13 gate; a second call finds the run's one grant), then `mark_sent`
  under the runs lock, committed before the POST, for a first send and for the re-send of an attempt already SENT
  (after a lost reply) alike. `sent` or `already_sent` POSTs the approved bytes under the grant's action id; the
  destination's key answers, and `record_outcome` records it. `cancelled` or `expired` (five minutes after the grant,
  `app._dispatch_seconds()`) means nothing more is sent: the tool requests the abort, POSTs it and records what the
  destination answers, so an attempt never sent ends FAILED with `cancelled_before_send` or `expired`, and a SENT one
  with the receipt or `aborted_no_commit`. A recover job's re-send of a SENT attempt is refused `NOT_REDISPATCHABLE`.
  Once an abort was requested, the call sends nothing and answers UNKNOWN; the abort's own record decides.
- **`get_incident_receipt`**: the stored outcome once the attempt is RESOLVED; otherwise one GET of the action's key.
  A receipt for the grant's hash is recorded as SUCCEEDED, another hash as CONFLICT, a tombstone as FAILED_NO_COMMIT;
  a 404, a 429, a 503 or no answer is UNKNOWN and recorded by nobody. It never POSTs and creates nothing.
- **`abort_incident`**: `request_abort` chooses the reason under the runs lock (`cancelled_before_send` or `expired`
  for an attempt never sent, `deadline` after SENT once cancelled or past the deadline) and records ABORT_REQUESTED;
  before either it is refused `ABORT_NOT_DUE` (retryable). The abort POST then meets a fresh tombstone (FAILED), the
  receipt already there (SUCCEEDED) or another hash's receipt (CONFLICT); no answer is UNKNOWN.

Answers: `ok` only for SUCCEEDED; `outcome` with `data.action_id` for UNKNOWN, CONFLICT and FAILED_NO_COMMIT;
`error` for a refusal before any destination call (`INVALID_HANDLE`, `ABORT_NOT_DUE`, `STALE_RUN` for a recover job's
redispatch of a run that left EXECUTING, `NOT_REDISPATCHABLE` for its re-send of a SENT attempt, `GRANT_REFUSED` for a
gate refusal or another proposal's id,
`GRANT_DEFERRED` for a stale membership sync). Each tool call is one destination request with a 10 s timeout; retrying
an UNKNOWN is the worker's (T22).

## Starting it

`python -m ops_mcp_write` (or `scripts/skeleton.py up`) needs the database at revision 0010: at start it refuses when
`app.test_clock` exists outside the test profile, when `app.model_permit` is missing (0007), when `_resolve_handle`
lacks 0009's job binding, and when `app.request_abort(text, text, uuid)` lacks 0010's text ("… predates this service;
run scripts/skeleton.py migrate for this profile"). The dev database stays at 0005 until the owner migrates it.
Readiness (`/health/ready`) needs the realm's signing keys and the database.

Never downgrade past 0010 while any `ABORT_REQUESTED` attempt-state row exists: 0009's `mark_sent` would not honour it
and could mark SENT after an abort request. The downgrade is for tests only.

| Variable | Default | What it is |
|---|---|---|
| `OPS_MCP_WRITE_PORT` | 8082 | the loopback port it listens on |
| `MCP_WRITE_RESOURCE_URL` | `http://mcp-write:8082/mcp` | its token audience and resource URL, not the listen URL |
| `OPS_INCIDENT_SIM_URL` | `http://127.0.0.1:8090` | the destination it calls with its own `ops-mcp-write` token |
| `OPS_WORKLOAD_CLIENT_ID` | `ops-worker` | the only `azp` it accepts (the worker reads the same setting) |

## Looking at it

As the superuser on the dev database (after the owner's migration to 0010), a run's grant and its attempt history,
then the destination's key (on the `incident` database):

```sql
SELECT g.action_id, g.granted_at, s.seq, s.state, s.outcome, s.detail->>'reason' AS reason, s.at
FROM app.execution_grant g JOIN app.action_attempt_state s USING (action_id)
WHERE g.run_id = '<run>' ORDER BY s.seq;
SELECT state, reason FROM app.runs WHERE run_id = '<run>';
-- on the incident database:
SELECT state, reason, incident_id, decided_at FROM incident.action_key WHERE action_id = '<action>';
```

`uv run python scripts/skeleton.py keys` lists every destination key that no grant's hash matches (exit 1 if any).

## When something looks wrong

- **An UNKNOWN that stays UNKNOWN**: the attempt is SENT and the destination did not answer (or answered 404). Look
  at the key; until T22's recover handler runs, nothing retries it. Never resend under a new key.
- **`ABORT_NOT_DUE`**: the run is not cancelled and the grant is less than five minutes old; the abort is not allowed
  yet.
- **`STALE_RUN` on a recover job's `create_incident`**: the attempt was never sent and the run left EXECUTING
  (OUTCOME_UNKNOWN); redispatch from there is T22's. Nothing was sent.
- **mcp-write will not start**: "predates this service" names the missing revision; "signing keys unavailable" is
  the realm. A handle or a token in a log line is a bug; never run it with uvicorn's `trace` level.

## Not here yet

The worker's recover handler, the backoff, scheduled recover jobs, redispatch from OUTCOME_UNKNOWN and escalation
(T22); the dispatch deadline as a setting (T29); signed receipts (v1.1); network isolation from mcp-read (T30).

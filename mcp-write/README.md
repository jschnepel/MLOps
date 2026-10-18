# mcp-write

MCP server for the guarded write and recovery tools

## Owns
create_incident, receipt lookup (get_incident_receipt), abort (abort_incident)

## Trusts
The worker's workload access token with this server's audience; the seven functions `mcp_exec` may execute
(`current_time` and the six write-path functions); it is trusted for outcome truth (`docs/threat-model.md`)

## Never
Any read function; asset-sim; corpus text

## Runs (T08, T15, T47)

`python -m ops_mcp_write` on 127.0.0.1:8082 (`OPS_MCP_WRITE_PORT`), Streamable HTTP at `/mcp`. A POST without exactly
`MCP-Protocol-Version: 2026-07-28` is 400 before authentication (T15). Verifies `aud ∋ MCP_WRITE_RESOURCE_URL`, `azp`
= the worker's client (`OPS_WORKLOAD_CLIENT_ID`, default `ops-worker`) and the access token's `typ` (T47); resolves
`X-Ops-Invocation` for open `execute` and `recover` jobs, by job type, run state and attempt state (revisions 0009 and
0010, which it checks at start). Three tools: `create_incident` (grant → INTENT → SENT, committed before I/O → POST
incident-sim with the `ops-mcp-write` workload token → RESOLVED; a cancelled or expired attempt is aborted instead and
ends FAILED, or SUCCEEDED if a SENT attempt's receipt already stands; an execute job's re-send of a SENT attempt reuses
the action id, and its call after an abort request is UNKNOWN with nothing sent), and, for recover jobs only,
`get_incident_receipt` (one GET of the action's key; creates nothing) and `abort_incident` (`request_abort`, then one
abort POST). A lost or unclear answer is UNKNOWN, recorded by nobody here; the worker's recovery loop is T22's. See
`docs/runbooks/mcp-write.md`.

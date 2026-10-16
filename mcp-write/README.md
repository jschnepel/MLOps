# mcp-write

MCP server for the guarded write and recovery tools

## Owns
create_incident, receipt lookup, abort

## Trusts
Workload token with its audience; the six write-path functions

## Never
Any read function; asset-sim; corpus text

## Runs (T08, T15)

`python -m ops_mcp_write` on 127.0.0.1:8082 (`OPS_MCP_WRITE_PORT`), Streamable HTTP at `/mcp`. A POST without exactly
`MCP-Protocol-Version: 2026-07-28` is 400 before authentication (T15). Verifies `aud ∋ MCP_WRITE_RESOURCE_URL`, `azp ==
ops-worker`; resolves `X-Ops-Invocation` for `execute` jobs that are still open while the run is APPROVED or EXECUTING
(T15). One tool, `create_incident`: grant → INTENT → SENT (committed before I/O) → POST incident-sim with the
`ops-mcp-write` workload token → RESOLVED. A replay while the run is still APPROVED or EXECUTING (the re-queue after a
transport failure) re-sends under the same action id and the destination's key answers; once the outcome is recorded,
any replay is refused `INVALID_HANDLE` before the grant (T15). A transport failure records OUTCOME_UNKNOWN
(reconciliation: T22). The verifier's T15 hardening and the recovery tools arrive with T47.

# mcp-write

MCP server for the guarded write and recovery tools

## Owns
create_incident, receipt lookup, abort

## Trusts
Workload token with its audience; the six write-path functions

## Never
Any read function; asset-sim; corpus text

## Runs (T08)

`python -m ops_mcp_write` on 127.0.0.1:8082 (`OPS_MCP_WRITE_PORT`), Streamable HTTP at `/mcp`. Verifies
`aud ∋ MCP_WRITE_RESOURCE_URL`, `azp == ops-worker`; resolves `X-Ops-Invocation` for `execute` jobs. One tool,
`create_incident`: grant → INTENT → SENT (committed before I/O) → POST incident-sim with the `ops-mcp-write` workload
token → RESOLVED. A replay returns the recorded outcome; a transport failure records OUTCOME_UNKNOWN (reconciliation: T22).

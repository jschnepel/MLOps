# mcp-read

MCP server for read tools only

## Owns
Asset status, alerts, procedure search

## Trusts
Workload token with its audience; definer functions `resolve_invocation`, `asset_scope`, `search_procedures_scoped`

## Never
Any write-path function; incident-sim

## Runs (T08)

`python -m ops_mcp_read` on 127.0.0.1:8081 (`OPS_MCP_READ_PORT`), Streamable HTTP at `/mcp`, protocol 2026-07-28,
stateless. Verifies `aud ∋ MCP_READ_RESOURCE_URL`, `azp == ops-worker`; resolves `X-Ops-Invocation` for `investigate`
jobs. One tool, `search_procedures` (lexical, fixture-backed until T17).

# mcp-read

MCP server for read tools only

## Owns
Asset status, alerts, procedure search

## Trusts
Workload token with its audience; definer functions `resolve_invocation`, `asset_scope`, `search_procedures_scoped`

## Never
Any write-path function; incident-sim

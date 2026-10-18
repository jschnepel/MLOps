# mcp-read

MCP server for read tools only

## Owns
Asset status, alerts, procedure search

## Trusts
The worker's workload access token with this server's audience; the definer functions `resolve_invocation` and
`search_procedures_scoped` (T17; `asset_scope` arrives with T16)

## Never
Any write-path function; incident-sim

## Runs (T08, T15)

`python -m ops_mcp_read` on 127.0.0.1:8081 (`OPS_MCP_READ_PORT`), Streamable HTTP at `/mcp`, protocol 2026-07-28,
stateless. A POST without exactly `MCP-Protocol-Version: 2026-07-28` is 400 before authentication. Verifies
`aud ∋ MCP_READ_RESOURCE_URL`, `azp` = the worker's client (`OPS_WORKLOAD_CLIENT_ID`, default `ops-worker`) and the
access token's `typ`; resolves `X-Ops-Invocation` for read
jobs whose run is in one of the job type's states, and only for the handle's own run's open job (revision 0009, which
it checks at start, with 0011's corpus function). One tool, `search_procedures` (lexical, over the governed corpus
through `search_procedures_scoped`, T17). See
`docs/runbooks/mcp-read.md`.

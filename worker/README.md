# worker

Run-lease worker: LangGraph orchestrator, LangChain draft node, MCP client

## Owns
Leases, the graph, drafting, MCP calls under handles

## Trusts
Its lease and `runs`; never model output

## Never
Writes decisions, grants, attempts, events; marks SUCCEEDED; reaches either sim

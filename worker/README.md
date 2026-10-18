# worker

Run-lease worker: LangGraph orchestrator, LangChain draft node, MCP client

## Owns
Leases, the graph, drafting, MCP calls under handles

## Trusts
Its lease and `runs`; never model output

## Never
Writes decisions, grants, attempts, events; marks SUCCEEDED; reaches either sim

## Runs (T08)

`python -m ops_worker`: polls `app.jobs` every 0.5 s (`FOR UPDATE SKIP LOCKED`), health on 127.0.0.1:8070
(`OPS_WORKER_HEALTH_PORT`). `investigate`: read tool on mcp-read → fake draft (`MODEL_MODE=fake`, the only route until
T19) → frozen proposal → AWAITING_APPROVAL. `execute`: `create_incident` on mcp-write. One `ops-worker` token carries
both MCP audiences; one handle per call. Lease, fence, heartbeat and LangGraph: T13/T20.

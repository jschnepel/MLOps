# worker

Run-lease worker: LangGraph orchestrator, LangChain draft node, MCP client

## Owns
Leases, the graph, drafting, MCP calls under handles

## Trusts
Its lease and `runs`; never model output

## Never
Writes decisions, grants, attempts, events; marks SUCCEEDED; reaches either sim

## Runs (T08, T13, T14)

`python -m ops_worker`: polls `app.jobs` every 0.5 s and claims a job together with its run's lease (`FOR UPDATE SKIP
LOCKED`, then the lease `FOR UPDATE NOWAIT`; a busy run's job is deferred behind the lease), health on 127.0.0.1:8070
(`OPS_WORKER_HEALTH_PORT`). Every unit it commits for a run is fenced by the lease; a heartbeat thread with its own
connection renews the lease while the event loop is alive and the job is within its compute budget, and cancels the
job's MCP or model call in flight when renewal fails; the job's final unit closes the job, releases the lease and
makes the run's deferred jobs due at once (T14). Polling is the v1 wake mechanism; a job it consumed without moving
its run is re-armed by the sweeper (`docs/runbooks/events-and-outbox.md`).
`investigate`: read tool on mcp-read → fake draft under the model permit (`MODEL_MODE=fake`, the only route until
T19) → frozen proposal → AWAITING_APPROVAL. `execute`: `create_incident` on mcp-write.
One token of the worker's client (`OPS_WORKLOAD_CLIENT_ID`, default `ops-worker`, the one setting both MCP servers'
verifiers read too, T47) carries both MCP audiences; one handle per call, bound to the lease's fence and to the client
id the tokens are issued to (T15). Settings:
`OPS_LEASE_SECONDS` (30), `OPS_HEARTBEAT_SECONDS` (10), `OPS_LOOP_STALL_SECONDS` (28), `OPS_COMPUTE_BUDGET_SECONDS`
(90); see `docs/runbooks/leases.md`. LangGraph: T20.

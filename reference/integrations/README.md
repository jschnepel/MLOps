# Optional integrations — not verified in this authoring environment

The Python package registry was unreachable. The MCP and LangGraph dependencies
could not be installed, so these examples were syntax-checked, not executed.
Do not count their tests as passing if the SDK is missing.

The MCP code targets the official SDK **v2** (`MCPServer`, `Client`). Do not mix it
with `FastMCP` / `ClientSession` examples intended for SDK v1. See the versioned
source notes in docs/SOURCES.md. Resolve exact dependencies and commit a lockfile
before promoting this integration.

## Install and test

```bash
python -m pip install -e '.[web,test,integrations]'
python -m pytest -o addopts="" tests/integration -q
```

The default pytest command explicitly ignores `tests/integration`; this command
must run as a separate required gate when the integration milestone is enabled.
It must fail, not silently pass, if required packages or services are unavailable.

## LangGraph

Create the graph with `build_graph(service, authenticated_requester, checkpointer)`.
For the local example use `SqliteSaver` in its context manager. In the target
worker use `PostgresSaver`, initialized by a controlled migration job, not on every
request. Set `configurable.thread_id` to the run UUID. One graph execution owns a
run at a time. The API first commits an authorized clarification/decision, then
enqueues a graph wake-up with `Command(resume={"event_id": "..."})`. The graph
ignores the signal's content as authorization and rereads authoritative state.

Do not call the synchronous graph directly from an async API event loop. The target
uses a separate leased worker. Current reference HTTP endpoints remain synchronous
and do not wire this graph automatically.

## MCP

`build_mcp` requires an identity resolver supplied by an authenticated host. Never
resolve identity from an `actor_id`, `team`, `approved` or `role` model argument.
The included contract test uses an in-process fixed identity ONLY as a test fixture.
There is deliberately no unauthenticated public server launcher.

Target transport: Streamable HTTP on an internal service. Implement and test OAuth
resource-server validation (issuer, audience, signature, expiry, scopes), approved
client/workload identity, and per-run user authorization before deploying. Do not
forward browser access tokens to a different audience. The MCP host owns its ASGI
lifespan; a mounted app's lifespan does not start automatically.

The production worker's MCP adapter must validate the returned structured content,
capabilities, tool names/schema hashes, error flags, size limits and timeouts. Tool
metadata is not an authorization source. SDK unit tests do not establish network
transport, token validation or interoperability with an external MCP host.

## Ollama

`operations_copilot.models.OllamaModel` implements the documented local `/api/chat`
structured-output request and validates the result. It has not been run against an
actual model here. Configure `MODEL_MODE=ollama` and an explicit locally installed
`OLLAMA_MODEL`. There is no cloud fallback or arbitrary endpoint URL. Do not claim
model quality using the deterministic test double's results.

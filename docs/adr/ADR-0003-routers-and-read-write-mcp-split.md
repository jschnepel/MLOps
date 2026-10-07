# ADR-0003: Explicit routers and a read/write MCP split

- **Status:** Accepted 2026-10-07
- **Amends:** SPEC_AMENDMENTS AM-01, AM-12, AM-13, AM-15, AM-20, AM-31; adds AM-16
- **Deciders:** repository owner

## Context

The project's purpose is to demonstrate four things to a technical reader: least privilege, routers, an orchestrator and MCP servers. After the 1.3.3 revision, least privilege and the orchestrator were specified in detail but not surfaced anywhere a reader could find them; routing existed only implicitly (admission rules in §7, the `resolve_context` node in §8, the `MODEL_MODE` switch); and a single MCP server hosted both read tools and the guarded write, which hid the privilege story behind one process and one database role.

## Decision

1. **Routers become named components with enumerable route tables** (AM-16):
   - an **admission router** in the API with routes `investigate`, `clarification_reply`, `status_question`, `readonly_answer`, `clarify`, `reject`;
   - a **graph router** node (`route_request`) in the orchestrator whose conditional edges come only from a route table in `core/`;
   - a **model router** (the `DraftGenerator` factory) that selects `fake`, `qwen3:8b` or a future model by configuration, records the choice in the run manifest, and never falls back silently.
   - Rule for all three: deterministic rules decide; model classification is at most a hint; unroutable input becomes a clarification or a 422 and never creates work (R129, R130).
2. **The MCP server splits into `mcp-read` and `mcp-write`.** Each has its own Keycloak client, token audience, database role and function set. `mcp_read` can execute only `resolve_invocation`, `asset_scope` and `search_procedures_scoped`; `mcp_exec` can execute only the write-path functions. Capability handles are bound to one server, so a read handle presented to mcp-write is rejected and vice versa (R131). Only mcp-write can reach incident-sim; only mcp-read can reach asset-sim.
3. **A showcase document** (`docs/ARCHITECTURE.md`) maps each of the four concepts to its components, the requirement IDs that prove it and the demo that shows it, and the README links to it.

## Consequences

- One more service (seven containers in the demo profile instead of six) and one more Keycloak client, role and audience. T15 builds mcp-read; the new T47 builds mcp-write.
- The worker holds two handle types and two base URLs. The walking skeleton (T08) runs both servers from the start, so the split is never retrofitted.
- Routing gains its own requirement and tests, which did not exist before; the route tables become the place to look when asking "what can this system do?".
- Nothing about authority changes: the final gate is still `grant_execution` inside the database, and the model still holds no credential and calls no tool.

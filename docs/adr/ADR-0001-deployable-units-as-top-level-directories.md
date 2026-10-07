# ADR-0001: Deployable units as top-level directories

- **Status:** Accepted, 2026-10-06
- **Amends:** BUILD_SPEC.md §5 (repository layout only)
- **Deciders:** repository owner

## Context

BUILD_SPEC §5 puts all code in one package, `src/operations_copilot/`, with services as sub-packages.

This is a portfolio project. Its main readers are interviewers, who should be able to open one directory and understand one running process: what it owns, what it trusts, and how it is tested.

BUILD_SPEC §3 also says that application-domain functions are not separate microservices. The deliberate network boundaries are MCP and the synthetic destination. The API and worker may share an image.

## Decision

Each independently deployed process gets its own top-level directory. Each has its own `pyproject.toml`, `Dockerfile`, entrypoint, `tests/` and a `README.md` stating ownership and trust:

```text
core/          shared library (uv workspace member): domain, application, adapters, contracts
api/           FastAPI: sessions, admission, decisions, SSE, health
worker/        run-lease worker: LangGraph graph, LangChain draft node, MCP client
mcp-read/      authenticated MCP server: read tools only
mcp-write/     authenticated MCP server: guarded write and recovery tools only
asset-sim/     synthetic asset/alert API
incident-sim/  synthetic incident destination with its own database
web/           React + TypeScript + Vite
```

- **`core/` is a library, not a service.** Every service imports domain rules from it. No domain logic is duplicated, and none is exposed over the network.
- **Network boundaries stay where §3 puts them:** browser → api, worker → mcp-read / mcp-write, mcp-read → asset-sim, mcp-write → incident-sim, worker → Ollama (ADR-0003).
- **Images:** the API and worker may share a base image.
- **Python packaging:** one `uv` workspace and one `uv.lock` at the repository root.
- **Cross-service tests:** end-to-end tests that span services live in `tests/e2e/` at the root.
- **The reference implementation** moves unchanged into `reference/` in task T04: `src/operations_copilot/`, its `tests/`, `pyproject.toml`, `Makefile`, `Dockerfile`, `compose.yaml`, `integrations/`, `scripts/init_demo.py` and `scripts/check_reference.sh`. It is not a uv workspace member, and root lint, type-check and tests exclude it. A hash remap keeps `verify_handoff.py --reference-code` passing, and the reference stays runnable there. Task T07 traces all 58 reference tests to port, replace or drop in `reference/TRACEABILITY.md`.

## Consequences

- Interviewers can read one service at a time, and each Dockerfile builds only its member plus `core/`.
- There is a risk of `core/` turning into a dumping ground. To mitigate it, `core/` keeps the sub-packages `domain/`, `application/`, `adapters/` and `contracts/`, and services contain only wiring, transport and process lifecycle.
- The two synthetic services (`asset-sim/`, `incident-sim/`) are separate on purpose. The destination needs an independent database and credentials (§14). The read API does not.

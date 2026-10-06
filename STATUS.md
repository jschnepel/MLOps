# Implementation status — 2026-10-06 handoff

Authority: `BUILD_SPEC.md`. Detailed observed checks: `reports/handoff/VERIFICATION.md`.

| Capability | Delivered state | Required target work |
|---|---|---|
| Local domain/API control reference | 58 deterministic tests rerun successfully | Preserve behavior through target adapters and real-service tests |
| Lost-response recovery example | CLI rerun; one synthetic destination incident | Test real network, process/pod failure, delayed visibility and retained-receipt restore |
| Identity | Seeded localhost bearer-token fixtures | Keycloak/OIDC, secure sessions, current authorization and scoped workload identity |
| Persistence | Two independent local SQLite stores | PostgreSQL, migrations, restricted roles/RLS, jobs/fences/checkpoints/outbox |
| Model | Deterministic substitute; historical direct Ollama adapter | Actual LangChain ChatOllama integration and measured model quality |
| LangGraph | Historical integration example only | Wire persistent/fenced graph, durable pauses and versioned recovery |
| MCP | Historical SDK example only | Authenticated remote server/client, invocation context, restricted receipt lookup |
| Retrieval | Small historical synthetic fixture | Governed ingestion, lexical baseline, pgvector comparison, revocation tests |
| UI | Native HTML/JS reference; syntax checks are not browser evidence | React, actual browser/accessibility tests, authorized SSE and manual fallback |
| Docker / Kubernetes | Inherited unexecuted reference templates | Build/scan target images, deploy/test Helm/kind/CNI, true pod recovery |
| Observability / CI | Planned stack and disabled CI template | Actual redacted telemetry, dashboards, trust-separated required gates |
| Evaluation / restore / upgrades | Explicit specification and scenario cards | Actual baselines, independent holdout, rehearsals and measured results |
| AI build specification / task map / schemas / charts | Included as handoff artifacts | The builder must implement the target; schema checks do not establish runtime correctness |
| Slack / cloud | Disabled, optional | Owner-approved integration after version 1 gates |

## Known inherited limitations

The original optional dependency bounds and example APIs must be resolved/locked and tested, not treated as a complete compatible environment. `tests/integration` is excluded by the historical default pytest configuration. `integrations/mcp_tools.py` contains a historical comment pointing to an absent `database/target_schema.sql`; use BUILD_SPEC section 6 and implement the target migrations rather than assuming that file exists. Historical README/docs paths have been archived; active instructions start at the root specification.

The inherited source/test/integration bytes are retained unchanged in this handoff and can be checked against `provenance/reference-code-hashes.json`. New documents and schema examples do not silently upgrade their implementation status. The target requires actual acceptance evidence before any feature is promoted to complete.

## Update — 2026-10-06 planning session (OPS-BUILD-1.1)

- The handoff was imported unmodified (git commit 1) and amended by `SPEC_AMENDMENTS.md`, ADR-0001 (per-service directories) and ADR-0002 (v1 scope cut).
- The adversarial review is at `docs/reviews/handoff-review-2026-10-06.md`.
- **No target capability is implemented yet.** Every acceptance requirement (R001–R100) remains `NOT_RUN`.
- **Reference baseline on the owner's Windows machine:**
  - recovery CLI reproduced;
  - 58-test suite **not yet reproduced** (FastAPI missing; T01).
- **Known v1 limitations, by design (ADR-0002):**
  - single-writer checkpoint profile (R021 open);
  - no Kubernetes deployment claim;
  - owner-authored rather than third-party holdout.

## Update — OPS-BUILD-1.2 (2026-10-06)

- The plan was revised after a second adversarial review (`docs/reviews/plan-review-2026-10-06.md`).
- Still **no target capability implemented**. All of R001–R117 are `NOT_RUN`.
- Schemas, examples and fixtures still describe 1.0 until T07.

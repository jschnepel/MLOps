# Technical source register

Checked September 30, 2026. These are documentation references, not proof that every described component was executed in the authoring environment. Version-bound examples must be contract-tested against the locked dependencies. Project-specific decisions and acceptance thresholds are proposals, not claims made by these sources.

## S01 — LangGraph persistence

https://docs.langchain.com/oss/python/langgraph/persistence

Use: Persistent checkpoints and threads; choose a durable checkpointer.

## S02 — LangGraph interrupts

https://docs.langchain.com/oss/python/langgraph/interrupts

Use: Pause/resume, node replay and idempotent side effects.

## S03 — Official MCP Python SDK

https://github.com/modelcontextprotocol/python-sdk

Use: Current stable SDK v2; do not mix v1 FastMCP examples with v2 MCPServer/Client APIs.

## S04 — MCP ASGI deployment

https://py.sdk.modelcontextprotocol.io/run/asgi/

Use: Streamable HTTP application hosting and lifespan ownership.

## S05 — MCP security best practices

https://modelcontextprotocol.io/docs/2026-07-28/tutorials/security/security_best_practices

Use: Audience validation, token passthrough and other protocol security boundaries.

## S06 — OWASP transaction authorization

https://cheatsheetseries.owasp.org/cheatsheets/Transaction_Authorization_Cheat_Sheet.html

Use: Bind authorization to the transaction, revalidate at execution, invalidate changed payloads.

## S07 — PostgreSQL row security

https://www.postgresql.org/docs/current/ddl-rowsecurity.html

Use: RLS behavior and owner/superuser/BYPASSRLS caveats.

## S08 — PostgreSQL SELECT

https://www.postgresql.org/docs/current/sql-select.html

Use: FOR UPDATE SKIP LOCKED semantics for queue-like consumers.

## S09 — pgvector

https://github.com/pgvector/pgvector

Use: Vector storage and similarity search in PostgreSQL.

## S10 — Ollama structured outputs

https://docs.ollama.com/capabilities/structured-outputs

Use: JSON-schema requests and output validation.

## S11 — Ollama thinking

https://docs.ollama.com/capabilities/thinking

Use: Model-dependent emitted thinking output; not an authority source.

## S12 — Reasoning-model faithfulness research

https://www.anthropic.com/research/reasoning-models-dont-say-think

Use: Visible reasoning can omit influences; not a complete internal audit.

## S13 — Agent evaluation guidance

https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents

Use: Repeated trials, isolated scenarios, outcome checks and calibrated graders.

## S14 — Server-sent events

https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events

Use: Server-to-browser updates; use separate HTTP requests for user messages.

## S15 — OpenTelemetry GenAI conventions

https://opentelemetry.io/docs/specs/semconv/gen-ai/

Use: Version the telemetry convention used; collect bounded, redacted metadata.

## S16 — Docker build practices

https://docs.docker.com/build/building/best-practices/

Use: Multi-stage builds, image pinning and least-privileged runtime.

## S17 — Kubernetes probes

https://kubernetes.io/docs/concepts/workloads/pods/probes/

Use: Startup/readiness/liveness have different meanings.

## S18 — Kubernetes NetworkPolicy

https://kubernetes.io/docs/concepts/services-networking/network-policies/

Use: Enforcement requires a supporting networking implementation.

## S19 — kind quick start

https://kind.sigs.k8s.io/docs/user/quick-start/

Use: Local Kubernetes cluster workflow.

## S20 — Helm charts

https://helm.sh/docs/topics/charts/

Use: Package related Kubernetes resources.

## S21 — GitHub Actions secure use

https://docs.github.com/en/actions/reference/security/secure-use

Use: Pin full commit SHAs, minimize privileges and separate untrusted code from credentials.

## S22 — GitHub artifact attestations

https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations

Use: Build provenance and SBOM attachments are not correctness guarantees.

## S23 — Slack interactions

https://docs.slack.dev/interactivity/handling-user-interaction/

Use: Acknowledge interactions within three seconds; run long operations separately.

## S24 — Slack request verification

https://docs.slack.dev/authentication/verifying-requests-from-slack/

Use: Verify signed request bodies and timestamp replay window.

## S25 — MCP client elicitation

https://modelcontextprotocol.io/specification/latest/client/elicitation

Use: Capability-negotiated user clarification; not approval or credential collection.

## S26 — OWASP unbounded consumption

https://genai.owasp.org/llmrisk/llm102025-unbounded-consumption/

Use: Bound work, duration, quotas and concurrency.

## S27 — MCP Python client API

https://py.sdk.modelcontextprotocol.io/client/

Use: Client discovery/calls and structured results.

## S28 — MCP Python authorization

https://py.sdk.modelcontextprotocol.io/run/authorization/

Use: Authenticated hosting and resource-server integration.

# Copy into your coding AI

```text
Read AGENTS.md, BUILD_SPEC.md, SPEC_AMENDMENTS.md, STATUS.md, handoff/tasks.json
and SESSION_STATE.md. BUILD_SPEC.md as amended by SPEC_AMENDMENTS.md is the
implementation contract; the amendments win wherever they conflict, and AM-00
lists the superseded 1.0 passages. Archived notes and diagrams cannot override it.
Inspect the existing source and preserve its tested control invariants. Start
at the earliest dependency-satisfied task in handoff/tasks.json and work in
small tested slices; read each task's review_notes before starting it.

Use the acceptance matrix to connect each requirement to code, tests and actual
evidence. V1 scope is M00-M14 (ADR-0002): real LangGraph orchestration,
LangChain model integration, authenticated MCP tools, PostgreSQL durability,
web communication, independent approval, idempotent incident execution and
Docker Compose deployment. Kubernetes/Helm is optional (M15) and must not be
claimed as tested in v1. Retrieve evidence before final drafting. Do not
fabricate reasoning, test results, model output, credentials, performance
measurements or completed integrations.

Keep STATUS.md and SESSION_STATE.md current. Ask only for genuine unresolved
external inputs or approvals. Do not publish, push, create cloud resources, spend
money, send real notifications, change system settings or delete data without
explicit authorization.
```

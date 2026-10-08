# Operations Copilot

**An evidence-backed incident assistant with controlled tool use, independent approval, and recoverable execution.**

> **Status: walking skeleton runs locally (T08); hardening in progress** ([runbook](docs/runbooks/walking-skeleton.md)). Read [STATUS.md](STATUS.md) before interpreting any capability below as built. The capabilities described are **targets**.

Start with **[START_HERE.md](START_HERE.md)**. The implementation contract is [BUILD_SPEC.md](BUILD_SPEC.md) as amended by **[SPEC_AMENDMENTS.md](SPEC_AMENDMENTS.md)**.

**What exists today:** the delivered local reference (single process, SQLite, deterministic model substitute).
- Its 58 tests passed in the handoff author's Linux environment ([reports/handoff/VERIFICATION.md](reports/handoff/VERIFICATION.md)).
- Re-running them on the owner's machine is task T01.
- Its recovery CLI has been run locally.

## What this demonstrates

| Concept | Where | Target tests |
|---|---|---|
| **Least privilege** | Column-level DB grants per role; MCP servers with no table access; a function-only final gate; capability handles; token audiences | R084, R124, R128, R106, R131, R026, R027, R085 |
| **Routers** | An admission router, a graph router node and a model router, each with an enumerable route table; model output can only downgrade a route | R129, R130 |
| **Orchestrator** | One explicit LangGraph graph: evidence before drafting, durable pauses, synchronous checkpoints, never the authority | R038, R042, R108, R091 |
| **MCP servers** | `mcp-read` (asset status, alerts, procedure search) and `mcp-write` (guarded incident write and recovery), disjoint functions, disjoint handles | R025–R031, R131 |

The full map, with diagrams and the demo that shows each, is **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

**Target v1 stack:**
- **Services:** FastAPI, a LangGraph worker with LangChain + local Ollama (`qwen3:8b`), and two authenticated MCP servers (read, write).
- **Data:** PostgreSQL/pgvector, plus an independent synthetic incident destination.
- **Identity and UI:** Keycloak, a React workspace.
- **Deployment:** Docker Compose.

**Ordering and authority:**
- Evidence retrieval precedes final drafting.
- Approval and actual destination receipts, not model text, control actions and result claims.

**Limits stated up front** ([ADR-0002](docs/adr/ADR-0002-v1-scope-cut.md), AM-10, AM-13, AM-50): Kubernetes/Helm is optional and not claimed for v1; one worker replica runs (multi-replica checkpoint fencing is deferred); the evaluation holdout is owner-authored, and with about 25 cases only differences of roughly 30 points are detectable; an action with a lost response can take up to 5 minutes to be declared failed; an escalated action may be acknowledged as unverified by an operator, and the destination may still hold the incident. Nothing is ever undone automatically.

[Ordered backlog](handoff/BUILD_BACKLOG.md) · [ADRs](docs/adr/) · [Adversarial reviews](docs/reviews/) · [Problems found and what changed](docs/PROJECT_HISTORY.md) · [Target schemas](schemas/README.md) · [Stage diagrams](docs/diagrams/README.md)

## Dependency-free local recovery reference

```bash
PYTHONPATH=src python -m operations_copilot.cli
```

The CLI walks through:
1. clarification;
2. independent approval;
3. a destination commit whose response is lost;
4. receipt reconciliation;
5. exactly one synthetic incident.

This is not real-model inference and not a container or cluster failure test.

## Scope

- Synthetic data only.
- None of: real equipment actuation, automatic privilege changes, generic shell/SQL/network tools, hidden cloud fallback, or unapproved external actions.
- Cloud and Slack are optional later milestones.

License: MIT ([LICENSE](LICENSE)).

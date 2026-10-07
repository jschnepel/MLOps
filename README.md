# Operations Copilot

**An evidence-backed incident assistant with controlled tool use, independent approval, and recoverable execution.**

> **Status: planning complete, implementation not started.** Read [STATUS.md](STATUS.md) before interpreting any capability below as built. The capabilities described are **targets**.

Start with **[START_HERE.md](START_HERE.md)**. The implementation contract is [BUILD_SPEC.md](BUILD_SPEC.md) as amended by **[SPEC_AMENDMENTS.md](SPEC_AMENDMENTS.md)**.

**What exists today:** the delivered local reference (single process, SQLite, deterministic model substitute).
- Its 58 tests passed in the handoff author's Linux environment ([reports/handoff/VERIFICATION.md](reports/handoff/VERIFICATION.md)).
- Re-running them on the owner's machine is task T01.
- Its recovery CLI has been run locally.

**Target v1 stack:**
- **Services:** FastAPI, a LangGraph worker with LangChain + local Ollama (`qwen3:8b`), and an authenticated MCP server.
- **Data:** PostgreSQL/pgvector, plus an independent synthetic incident destination.
- **Identity and UI:** Keycloak, a React workspace.
- **Deployment:** Docker Compose.

**Ordering and authority:**
- Evidence retrieval precedes final drafting.
- Approval and actual destination receipts, not model text, control actions and result claims.

Kubernetes/Helm is an optional later extension and is **not** claimed for v1 ([ADR-0002](docs/adr/ADR-0002-v1-scope-cut.md)).

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

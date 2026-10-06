# Operations Copilot — AI implementation handoff

**An evidence-backed incident assistant with controlled tool use, independent approval, and recoverable execution.**

Start with **[START_HERE.md](START_HERE.md)**. The complete authoritative implementation contract is **[BUILD_SPEC.md](BUILD_SPEC.md)**. No previous conversation is required.

This package contains a tested local reference, not the completed target production-oriented application. Read **[STATUS.md](STATUS.md)** before interpreting feature claims. Actual handoff checks and limitations are in **[reports/handoff/VERIFICATION.md](reports/handoff/VERIFICATION.md)**.

The target uses FastAPI, LangGraph, LangChain, Ollama, authenticated MCP tools, PostgreSQL/pgvector, React, Docker, and tested Kubernetes/Helm deployment. Evidence retrieval precedes final drafting. Approval and actual destination receipts—not model text—control actions and result claims.

[Ordered backlog](handoff/BUILD_BACKLOG.md) · [Acceptance checklist](handoff/ACCEPTANCE.md) · [Target schemas](schemas/README.md) · [Stage diagrams](docs/diagrams/README.md)

## Dependency-free local recovery reference

```bash
PYTHONPATH=src python -m operations_copilot.cli
```

Expected behavior: clarification → independent approval → destination commit with lost response → receipt reconciliation → one synthetic incident. This is not real-model inference or a Kubernetes failure test.

## Scope

Synthetic data only. No real equipment actuation, automatic privilege changes, generic shell/SQL/network tools, hidden cloud fallback, or unapproved external actions. Cloud and Slack are optional later milestones. Public license and publication require an explicit owner decision; no public license is silently assigned by this handoff.

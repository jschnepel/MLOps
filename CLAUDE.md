# Operations Copilot

Read and follow `AGENTS.md`. Then read the complete `BUILD_SPEC.md` and `SPEC_AMENDMENTS.md`. The amendments win wherever the two conflict. Both coding-agent entry points use the same implementation contract; there is no separate Claude-specific architecture.

Continue from `SESSION_STATE.md` and the earliest incomplete dependency-satisfied task in `handoff/tasks.json` (v1.1 dependency graph). Record actual test/evidence status and preserve the authority, approval, idempotency and no-unapproved-external-action boundaries.

Each deployable service lives in its own top-level directory, with shared code in `core/` (ADR-0001). The v1 scope is M00–M14; M15 is optional (ADR-0002).

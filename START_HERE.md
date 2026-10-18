# Start here — Operations Copilot

**One contract (BUILD_SPEC.md as amended by SPEC_AMENDMENTS.md), a runnable local reference, and an ordered task graph.**

This repository began as an AI build handoff (OPS-BUILD-1.0; the delivered package is preserved byte-for-byte as `provenance/handoff-1.0.zip`). It was then amended after six adversarial reviews (`docs/reviews/`); `docs/PROJECT_HISTORY.md` lists the problems found and what changed. No earlier conversation is needed to understand it.

## Give the coding AI this instruction

Use the prompt in [`handoff/KICKOFF_PROMPT.md`](handoff/KICKOFF_PROMPT.md). In short:
- **Contract:** `BUILD_SPEC.md` as amended by `SPEC_AMENDMENTS.md`. The amendments win wherever they conflict, and AM-00 lists the superseded passages.
- **Where to start:** the earliest dependency-satisfied task in `handoff/tasks.json`, after reading its `review_notes`.
- **Scope:** v1 is M00–M14. Kubernetes/Helm is optional (M15) and is not claimed as tested.

`CLAUDE.md` and `AGENTS.md` point to the same contract.

## What is in the repository

| Location | Purpose |
|---|---|
| `BUILD_SPEC.md` | Original 1.0 product/architecture contract (amended; see the banner at its top) |
| `SPEC_AMENDMENTS.md` | Current amendments (overrides BUILD_SPEC); AM-00 lists superseded text |
| `docs/adr/` | ADR-0001 (one top-level directory per service), ADR-0002 (v1 scope cut, one-replica profile), ADR-0003 (routers and the read/write MCP split) |
| `docs/ARCHITECTURE.md` | The showcase map: least privilege, routers, orchestrator, MCP servers → components, requirements, demos |
| `docs/reviews/` | The six adversarial review rounds and their findings |
| `handoff/tasks.json` | 16 milestones and 47 tasks as a dependency graph, with review notes |
| `handoff/acceptance-matrix.json` | 131 requirements, each with an owning task and a suggested test path |
| `reference/` | Original runnable local reference (moved by T42; byte-identical to the delivered package, enforced by `verify_handoff.py --reference-code`) |
| `core/`, `api/`, `worker/`, `mcp-read/`, `mcp-write/`, `asset-sim/`, `incident-sim/` | uv workspace members, one top-level directory per service (ADR-0001) |
| `tests/plan_a/` | Workspace tests run by `scripts/check.py` |
| `schemas/` | Target JSON schemas and positive/negative examples (still 1.0 until T45; see AM-80) |
| `handoff/prompts/` | Sealed v1 prompt starters (hashes in AM-31) |
| `data/handoff-fixtures/`, `evals/` | Synthetic fixtures and development scenario cards (no holdout is stored in the repo) |
| `docs/diagrams/` | Six corrected stage charts |
| `provenance/`, `docs/archive/`, `reports/historical/` | Provenance and historical context only |

## Quick start

```bash
uv sync --locked
uv run python scripts/check.py
```

The workspace root depends on all seven members, so a plain `uv sync` / `uv run` installs them; `check.py` runs ruff, mypy and pytest and prints `CHECK: GREEN` or `CHECK: RED`.

## First local checks

```bash
# Package structure, JSON, task graph, fixtures, source syntax (standard library only).
python scripts/verify_handoff.py

# Reference bytes unchanged (the whole reference/ tree) and the 1.0 manifest verified against provenance/handoff-1.0.zip.
python scripts/verify_handoff.py --reference-code --manifest

# Dependency-free synthetic recovery demonstration.
cd reference && PYTHONPATH=src python -m operations_copilot.cli
```

To run the reference test suite, use an isolated venv **outside** the repository and install without `-e`. The exact commands are in `SESSION_STATE.md` ("Exact next step"; the T01 procedure, run from `reference/`).

The package checker is **not** an acceptance runner. Schema-valid examples are not proofs of permissions or semantic truth.

## Completion boundary

No target capability is implemented yet (see `STATUS.md`). Four things are owner-specific inputs, and the AI must not invent them:
- hardware and model choice;
- nonlocal secrets;
- external service consent;
- publication approval.

The license is MIT.

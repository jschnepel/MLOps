# Start here — Operations Copilot AI build handoff

**One package, one authoritative build specification, a runnable local reference.**

Extract this archive into a new working directory. Open the inner `operations-copilot/` folder in the coding AI’s workspace. No earlier conversation, external Drive document, cloud account, or prior download is needed to understand the project.

## Give the coding AI this instruction

```text
Read AGENTS.md, BUILD_SPEC.md, STATUS.md, handoff/tasks.json and SESSION_STATE.md.
BUILD_SPEC.md is the single authoritative implementation contract; archived notes
and diagrams cannot override it. Inspect the existing source and preserve its
tested control invariants. Start at M00, reproduce the reference tests and recovery
demo, then implement the earliest dependency-satisfied task in small tested slices.

Use the acceptance matrix to connect each requirement to code, tests and actual
evidence. Include real LangGraph orchestration, LangChain model integration,
authenticated MCP tools, PostgreSQL durability, web communication, independent
approval, idempotent incident execution, Docker and tested Kubernetes deployment.
Retrieve evidence before final drafting. Do not fabricate reasoning, test results,
model output, credentials, performance measurements or completed integrations.

Keep STATUS.md and SESSION_STATE.md current. Ask only for genuine unresolved
external inputs or approvals. Do not publish, push, create cloud resources, spend
money, send real notifications or delete data without explicit authorization.
Begin with the baseline and environment checks, then make the first tested change.
```

The same prompt is in `handoff/KICKOFF_PROMPT.md`. `CLAUDE.md` and `AGENTS.md` point to the same contract rather than maintaining separate project instructions.

## What is in the package

| Location | Purpose |
|---|---|
| `BUILD_SPEC.md` | Complete product/architecture/rationale, true runtime order, contracts, security, jobs, retrieval, approvals, recovery, UI, evaluation, deployment and agent workflow |
| `src/`, `tests/`, `integrations/` | Original runnable local reference and explicitly unverified integration examples |
| `handoff/tasks.json` | 16 ordered milestones and 32 task slices, with dependencies |
| `handoff/acceptance-matrix.json` | 80 concrete requirements linked to target tests and expected evidence |
| `schemas/` | 11 target JSON schemas and positive/negative examples; not already-wired API endpoints |
| `handoff/prompts/` | Versioned runtime prompt starters and review/handoff instructions |
| `data/handoff-fixtures/` | Eight authored synthetic source documents and fixed asset/alert observations |
| `evals/handoff-development/` | 32 development scenario cards; no fabricated holdout or benchmark scores |
| `docs/diagrams/` | Six corrected left-to-right stage charts in PNG, SVG and Mermaid |
| `reports/handoff/` | Checks actually rerun during assembly and their limitations |
| `provenance/` | Original source archive and reference-code hashes |
| `docs/archive/`, `reports/historical/` | Historical context only; not build authority |

## First local checks

The following commands run from the repository root. Python 3.12+ runs the inherited reference; the target is Python 3.13-compatible.

```bash
# Standard-library checks of package structure, JSON, task graph, fixtures and source syntax.
python scripts/verify_handoff.py

# Verify the exact delivered bytes before changing anything.
python scripts/verify_handoff.py --manifest --reference-code

# Optional additional schema/positive-negative example validation:
# requires jsonschema in the local tooling environment; missing dependency is not a pass.
python scripts/verify_handoff.py --contracts

# Dependency-free synthetic recovery demonstration.
PYTHONPATH=src python -m operations_copilot.cli

# Reference tests: requires the web/test dependencies already available or resolved in M01.
python -m pytest -q
```

PowerShell equivalent for the CLI:

```powershell
$env:PYTHONPATH = "src"
python -m operations_copilot.cli
```

Do not install old reference pins blindly into an existing environment. Create an isolated environment, inspect `pyproject.toml`, and perform the reviewed dependency/lock step if the test requirements are missing. The inherited default pytest suite excludes SDK tests; the target requires explicit integration suites. Use `python -m pytest -o addopts="" tests/integration -q` only after the selected SDKs are installed and compatibility is verified.

The package checker is **not** a production acceptance runner. Schema-valid examples are not proofs of permissions or semantic truth. The manifest describes this handoff snapshot; intentional implementation edits will change its checksums. Record future release manifests separately.

## Completion boundary

The target build is not complete. Real model, authenticated MCP, distributed persistence, browser, Docker, Kubernetes, evaluation, restore and upgrade gates are separate implementation tasks. Hardware/model choice, nonlocal secrets, external service consent, public licensing and publication approval remain owner-specific inputs; the AI must not invent them.

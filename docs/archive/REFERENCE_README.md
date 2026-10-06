# Operations Copilot

**Evidence-backed incident investigation with human approval and recoverable execution.**

An implementation kit for a production-oriented LLM portfolio project. It includes a working local control reference, optional integration examples, deployment templates, and a full implementation roadmap with design rationale.

**Read [STATUS.md](STATUS.md) first.** This is not a completed production deployment. The default application uses a deterministic model substitute, SQLite, and direct synthetic tool calls. It does not silently claim to run LangGraph, MCP, PostgreSQL, or an actual LLM.

## Flagship workflow

An operator requests an investigation of synthetic Asset A17. The application asks for missing context, retrieves a synthetic procedure and asset information, prepares an evidence-referenced incident proposal, and waits for an independent approver. Only the approved proposal can be submitted. A lost response after submission is reconciled against the synthetic destination rather than blindly retried.

**No real equipment control, employer information, arbitrary shell access, or unrestricted network tools.**

## Start with the dependency-free demonstration

Python 3.12 or newer; the supplied reference was tested using Python 3.13.5. From the extracted repository root:

```bash
PYTHONPATH=src python -m operations_copilot.cli
```

Expected state progression (incident IDs and timestamps vary):

```text
AWAITING_INPUT
AWAITING_APPROVAL
OUTCOME_UNKNOWN
SUCCEEDED
Destination incident count: 1
```

The CLI uses temporary synthetic databases. It intentionally loses the response after the destination commits and constructs a new service instance before reconciliation. This is a reference recovery test, not a Kubernetes pod-failure experiment.

PowerShell equivalent:

```powershell
$env:PYTHONPATH = "src"
python -m operations_copilot.cli
```

## Run the tests and local web application

Dependency installation requires an online Python package registry. The supplied direct dependency pins reflect the authoring environment; the fully resolved dependency lock is a required next milestone.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[web,test]'
python -m pytest -q
python scripts/init_demo.py
python -m uvicorn operations_copilot.api:create_app --factory --host 127.0.0.1 --port 8000
```

On PowerShell activate with `.venv\Scripts\Activate.ps1`. WSL2 can use the Bash commands.

Open `http://127.0.0.1:8000`. The initialization command creates private credentials in `runtime/demo_credentials.json`. Use **alex** to request an investigation and **sam** to independently approve it. **lee** is an alpha-team reader; **riley** and **jordan** belong to beta. The credential field clears after connection and the browser keeps the token in memory only.

A simple walkthrough: connect as alex; request A17 with a blank time range; supply 24 hours; retrieve and draft; connect as sam; review the exact proposal; approve; submit. The same run can be loaded in a second browser tab with a different identity. Use the CLI/tests for deliberate response-loss injection; the web API does not expose that fault switch.

Keep this reference on localhost. Demo tokens are not an OIDC login implementation and have no expiration or refresh flow. Do not commit `runtime/`, expose the application publicly, or store real information in it. The OpenAPI schema is available at `/openapi.json`; no CDN-hosted interactive documentation is enabled.

## Real model and SDK integrations

The local Ollama adapter, MCP v2 server example, and LangGraph graph example are supplied but **were not executed here**. See [integrations/README.md](integrations/README.md). The default test run intentionally excludes external-SDK tests; they are a separate required milestone, not skipped evidence of success.

## What is included

| Path | Purpose |
|---|---|
| `src/operations_copilot/` | Tested state transitions, synthetic destination, model adapters, local API, native browser interface. |
| `tests/` | Deterministic domain and HTTP tests; separately gated SDK contracts. |
| `integrations/` | LangGraph and official MCP SDK v2 integration examples. |
| `Dockerfile`, `compose.yaml` | Unbuilt, local single-instance reference deployment definitions. |
| `deploy/helm/`, `deploy/kind*.yaml` | Unexecuted reference Kubernetes packaging and cluster definitions. |
| `docs/IMPLEMENTATION.md` | Full target architecture, rationale, contracts, and staged implementation plan. |
| `docs/BACKLOG.md` | Ordered engineering tasks and acceptance gates. |
| `docs/DECISIONS.md` | Architecture decisions, trade-offs, and reconsideration triggers. |
| `docs/SECURITY.md`, `docs/RUNBOOKS.md` | Threat model and operating procedures to implement and test. |
| `docs/EVALUATION.md`, `evals/` | Benchmark design and explicitly development-only scenario seeds. |
| `docs/DEPLOYMENT.md`, `docs/RELEASE.md` | Docker/Kubernetes evolution and release gates. |
| `reports/` | Actual authoring-time checks and their limitations. |
| `docs/SOURCES.md` | Primary technical references, checked September 30, 2026. |

## Current verification

The delivered reference passes **58 deterministic domain/API tests**. Python syntax and browser JavaScript syntax were checked. The recovery CLI was run successfully. See `reports/VERIFICATION.md` and `reports/reference-tests.xml` for evidence and environment details.

Not verified here: actual model inference, MCP/LangGraph SDK execution, distributed PostgreSQL workers, container builds, Kubernetes installation, visual browser behavior, cloud deployment, real-model quality, load limits, or complete production security.

## Publishing

Create a new repository only after reading `docs/RELEASE.md`, choosing an explicit project license, and scanning for secrets. A disabled CI template is provided; it must not be advertised as a passing GitHub Actions pipeline. Do not upload model weights, private runtime files, or fabricated evaluation scores. Label screenshots and demos with the actual model mode.

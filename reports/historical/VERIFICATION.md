# Verification report — Operations Copilot implementation kit

Date: September 30, 2026.

## Checks actually performed

| Check | Result | Evidence / limitation |
|---|---|---|
| Deterministic domain/API test suite | **58 passed** | `reference-tests.xml` and `pytest-output.txt`; latest run 0.62 seconds. This is test runtime, not model or application latency. |
| Lost-response reference CLI | Passed | `reference-demo.txt`: destination commits, response is lost, service reconstructed, reconciliation confirms one incident. No real network partition or pod kill was performed. |
| Python syntax compilation | Passed | `python -m compileall -q src integrations tests scripts`; does not resolve or exercise external SDK imports. |
| Browser JavaScript syntax | Passed | `node --check src/operations_copilot/web/app.js`; not a browser interaction test. |
| Plain Compose/kind/Helm metadata YAML and scenario JSONL parsing | Passed | Only non-templated YAML parsed. Helm Go-template rendering and Kubernetes admission were not run. |
| Python wheel build and packaged source/static contents | Passed | Offline `pip wheel --no-deps --no-build-isolation --no-index`; `wheel-build.txt`. Uses preinstalled build tools; not proof of clean dependency resolution. |
| Local HTTP server health | Passed | Temporary localhost Uvicorn server returned live status. Subsequently stopped. |
| Browser visual/interactive verification | **Blocked** | Browser navigation was denied by the environment (`ERR_BLOCKED_BY_ADMINISTRATOR`). No screenshots or visual success claims. |
| Fresh ZIP extraction test | Passed | Extracted to a separate directory; 58 tests passed again and CLI confirmed one destination incident. See `archive-check.txt`. |

## Not executed or not implemented

Online dependency resolution was unavailable. MCP and LangGraph SDKs could not be installed, so their separately gated tests were not executed. No actual Ollama model was run. Docker, Helm and kubectl were unavailable; no container build, cluster installation, CNI enforcement or cloud deployment was performed. PostgreSQL workers, OIDC, React migration, telemetry backend, Slack, real-model evaluations, capacity tests, restore and upgrade experiments remain implementation milestones.

The default pytest configuration explicitly excludes `tests/integration`. Once the SDK milestone is enabled, run `python -m pytest -o addopts="" tests/integration -q` as a separate required gate. An unavailable dependency is not a passing integration.

## Environment

Python: 3.13.5

Packages: fastapi 0.128.2, uvicorn 0.48.0, pydantic 2.13.4, httpx 0.28.1, pytest 9.0.2

Node: v22.16.0

## Interpretation

These checks support a working local reference for typed requests, application permission checks, human decisions, proposal integrity, destination idempotency and recovery behavior. They do not establish model quality, a complete production system, remote MCP security, global exactly-once behavior, or Kubernetes availability.

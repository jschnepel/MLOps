# Reproducibility, CI and publication

## Dependency reality

The reference ran against preinstalled Python packages. Online package installation was unavailable. The archive therefore includes tested direct pins for the web/test extras and major-version bounds for unexecuted SDK examples, but no fabricated resolved lockfile. The first implementation task is to resolve exact versions, review compatibility/security and commit a reproducible lock with artifact hashes.

One possible online resolution procedure, after choosing and pinning the lock tool itself:

```bash
uv pip compile pyproject.toml --extra web --extra test --generate-hashes -o requirements.lock
uv pip compile pyproject.toml --extra web --extra test --extra integrations --extra postgres --generate-hashes -o requirements-integration.lock
```

These commands were not executed successfully here. Check the installed tool's documented syntax and verify a clean install with `pip install --require-hashes -r ...`. Lock build dependencies as well as runtime dependencies before claiming a reproducible build. Update the Docker build to consume locked artifacts; the supplied Dockerfile does not yet do so. A project wheel install must not resolve an unconstrained dependency behind the lock.

## CI template

`deploy/ci/ci.yml.template` is intentionally not an active GitHub workflow. Before copying it to `.github/workflows/ci.yml`, resolve the lock, replace action tags with verified full commit SHAs from the official actions, review permissions and run the pipeline. Never fabricate SHA pins. GitHub recommends immutable SHA references and careful handling of untrusted workflow input. [S21]

Implement required checks in this order: syntax/lint/type -> deterministic domain/API -> PostgreSQL isolation/migrations -> actual MCP/LangGraph contracts -> real-model development regressions -> container build/scan -> Kubernetes/network/failure smoke -> protected release evaluation. Missing dependencies should fail the relevant required gate, not be converted into a skip that looks green.

For real-model GPU testing, do not execute arbitrary fork code on a secret-bearing self-hosted runner. Use isolated ephemeral runners or explicitly trusted workflows. Separate untrusted pull-request tests from release credentials and held-out evaluation material.

## Release manifest

Record source commit, image digest, dependency-lock hash, prompt/workflow/tool-schema versions, model/digest/configuration, corpus and evaluation-set version, report hashes, migration compatibility, environment, approval and rollback target. Verify provenance against the expected source/workflow/commit. SBOM and build attestations are provenance evidence, not proof of safe or correct behavior. [S22]

## Repository publication checklist

Choose a code license and an appropriate synthetic-data license; the kit does not silently choose legal terms for you. Check model and dependency redistribution requirements. Do not upload model weights or third-party documentation dumps. Scan the entire candidate commit for secrets, private records, generated runtime credentials and large artifacts. Keep actual model mode visible in recordings.

Publish tested results, architecture decisions, limitations, setup, recovery instructions and a short demonstration. Each claimed feature should link to code and a test or report. Do not use a passing badge for an inactive workflow. Do not fill a résumé metric with an unmeasured percentage.

## Release blocking conditions

Any observed unauthorized write, wrong-team evidence disclosure, duplicate destination incident, unexplained test exclusion, failed restore/upgrade gate, secret leak, or unacceptable measured quality regression blocks promotion. The response is to fix or clearly reduce scope, not relabel the issue as production-ready.

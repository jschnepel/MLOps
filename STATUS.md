# Implementation status — 2026-10-06 handoff

Authority: `BUILD_SPEC.md`. Detailed observed checks: `reports/handoff/VERIFICATION.md`.

| Capability | Delivered state | Required target work |
|---|---|---|
| Local domain/API control reference | 58 deterministic tests rerun successfully | Preserve behavior through target adapters and real-service tests |
| Lost-response recovery example | CLI rerun; one synthetic destination incident | Test real network, process/pod failure, delayed visibility and retained-receipt restore |
| Identity | Seeded localhost bearer-token fixtures | Keycloak/OIDC, secure sessions, current authorization and scoped workload identity |
| Persistence | Two independent local SQLite stores | PostgreSQL, migrations, restricted roles/RLS, jobs/fences/checkpoints/outbox |
| Model | Deterministic substitute; historical direct Ollama adapter | Actual LangChain ChatOllama integration and measured model quality |
| LangGraph | Historical integration example only | Wire persistent/fenced graph, durable pauses and versioned recovery |
| MCP | Historical SDK example only | Authenticated remote server/client, invocation context, restricted receipt lookup |
| Retrieval | Small historical synthetic fixture | Governed ingestion, lexical baseline, pgvector comparison, revocation tests |
| UI | Native HTML/JS reference; syntax checks are not browser evidence | React, actual browser/accessibility tests, authorized SSE and manual fallback |
| Docker / Kubernetes | Inherited unexecuted reference templates | Build/scan target images, deploy/test Helm/kind/CNI, true pod recovery |
| Observability / CI | Planned stack and disabled CI template | Actual redacted telemetry, dashboards, trust-separated required gates |
| Evaluation / restore / upgrades | Explicit specification and scenario cards | Actual baselines, independent holdout, rehearsals and measured results |
| AI build specification / task map / schemas / charts | Included as handoff artifacts | The builder must implement the target; schema checks do not establish runtime correctness |
| Slack / cloud | Disabled, optional | Owner-approved integration after version 1 gates |

## Known inherited limitations

The original optional dependency bounds and example APIs must be resolved/locked and tested, not treated as a complete compatible environment. `tests/integration` is excluded by the historical default pytest configuration. `integrations/mcp_tools.py` contains a historical comment pointing to an absent `database/target_schema.sql`; use BUILD_SPEC section 6 and implement the target migrations rather than assuming that file exists. Historical README/docs paths have been archived; active instructions start at the root specification.

The inherited source/test/integration bytes are retained unchanged in this handoff and can be checked against `provenance/reference-code-hashes.json`. New documents and schema examples do not silently upgrade their implementation status. The target requires actual acceptance evidence before any feature is promoted to complete.

## Update — 2026-10-06 planning session (OPS-BUILD-1.1)

- The handoff was imported unmodified (git commit 1) and amended by `SPEC_AMENDMENTS.md`, ADR-0001 (per-service directories) and ADR-0002 (v1 scope cut).
- The adversarial review is at `docs/reviews/handoff-review-2026-10-06.md`.
- **No target capability is implemented yet.** Every acceptance requirement (R001–R100) remains `NOT_RUN`.
- **Reference baseline on the owner's Windows machine:**
  - recovery CLI reproduced;
  - 58-test suite **not yet reproduced** (FastAPI missing; T01).
- **Known v1 limitations, by design (ADR-0002):**
  - single-writer checkpoint profile (R021 open);
  - no Kubernetes deployment claim;
  - owner-authored rather than third-party holdout.

## Update — OPS-BUILD-1.2 (2026-10-06)

- The plan was revised after a second adversarial review (`docs/reviews/plan-review-2026-10-06.md`).
- Still **no target capability implemented**. All of R001–R117 are `NOT_RUN`.
- Schemas, examples and fixtures still describe 1.0 until T07.

## Update — OPS-BUILD-1.3 (2026-10-06)

- The round-3 blocking items are resolved in the plan (`docs/reviews/plan-review-r3-2026-10-06.md`). LATER items are attached to their owning tasks.
- Still **no target capability implemented**. All of R001–R123 are `NOT_RUN`.
- Next: an implementation plan for T01–T08, then build. From here, review happens per slice against code and tests.

## Update — OPS-BUILD-1.3.2 (2026-10-06)

- Round-5 blocking and high items are fixed in the plan. README, START_HERE and KICKOFF_PROMPT no longer claim tested Kubernetes.
- Still **no target capability implemented**. All of R001–R126 are `NOT_RUN`.

## Update — OPS-BUILD-1.3.3 (2026-10-06)

- AM-20 rewritten (grants, function contracts, RLS policies, test clock); round-6 items fixed; `provenance/handoff-1.0.zip` committed; `docs/PROJECT_HISTORY.md` added.
- Still **no target capability implemented**. All of R001–R128 are `NOT_RUN`.

## Update — OPS-BUILD-1.3.4 (2026-10-07)

- Routers named (AM-16), MCP split into read and write servers (ADR-0003), `docs/ARCHITECTURE.md` added as the showcase map.
- Still **no target capability implemented**. All of R001–R131 are `NOT_RUN`.

## Update — OPS-BUILD-1.3.5 (2026-10-07)

- Round-7 high and blocking items fixed; showcase and history corrected for truthfulness.
- Still **no target capability implemented**. All of R001–R131 are `NOT_RUN`.

## Update — OPS-BUILD-1.3.6 and Plan A (2026-10-07)

- Round-8 regressions fixed; Plan A (T01, T03, T02, T42, T04, T06) rewritten after a builder dry-run found it unexecutable.
- Still **no target capability implemented**. All of R001–R131 are `NOT_RUN`.

## Update — Plan A executed (2026-10-07, branch `plan-a`)

- Plan A (T01, T03, T02, T42, T04, T06) executed on branch `plan-a` (commits a638801..HEAD), followed by a final-review fix wave (five Important findings fixed).
- `uv run python scripts/check.py` is `CHECK: GREEN`: ruff, ruff format, mypy on the seven members, and pytest `54 passed, 1 skipped`. The one skip is `tests/plan_a/test_seal.py` (owner has not sealed the holdout yet).
- `python -I scripts/verify_handoff.py --reference-code --manifest` passes, including the whole-tree check of `reference/` against `provenance/handoff-1.0.zip`.
- **Pending owner inputs:**
  - T03 step 9: author the holdout off-machine, seal it into `evals/holdout.sha256`, and record the hash outside this repo;
  - T02: the live `qwen3:8b` probe run, after the seal (the probe refuses to run without it);
  - T06 step 7: `gh auth login`, choose visibility, create the remote, push; the first CI run is R103's evidence.
- Still **no target capability implemented**. R001–R131 remain `NOT_RUN` in the acceptance matrix. Partially evidenced by Plan A (per the plan's coverage notes): R001 (reference baseline reproduced), R071 (holdout schema and seal procedure; the seal itself is pending), R081 partial (probe built; live run pending), R101 partial (seed IDs only), R103 up to the owner's push, R121.

## Update — Plan B executed (2026-10-08, branch `plan-b`)

- Plan B (T05, T43, T44) executed on branch `plan-b` on top of `plan-a`, each task by a fresh implementer and gated by a fresh reviewer (one fix round each); the plan itself went through three adversarial rounds, two with real-Docker dry runs (`docs/reviews/plan-review-b-2026-10-08.md`).
- `uv sync --locked` then `uv run python scripts/check.py` is `CHECK: GREEN`: pytest `89 passed, 11 skipped`. Skips: the owner-pending holdout seal (1), one POSIX-only permissions test (Windows), and nine live tests that run only with `OPS_LIVE=1` against the dev profile (they passed: 2 stack, 4 + 2 Keycloak, 1 Ollama bridge; redacted evidence under `reports/bootstrap/`).
- `uv run python scripts/bootstrap_dev.py up` brings up PostgreSQL+pgvector and Keycloak 26.8.0 (realm `ops-dev`, five personas with seeded IDs, four workload clients with exact audiences, a `view-users` service account) with every port on `127.0.0.1` and secrets as files outside git; the bootstrap admin is removed after import.
- Plan A's scripts, tests and workflow were re-commented against `docs/CODE_COMMENTS.md` (commits c25ee89, 32bf85d).
- **Pending owner inputs:** T03 holdout seal → T02 live probe; T06 push → first CI run URL; **T44 step 10:** apply `docs/runbooks/ollama-network.md` step A (bind Ollama to loopback at User scope), verify, fill the attestation table, decide on the proposed AM-31 errata.
- Still **no target capability implemented**. R001–R131 remain `NOT_RUN`. Newly evidenced in part: R101 (dev environment and network boundaries: loopback bindings, file secrets, host/container routes; the Ollama exposure half awaits the owner), R102 (Keycloak topology: `aud`/`azp`/`sub`/`iss` asserted live).

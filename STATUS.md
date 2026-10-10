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
  - T06 step 7: the remote `jschnepel/MLOps` exists and `main`/`plan-a` were pushed on 2026-10-07; the first CI run's URL is R103's evidence.
- Still **no target capability implemented**. R001–R131 remain `NOT_RUN` in the acceptance matrix. Partially evidenced by Plan A (per the plan's coverage notes): R001 (reference baseline reproduced), R071 (holdout schema and seal procedure; the seal itself is pending), R081 partial (probe built; live run pending), R101 partial (seed IDs only), R103 up to the owner's push, R121.

## Update — Plan B executed (2026-10-08, branch `plan-b`)

- Plan B (T05, T43, T44) executed on branch `plan-b` (`b98140f..HEAD` as of 2026-10-08, including the final-review fix wave) on top of `plan-a`, each task by a fresh implementer and gated by a fresh reviewer (one fix round each); the plan itself went through three adversarial rounds, two with real-Docker dry runs (`docs/reviews/plan-review-b-2026-10-08.md`).
- `uv sync --locked` then `uv run python scripts/check.py` is `CHECK: GREEN`: pytest `92 passed, 11 skipped`. Skips: the owner-pending holdout seal (1), one POSIX-only permissions test (Windows), and nine live tests that run only with `OPS_LIVE=1` against the dev profile (they passed: 2 stack, 4 + 2 Keycloak, 1 Ollama bridge; redacted evidence under `reports/bootstrap/`).
- `uv run python scripts/bootstrap_dev.py up` brings up PostgreSQL+pgvector and Keycloak 26.8.0 (realm `ops-dev`, five personas with seeded IDs, four workload clients with exact audiences, a `view-users` service account) with every port on `127.0.0.1` and secrets as files outside git; the bootstrap admin is removed after import.
- Plan A's scripts, tests and workflow were re-commented against `docs/CODE_COMMENTS.md` (commits c25ee89, 32bf85d).
- **Pending owner inputs:** T03 holdout seal → T02 live probe; push `plan-b` and open the PR → first CI run URL (the remote exists; `main` and `plan-a` were pushed on 2026-10-07); **T44 step 10:** apply `docs/runbooks/ollama-network.md` step A (bind Ollama to loopback at User scope), verify, fill the attestation table, decide on the proposed AM-31 errata.
- Still **no target capability implemented**. R001–R131 remain `NOT_RUN`. Newly evidenced in part: R101 (dev environment and network boundaries: loopback bindings, file secrets, host/container routes; the Ollama exposure half awaits the owner), R102 (Keycloak topology: `aud`/`azp`/`sub`/`iss` asserted live).

## Update — Plan C executed (2026-10-08, branch `plan-c`)

- Plan C (T07, T45, T46) executed on branch `plan-c` (`36c1007..843f365`, plus plan commits 36eb767 and 28fe2a6) on top of `plan-b`, each task by a fresh implementer and gated by a fresh reviewer; six of the eight implementation tasks needed a fix round (Tasks 5 and 8 did not).
- `uv run python scripts/check.py` is `CHECK: GREEN`: pytest `381 passed, 30 skipped`. `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts` passes: 26 JSON Schema documents, 34 accepted and 53 negative examples (each failing for its stated reason), governed files LF-only. The generated tree is 25 schemas, 87 examples and `index.json` 1.3.3. The conformance test runs 110 cases, 91 passed and 19 skipped with stated reasons (tool-result, evidence, route, job and tool inputs wait for the tasks that consume them); 22 of them mutate every valid example of a modelled schema and require the schema and the code to agree.
- **Evidenced locally** (`RECORDED_LOCALLY` / `IMPLEMENTED_LOCALLY_VERIFIED` in the acceptance matrix; the core library or contract exists and the listed tests verify it, with no running target capability): R004 (authority fields rejected at every depth), R005 (canonical JSON v1, NFC-normalised, same bytes for equivalent payloads), R082 (the transition table, 44 rows; the "disallowed transitions logged" half was `TODO(T09)` in `states.py` until Plan E), R083 (no envelope that contradicts its outcome), R104 (schemas, examples and fixtures aligned and generated from one source), R123 (all 58 reference tests traced). R120 stays `NOT_RUN`: the rule (`revision_allowed`) exists, but its 409 `SLOT_OCCUPIED` is T21's.
- The nine rulings made while modelling the spec are proposed errata, listed in `SESSION_STATE.md`; the owner decides, and the spec text stays authoritative until then.
- Still **no target capability implemented**: there is no database, service, worker or tool in this slice. The other 125 requirements remain `NOT_RUN`.

## Update — Plan D executed (2026-10-08, branch `plan-d`)

- Plan D (T08, the walking skeleton) executed on branch `plan-d` (`8136ee6..d7b6359`, on top of `plan-c`), each task by a fresh implementer and gated by a fresh reviewer; seven of the eight implementation tasks needed a fix round (only Task 1 did not; Task 7 had two).
- `PYTHONUTF8=1 uv run python scripts/check.py` is `CHECK: GREEN`: pytest `457 passed, 44 skipped` (the live tests run only with `OPS_LIVE=1`). The live suite `OPS_LIVE=1 PYTHONUTF8=1 uv run python -m pytest tests/e2e` passes `14 passed` against the running dev profile.
- **Evidenced** (acceptance matrix `RECORDED_LOCALLY_LIVE` / `IMPLEMENTED_LOCALLY_VERIFIED`): R105. One run crosses api, worker, mcp-read, mcp-write and incident-sim over real HTTP with real Keycloak tokens, ends `SUCCEEDED` with nine events, survives a replay that returns the same action id, and every wrong token is refused (`reports/skeleton/r105-walking-skeleton.txt`).
- The five application processes (incident-sim :8090, mcp-read :8081, mcp-write :8082, api :8000, worker :8070 health only) are **host processes** started by `scripts/skeleton.py up` until T30 containerises them; every shortcut is a debt line in `SESSION_STATE.md` with its owning task.
- Still no hardened capability: R106 onward (roles, RLS, definer functions) wait for T09; the other requirements remain `NOT_RUN`.

## Update — Plan E executed (2026-10-08, branch `plan-e`)

- Plan E (T09 roles, RLS and definer functions; T10 incident-sim `action_key` hardening) executed on branch `plan-e` (`3fb9645..5fbb272`, on top of `plan-d`), each task by a fresh implementer and gated by a fresh reviewer. The plan is `docs/superpowers/plans/2026-10-08-first-slice-e-roles-rls-definers.md`; the review record is `docs/reviews/plan-review-e-2026-10-08.md`.
- `PYTHONUTF8=1 uv run python scripts/check.py` is `CHECK: GREEN`: pytest `530 passed, 82 skipped` (the live tests run only with `OPS_LIVE=1`). `PYTHONUTF8=1 uv run python scripts/check.py --profile test` is `CHECK: GREEN`: pytest `591 passed, 21 skipped`, the live suite included (it runs against the per-session `ops_test` and `incident_test` databases and needs the dev stack up). `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts` exits 0.
- **Evidenced** (acceptance matrix `RECORDED_LOCALLY_LIVE` / `IMPLEMENTED_LOCALLY_VERIFIED`): R006, R007, R008, R009, R084, R106, R124, R126, R128 (T09) and R010, R047, R096, R098 (T10); R082's logged half is done (`transition_run` raises `OC004` and the wrapper logs at WARNING). Every process now connects as its own AM-20.1 login role, the R105 walking skeleton re-runs under those roles, and the destination refuses the persona and worker tokens with 403 (`reports/skeleton/r105-walking-skeleton.txt`).
- The final whole-branch review (0 Critical, 3 Important, 12 Minor) was fixed in one wave (`e8e71a7`): after SENT every mapped refusal answers UNKNOWN (an unmapped database error is still a tool error the worker retries); the transition rows, event types and grantee roles of revisions 0002/0003 are frozen literals checked against the live Python; a live test migrates three Plan-D runs written at revision 1 (R006's old-schema half). R098's evidence is unit-level (`RECORDED_LOCALLY`). Ten of the twelve minors were fixed in the wave; the zero-orphan `keys` case and the connect helper for the three servers are open items. Record: `docs/reviews/plan-e-final-review-2026-10-08.md`.
- R122 stays `NOT_RUN`, deferred to T20 (the checkpoint dependency is not locked). The other deferrals are parked in `SESSION_STATE.md` with their owning tasks.
- Still no hardened capability beyond these: sessions and admission (T11/T12), leases (T13) and the remaining requirements stay `NOT_RUN`.

## Update — Plan F executed (2026-10-09, branch `plan-f`)

- Plan F (T11 Keycloak login, server-side sessions, revocation and the membership sync) executed on branch `plan-f` (`0d1a892..ad3163f`, on top of `plan-e`; the close-out commit with the handoff records follows), each task by a fresh implementer and gated by a fresh reviewer. The plan is `docs/superpowers/plans/2026-10-08-first-slice-f-sessions-login-sync.md`; the review record is `docs/reviews/plan-review-f-2026-10-09.md`.
- `PYTHONUTF8=1 uv run python scripts/check.py` is `CHECK: GREEN`: pytest `663 passed, 95 skipped` (the live tests run only with `OPS_LIVE=1`), with no warnings in the output. `PYTHONUTF8=1 uv run python scripts/check.py --profile test` is `CHECK: GREEN`: pytest `737 passed, 21 skipped`, the live suite included (it needs the dev stack up and no skeleton process running). `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts` exits 0.
- **Evidenced** (acceptance matrix `RECORDED_LOCALLY_LIVE` / `IMPLEMENTED_LOCALLY_VERIFIED`): R011, R012, R013 and R086 (T11). A browser login through the real Keycloak form opens a server-side session; mutations without the CSRF token or Origin are refused (403); an idle session expires (401); logout ends the provider session; a back-channel logout token revokes the sibling session once and a forged token is refused (400); a user disabled at Keycloak gets 401 on the decision route and the sweeper's membership sync follows within 60 s (`synced_after` 23-24 s; the sweeper re-stamp 25 s) (`reports/auth/t11-sessions-revocation.txt`). The walking skeleton re-runs with six processes, the sweeper being the sixth (`reports/skeleton/r105-walking-skeleton.txt`). authlib 1.8.0 and joserfc 1.7.5 are locked (AM-30's 1.8.0 holds).
- R086 is split: the admin-API half and the sync half are live; the grant-side block through a real `grant_execution` call lands with T21.
- The dev `ops` database is at revision 0005 (the owner ran `skeleton.py migrate` on 2026-10-09); all six processes were brought to ready and stopped against it. The shared dev realm already carries the Plan F clients.
- Deferred, each with its owner in `SESSION_STATE.md`: `Idempotency-Key` -> T12; the enabled check on revisions, cancel and manual proposals -> T21; the SSE identity recheck -> T27; telemetry redaction -> T28; the containerised back-channel URL and the demo realm -> T30; the purge of finished maintenance jobs -> T14. Nine errata (26-34) are proposed for the owner to decide.
- Still no hardened capability beyond these: admission (T12), leases (T13) and the remaining requirements stay `NOT_RUN`.

## Update — PRs and first CI (2026-10-09)

- PRs #1-#5 opened for the stack (plan-b -> main, plan-c -> plan-b, plan-d -> plan-c, plan-e -> plan-d, plan-f -> plan-e) with plan summaries from this file.
- The first five CI runs were `CHECK: RED` on a single ruff finding, EXE001 on `scripts/verify_handoff.py` (a shebang without the executable bit; ruff skips the rule on Windows, where every local check had run). Every test passed on the Linux runner (93, 382, 459, 531 and 680 passed; one more than locally, the POSIX-only permissions test). Fixed by a file-mode commit on `plan-b` cherry-picked onto the four branches above it; all five re-runs are green. First green run: https://github.com/jschnepel/MLOps/actions/runs/37962510516; the red one: https://github.com/jschnepel/MLOps/actions/runs/37962039002. Record: `reports/ci/t06-first-ci-runs.txt`.
- T06 is `DONE` and R103 is evidenced (`RECORDED_LOCALLY_LIVE`, on GitHub-hosted runners with the read-only token and no secrets). The push-to-main trigger fires with the first merge.

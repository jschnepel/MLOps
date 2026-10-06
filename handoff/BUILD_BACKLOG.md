# Ordered AI implementation backlog

Read BUILD_SPEC.md first. These tasks are planned; no future integration is marked complete.

## M00 — Baseline and environment

- [ ] **T01 Reproduce reference and inspect source** — Run the existing 58-test baseline and dependency-free recovery CLI. Record actual mode and capabilities. Dependencies: none.
- [ ] **T02 Inventory environment and preserve work** — Inspect git state, tool versions, installed model/hardware, filesystem and local-only boundaries. Record unresolved owner inputs. Dependencies: T01.

## M01 — Contracts and toolchain

- [ ] **T03 Resolve and lock compatible toolchains** — Create real locks and import/SDK compatibility report; add Ruff/mypy checks without deleting baseline tests. Dependencies: T01, T02.
- [ ] **T04 Implement reviewed contracts and canonical action representation** — Turn schemas into tested Pydantic contracts, enum transitions, canonicalization and application API/version rules. Dependencies: T03.

## M02 — PostgreSQL foundations

- [ ] **T05 Build real PostgreSQL migrations and restricted repositories** — Define application schema/constraints and runtime roles/RLS; test pooling and cross-tenant child references. Dependencies: T03, T04.
- [ ] **T06 Create independent synthetic destination persistence** — Implement destination schema and interfaces while preserving independent receipts; no shared assistant transaction assumption. Dependencies: T05.

## M03 — Identity and API

- [ ] **T07 Implement local Keycloak login and secure backend sessions** — OIDC/PKCE/session lifecycle/CSRF/current-membership checks and negative tests. Dependencies: T05, T06.
- [ ] **T08 Implement versioned API with durable admission** — Messages/runs/jobs/events commit before 202; scoped request idempotency, fixed interval and stale-version conflicts. Dependencies: T07.

## M04 — Jobs and persistence

- [ ] **T09 Implement durable leased workers and fencing** — Job claim/heartbeat/sweeper, application and checkpoint transactional fence checks. Dependencies: T07, T08.
- [ ] **T10 Implement event journal, wake-up reconciliation and outbox** — Protect user-event to checkpoint handoff from lost wakeups; release leases on human waits. Dependencies: T09.

## M05 — Remote MCP

- [ ] **T11 Deploy authenticated MCP transport and per-run invocation contexts** — Official SDK remote host/client, workload audience and expiring lease-bound invocation handles. Dependencies: T09, T10.
- [ ] **T12 Implement controlled tool registry and independent network tests** — Read tools plus disabled-until-approved write boundary; restricted receipt lookup for reconciliation. Full approved execution closes in M08. Dependencies: T11.

## M06 — Evidence pipeline

- [ ] **T13 Implement versioned source ingestion and lexical baseline** — Authored fixtures, approved/effective sections, source hashes, current access and source revocation tests. Dependencies: T11, T12.
- [ ] **T14 Add exact vector retrieval and comparison report** — Select installed/approved embedding model, record dimensions/index version, compare same development queries. Dependencies: T13.

## M07 — LangChain and LangGraph

- [ ] **T15 Implement real LangChain ChatOllama draft adapter** — Versioned prompts, explicit mode, supported structured output, bounded validation/repair, real inference evidence. Dependencies: T13, T14.
- [ ] **T16 Wire explicit persistent LangGraph workflow** — Run retrieval before final generation; typed clarification, persisted interrupt/resume, deterministic policy branching. Dependencies: T15.

## M08 — Review and outcomes

- [ ] **T17 Implement immutable independent-review lifecycle and final grant** — Lock/version authority, exact approval hash/revision, freshness and cancellation race ordering. Dependencies: T15, T16.
- [ ] **T18 Implement stable-key destination execution and reconciliation** — Use actual MCP path; same-key atomic commit, response-loss/hash-conflict/delayed-receipt/retention tests. Dependencies: T17.

## M09 — Web experience

- [ ] **T19 Build React conversation evidence activity and approval views** — Accessible UI with all states, safe rendering, independent identities, manual baseline and backend capabilities. Dependencies: T17, T18.
- [ ] **T20 Implement authenticated SSE replay and actual browser tests** — Cursor reset/dedup, stream revocation, multi-tab decisions, identity changes and keyboard interaction. Dependencies: T19.

## M10 — Observability and budgets

- [ ] **T21 Instrument real runtime and create diagnostics** — OTel traces, metrics, dashboards, redaction and bounded labels; audit records separate. Dependencies: T19, T20.
- [ ] **T22 Enforce budgets and degraded operating behavior** — Queue/model caps, time/retry limits, dependency outages, no hidden fallback; measure load on named hardware. Dependencies: T21.

## M11 — Containers and cluster

- [ ] **T23 Build target Docker and Compose profiles** — Locked minimal images, target services, reference-vs-real modes, explicit model endpoint and secret handling. Dependencies: T21, T22.
- [ ] **T24 Deploy target Helm/kind topology and test it** — Compatible CNI, network allows/denials, probes/drain, actual worker/pod failure and persistent state. Dependencies: T23.

## M12 — Restore and upgrade

- [ ] **T25 Rehearse retained-receipt restore and paused-run upgrade** — Restore isolated old app state against retained destination, route/migrate old workflows and verify rollback compatibility. Dependencies: T23, T24.
- [ ] **T26 Complete operational runbooks and measured recovery evidence** — Write exact commands and observations for outages, stale approvals, lease recovery, uncertain outcomes, overload and restore. Dependencies: T25.

## M13 — Evaluations and secure CI

- [ ] **T27 Build evaluation harness baseline reports and holdout governance** — 80 development/40 independently controlled release cases target, repeated trials, grader calibration and frozen thresholds. Dependencies: T25, T26.
- [ ] **T28 Enable secure CI and protected release gates** — Test trust separation, locked builds, scans, actual evals, blockers, SBOM/provenance and release manifest. Dependencies: T27.

## M14 — Portfolio release

- [ ] **T29 Validate clean-machine setup and record three truthful demos** — Use actual LLM/MCP success, denied action, and real interruption/reconciliation; keep deterministic demo separate. Dependencies: T27, T28.
- [ ] **T30 Review license claims release evidence and owner publication approval** — Update README/ADRs/status/limits, tie every claim to evidence, no remote publication without explicit approval. Dependencies: T29.

## M15 — Optional extensions

- [ ] **T31 Add opt-in Slack adapter after v1** — Verified callbacks, identity mapping, outbox notifications and same review/execute/reconcile policy. Dependencies: T29, T30.
- [ ] **T32 Add explicitly approved budgeted cloud deployment** — Terraform/EKS only after owner authorization, compatible identity/secrets, cost plan and teardown. Dependencies: T31.

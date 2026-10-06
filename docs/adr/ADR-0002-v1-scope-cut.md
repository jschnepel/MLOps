# ADR-0002: Version 1 scope cut and single-writer checkpoint profile

- **Status:** Accepted, 2026-10-06
- **Amends:** BUILD_SPEC.md §2, §8, §20–§25, §28 (see SPEC_AMENDMENTS.md AM-02, AM-12, AM-50)
- **Deciders:** repository owner

## Context

The adversarial review (`docs/reviews/handoff-review-2026-10-06.md`) estimated the full OPS-BUILD-1.0 scope at 87–136 solo days. That figure is the reviewers' estimate, not a measurement. Several required items add little that an interviewer can see, but cost a lot:
- kind with a third-party CNI;
- paused-version upgrade rehearsal;
- SBOM/provenance;
- a full Grafana/Loki/Tempo/Prometheus stack;
- six database credentials;
- a tenant-admin surface.

The evaluation work, which matters most to an MLOps reader, was scheduled behind all of them.

The review also found that fencing distributed LangGraph checkpoint writes needs a custom `BaseCheckpointSaver`. The stock `PostgresSaver` writes in sealed transactions with no hook. A stale worker therefore appends a new latest checkpoint rather than overwriting one.

## Decision

1. **V1 consists of M00–M14 of `handoff/tasks.json` v1.1.** These move to the optional, non-blocking M15:
   - kind/Helm and cluster NetworkPolicy tests;
   - the upgrade rehearsal;
   - SBOM/provenance;
   - fenced checkpoint writes (R021);
   - Slack;
   - cloud.
2. **Evaluation is milestone M09,** directly after review/outcome recovery. A deterministic scenario suite runs on every PR. A model-quality evaluation runs against an owner-authored, hash-locked holdout, with Wilson confidence intervals.
3. **Reduced profiles for v1:**
   - **Observability:** OTel collector plus one trace backend.
   - **UI:** three panels covering eight states.
   - **Database roles:** migrator, api, worker, function-only mcp_exec, plus a separate destination database.
   - **Administration:** no admin surface.
4. **Single-writer checkpoint profile.**
   - Workers write checkpoints only while holding the run lease.
   - Every node rereads authoritative application state.
   - Checkpoints are never authority.
   - A stale worker appending a checkpoint after losing its lease is a **known, documented limitation**: R021 stays open.
   - Multiple worker replicas are allowed. Application writes are fenced and the destination is idempotent, so duplicated *effects* are still prevented.

## Consequences

- **Effort:** the reviewers estimated about 54 solo days for this cut. That is an estimate, not a commitment.
- **What v1 does not claim:**
  - "tested Kubernetes deployment";
  - "fenced distributed checkpoints";
  - "independent third-party holdout".

  The README states each of these limits.
- The recovery demo uses `docker kill` on a worker container, not a pod kill.
- Every deferred item keeps its requirement ID and task, so it can be picked up without redesign.

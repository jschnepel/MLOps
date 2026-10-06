# ADR-0002: Version 1 scope cut and one-replica checkpoint profile

- **Status:** Accepted 2026-10-06; revised the same day for OPS-BUILD-1.2 after the second review.
- **Amends:** BUILD_SPEC.md §2, §8, §20–§25, §28 (see SPEC_AMENDMENTS.md AM-02, AM-12, AM-50, AM-60).
- **Deciders:** repository owner

## Context

Two adversarial reviews estimated the effort, without measuring it:
- the full OPS-BUILD-1.0 scope at **87–136 solo days**;
- this cut at **54–108 days**. The lower figure is round one's estimate; the upper is a task-by-task estimate from round two.

Several 1.0 items are expensive but add little that an interviewer can see:
- kind with a third-party CNI;
- the upgrade rehearsal;
- SBOM/provenance;
- the full observability stack;
- six database credentials;
- a tenant-admin surface.

Evaluation, the core MLOps evidence, was scheduled last.

Fencing LangGraph checkpoint writes needs a custom `BaseCheckpointSaver`. The stock `PostgresSaver` writes in sealed transactions with no hook. A stale worker can append a newer checkpoint and overwrite pending writes. LangGraph also persists checkpoints **asynchronously by default**.

## Decision

1. **V1 is M00–M14 of `handoff/tasks.json` (1.2).** These move to the optional, non-blocking M15:
   - kind/Helm and cluster NetworkPolicy (R112);
   - the upgrade rehearsal;
   - SBOM/provenance;
   - fenced checkpoint writes and multi-replica workers (R021);
   - Slack;
   - cloud.
2. **Early de-risking.** A walking skeleton (T08) crosses every service with a fake model before any hardening, and secret-free CI (T06) starts with the first code.
3. **Evaluation is M09.** The holdout is owner-authored and sealed in M00, before any prompt tuning. Results are reported with case-level Wilson intervals and paired McNemar tests, and no ranking is claimed without significance.
4. **Reduced v1 profiles:**
   - **Observability:** OTel collector plus one trace backend.
   - **UI:** three panels covering eight states.
   - **Database roles:** migrator, api, worker, a function-only mcp_exec, a non-owner app_definer, plus a separate destination database.
   - **Administration:** no admin surface.
5. **One worker replica in v1.**
   - Graphs run with `durability="sync"`.
   - The accepted `checkpoint_id` is stored on the run under the fence, and resumes use it explicitly.
   - Application writes are fenced, and the destination's action keys make effects idempotent.
   - Multiple worker replicas are a v1.1 capability, gated on R021.

## Consequences

- **Effort is a range, 54–108 solo days, not measured.** It is re-estimated after the walking skeleton (T08), using real slice durations.
- **V1 does not claim:**
  - "tested Kubernetes deployment";
  - "horizontally scaled / fenced distributed workers";
  - "independent third-party holdout".

  The README states each limit.
- The recovery demo uses `docker kill` on the worker container.
- Every deferred item keeps its requirement ID and task.

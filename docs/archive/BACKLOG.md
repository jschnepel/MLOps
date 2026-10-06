# Ordered implementation backlog

Each row is an issue-sized work item. Attach code, tests and evidence to the same issue. “Planned” is not a passing implementation. Stage order follows IMPLEMENTATION.md.

| ID | Work | Dependencies | Acceptance evidence | Delivered status |
|---|---|---|---|---|
| P00 | Reproduce reference and inspect negative tests | None | CLI + 58 passing tests | Implemented/tested here; reproduce locally |
| P01 | Resolve dependency lock and image/action digests | P00 | Clean install from locked hashes; no moving release inputs | Planned |
| P02 | Add lint/type/static security checks | P01 | Required CI checks; baseline issues addressed | Planned |
| P03 | Select login provider; implement OIDC/session lifecycle | P01 | Issuer/audience/signature/expiry and login/logout tests | Planned |
| P04 | Enforce team/user projections on all endpoints and evidence | P03 | Cross-team denial; revoked session/stream stops | Reference subset tested; target planned |
| P05 | PostgreSQL schema/migrations and repository adapter | P01 | Fresh/migrate/rollback-compatible schema test | Planned |
| P06 | Restricted roles/RLS and pooled context handling | P04,P05 | Real runtime-role isolation tests | Planned |
| P07 | Transactional run/message/job admission | P05 | Request crash cannot lose admitted job | Planned |
| P08 | Lease/heartbeat/fencing/sweeper | P07 | Concurrent workers, expired lease, stale-owner denial | Planned |
| P09 | Persisted event/outbox protocol | P07 | Commit/delivery failure recovery, dedup cursors | Reference events only; outbox planned |
| P10 | Lock MCP/LangGraph SDKs and execute contract examples | P01 | Explicit integration-test command passes | Examples only/unverified |
| P11 | Remote MCP auth host and real client | P03,P10 | Network list/call, audience denial, timeouts, schema validation | Planned |
| P12 | LangGraph leased worker and PostgreSQL checkpoints | P08,P10 | Worker restart during human pause; safe wakeup dedup | Example graph only |
| P13 | Replace direct reference tools with MCP adapters | P11,P12 | Trace proving remote tool boundaries; no direct bypass | Planned |
| P14 | Immutable proposal and destination idempotency/reconciliation | P05,P13 | Lost response, duplicate click, expired/revoked approval | Reference behavior tested; remote migration planned |
| P15 | Versioned document ingestion and lexical search | P06 | Effective version/access/hash/citation tests | Fixture only |
| P16 | Real local model configuration and bounded structured output | P10 | Named model/hardware inference records, invalid output handling | Adapter only/unverified |
| P17 | Add pgvector and compare retrieval baseline | P15,P16 | Matched-scenario recall/support comparison | Planned |
| P18 | Conversation messages/clarifications/cancellation semantics | P09,P12 | Corrections, same-run serialization, stale reply tests | Reference subset tested |
| P19 | React/TS user workspace and safe rendering | P18 | Browser happy path, identity switch, keyboard accessibility | Native reference only |
| P20 | SSE replay/retention/session expiry | P09,P19 | Disconnect/reconnect, cursor reset, access revocation | Reference code only; browser unverified |
| P21 | OTel traces, metrics and dashboards | P11,P12 | One correlated run, no secret capture, bounded labels | Planned |
| P22 | Budgets, overload and manual degraded workflow | P17,P19,P21 | Dependency outage and bounded queue tests | Planned |
| P23 | Dev/held-out benchmark and grader calibration | P14,P17,P19 | Versioned repeated-trial outcome report | Development scenario seeds only |
| P24 | Harden and build Docker images/Compose target | P13,P22 | Non-root images, read-only runtime, clean startup, scans | Single-reference templates only |
| P25 | Target Helm topology and enforced network policies | P24 | Fresh kind install, allow/deny connectivity, no secrets mounted unnecessarily | Reference chart only |
| P26 | Restore and paused-workflow upgrade experiments | P12,P14,P25 | Backup restore, old-run completion, no duplicate write | Planned |
| P27 | CI and protected release pipeline | P02,P23,P25,P26 | Required checks, immutable release manifest, provenance | Disabled template |
| P28 | Independent setup test, video, README results | P27 | Actual manual/RAG/orchestrated comparison and limitations | Planned |
| P29 | Optional Slack notifications/decisions | P09,P14,P20 | Signature/replay, current authority, duplicate-channel tests | Planned extension |
| P30 | Optional Terraform/EKS | P28, approved budget | Cost cap, deployment/rollback/destroy evidence | Not authorized or deployed |

## Definition of done for each issue

An issue includes a short design decision, tests that would fail without the implementation, safe configuration defaults, documentation updates, and actual verification evidence. Missing external dependencies mean the integration gate remains open, not that tests are skipped into a green release.

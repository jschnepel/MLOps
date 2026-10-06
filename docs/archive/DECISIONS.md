# Architecture decision records

Status: target decisions unless explicitly implemented in STATUS.md. References use SOURCES.md.

| ID | Decision and reason | Alternative considered | Cost / revisit trigger |
|---|---|---|---|
| ADR-001 | One bounded incident workflow. Makes usefulness, correctness and failure outcomes measurable. | General autonomous multi-agent assistant. | Less breadth. Expand only after a second validated user task exists. |
| ADR-002 | Independent approval bound to immutable proposal content. Prevents self-authorized or silently edited writes. [S06] | Single-user yes/no response to generated text. | More interaction. Revisit per-action risk policy, not model confidence. |
| ADR-003 | LangGraph owns coordination; application domain owns authority. Persistent pauses are useful, but replay does not confer external exactly-once effects. [S01–S02] | Graph state as the sole authorization database. | Duplicate-looking state must have documented ownership. Never make a generated resume payload authoritative. |
| ADR-004 | Custom MCP boundary with four tools and authenticated transport. Demonstrates real interoperable contracts. [S03–S05] | Direct tool functions only. | Additional auth/transport/versioning work. Keep direct reference adapter only for local unit tests. |
| ADR-005 | PostgreSQL for jobs/events/outbox and state initially. Reduces operational systems without dropping durability. [S08] | Kafka plus Redis from day one. | Lease/fencing logic remains necessary. Revisit after throughput/backpressure measurements. |
| ADR-006 | Destination idempotency and explicit OUTCOME_UNKNOWN. Accurate outcome reporting beats automatic retries. | Treat every timeout as failure. | Reconciliation and operator workflow are required. No downgrade for an easier demo. |
| ADR-007 | SQLite only in the delivered single-machine reference. Keeps runnable core independent of unavailable services. | Untested PostgreSQL code presented as working. | Reference is not scalable or production-equivalent. Replace before distributed deployment. |
| ADR-008 | Local model adapter plus deterministic test substitute. Reproducible controls and real-model evaluation stay distinct. [S10] | Hosted-only demo or fake responses represented as AI. | Hardware/model selection remains an experiment. Hosted adapter needs explicit data/egress policy. |
| ADR-009 | Lexical baseline before vector search; pgvector before another database. [S09] | Immediate vector database, reranker and approximate index. | Small-scale exact retrieval first. Revisit with measured recall/scale deficiencies. |
| ADR-010 | HTTP commands plus SSE projection. Fits web chat and approval events without a bidirectional socket requirement. [S14] | WebSocket for all communication. | Must build authorized replay and reconnect. Revisit for voice/live bidirectional transport. |
| ADR-011 | Evidence and recorded actions are default explanation. Reasoning text is optional, redacted and non-authoritative. [S11–S12] | Full emitted reasoning labeled as an audit trail. | Less spectacle, more inspectable claims. No condition justifies fabricating internal reasoning. |
| ADR-012 | Native reference UI, React/TS target. Validate backend contracts before frontend tooling expands. | Full framework scaffold with no tested backend. | UI migration is a real milestone; do not list React as delivered implementation. |
| ADR-013 | Local kind/Helm before EKS. Verify Kubernetes behavior before recurring infrastructure costs. [S18–S20] | Cloud-first multi-environment platform. | Single-machine limits. Add cloud when local release evidence and budget justify it. |
| ADR-014 | Real-model outcome evaluation separate from deterministic tests. Actual destination state decides task completion. [S13] | Judge only answer fluency or unit-test pass count. | Curated scenarios and human calibration cost effort. Keep sample limitations visible. |
| ADR-015 | Opt-in Slack after web. Reuse the same policy and state transitions, not a second agent. [S23–S24] | Multi-channel platform from day one. | Channel delivery/replay identities add work. Add only once web decisions are reliable. |

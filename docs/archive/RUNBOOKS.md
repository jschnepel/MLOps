# Operations runbooks to implement and rehearse

These are target procedures and validation requirements. Only the reference response-loss CLI/test was executed here. Record each rehearsal's versions, timestamps, commands, observed state and outcome.

## Model unavailable or invalid output

Confirm model endpoint health separately from API process liveness. Preserve request/run identity and evidence. Bound retries, mark the model-stage failure accurately, and offer the implemented authorized manual path. Never silently switch an offline profile to a cloud model. Recovery gate: restore model availability, submit a new authorized attempt, and verify no duplicate incident.

## Destination outcome unknown

Stop blind write retries. Record run/action ID and payload hash. Query the destination's authoritative receipt endpoint with the same action ID. Verify identity, tenant and hash. If confirmed, record success; if still ambiguous, retain OUTCOME_UNKNOWN and escalate for reconciliation. Do not infer non-commit from a transient absence. A new submission requires a documented safe decision, not a new random key.

Reference demonstration: `PYTHONPATH=src python -m operations_copilot.cli`. The tool commits one incident then loses its response. A reconstructed service finds that receipt. This is not a network-partition or pod-failure rehearsal.

## Expired or revoked approval

Deny execution and show why the existing authority is no longer valid. Retrieve fresh permitted evidence and issue a new proposal revision when appropriate. A new independent review is required. Do not extend old approval expiry behind the user's back. Authority is evaluated at the documented execution-grant point; later changes cannot undo already dispatched effects.

## Worker crash or expired lease

Stop stale owners from committing via fencing checks. The sweeper schedules safe recovery from persistent state. Reconcile any dispatched action before replaying a write. Human waits should not hold an active worker lease. Test crash before dispatch, after destination commit and before app acknowledgement separately.

## Database outage

Reject new work that cannot be durably admitted rather than acknowledging volatile in-memory acceptance. Separate liveness from readiness. Preserve no unsafe fallback database. Restore connectivity, recover queued work under lease controls and reconcile possible writes. Verify session/tenant context is still isolated after connection-pool recovery.

## Backup restore

Restore into an isolated environment; do not let resumed jobs reach the destination automatically. Validate schema version, membership/policy state, run/proposal/approval relationships and source references. Compare execution attempts with independently retained destination receipts. Only enable workers after reconciliation and explicit operator review. Measure restore duration and data-loss window; do not claim RPO/RTO before a real rehearsal.

## Workflow or schema upgrade with paused runs

Create a v1 run awaiting approval. Deploy v2 under a compatibility plan: route old runs to compatible code or migrate them through a tested transformation. Never reinterpret an old approval as authority for changed content. Rehearse rollback with database compatibility; restoring an older image does not undo a destructive migration or an external action.

## Slack delivery failure

Separate application success from notification delivery. Retain the workflow result in the authorized web interface; retry the outbox item with bounded backoff. Verify signatures and current membership on every eventual decision. Duplicate Slack/web decisions must converge on one committed incident.

## Suspected access leak

Disable affected route/tool/credential, preserve restricted evidence, scope affected runs and source permissions, and revoke sessions where necessary. Do not publish raw traces in a public GitHub issue. Correct the boundary and add a regression test before re-enabling. Follow the deployment owner's incident-handling policy; this synthetic project does not establish regulatory compliance.

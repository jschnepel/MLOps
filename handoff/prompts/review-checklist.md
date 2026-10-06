# Coding-agent review checklist

Review the actual diff, tests and observations. State the review role and whether this is a self-review or an independently performed review. Do not label unrun tests passing.

## Pass A — correctness and architecture

Check requirement IDs, explicit state transitions, ownership of authoritative records, canonical payload identity, API/schema compatibility, current evidence access, transaction boundaries, job/checkpoint fencing, wake-up crash windows, bounded computation and clear UI failure states. Verify that LangChain/LangGraph/MCP are actually on their intended runtime paths and that retrieval precedes final drafting.

## Pass B — adversarial security and reliability

Attempt untrusted authority fields, wrong-team IDs, expired audience/session/invocation context, self-approval, changed proposals, stale reviewer/requester roles, source revocation, duplicate decisions, stale worker commits, response loss after destination commit, delayed or mismatching receipts, cancellation races, restored old app state, untrusted browser content and leaked telemetry secrets.

For each finding record severity, affected requirement/code location, concrete failure mechanism, reproduction/test, proposed fix and observed retest result. Fix critical/high findings before closing a gate. Report remaining uncertainty rather than awarding a blanket “secure” verdict. Repeat in bounded cycles; escalate an unresolved gate rather than fabricating a clean pass.

# Threat model and security boundaries

This is a design and testing plan, not an independent audit or a claim of production readiness. Reference credentials and synthetic fixtures must stay local. Source IDs refer to SOURCES.md.

## Assets and trust boundaries

Protect user identity, team-scoped conversations and evidence, approvals, service credentials, checkpoint contents and destination integrity. User text, retrieved SOPs, model output, tool metadata, browser events and channel callbacks are untrusted until their relevant validation completes. The identity provider, application policy service, database and destination each have explicit responsibilities; a trusted transport does not make every payload instruction authoritative.

| Threat | Control to implement | Negative test |
|---|---|---|
| Prompt injection in a procedure | Treat source as data; fixed allowlisted tools; policy outside model | Embedded “create as admin” causes no unauthorized write |
| Model invents approval | Schema rejects authority fields; database-only approval records | approved=true cannot reach executor authority |
| Wrong-tenant run or citation | Authorization at retrieval, read, stream, cache and tool boundary | Exact ID still denied, including event replay |
| Stale cached access | Permission-aware keys, invalidation, current read checks | Revoke source/user and repeat request |
| Stolen/mis-audienced MCP token | Validate full resource-server claims; no token passthrough [S05] | Valid token for another audience rejected |
| Edited or replayed approval | Immutable hash/version, independent actor, expiry, current auth [S06] | Old Slack/web card cannot authorize changed payload |
| Lost response and duplicate write | Stable action key at destination; explicit uncertainty | Destination commits, response disappears, only one receipt |
| Concurrent workers | Leases/fencing plus destination idempotency | Expired owner cannot commit run state |
| Browser script injection | Text rendering, CSP, no arbitrary HTML/URLs | Malicious content remains text |
| CSRF/session confusion | Same-site session design, CSRF token/origin policy, reauth | Cross-site mutation rejected; session change clears UI |
| SSRF or secret exfiltration | Fixed endpoints, egress controls, redirect restrictions | Model-supplied destination/redirect rejected |
| Excessive work/cost | Input/output/tool/retry/concurrency/time budgets [S26] | Loop/oversized tool response stops predictably |
| Leaked observability content | Redaction, access scopes, short diagnostic retention | Tokens never appear in recorded trace/log payload |
| Malicious CI dependency/action | Locks, verified SHAs, secret isolation [S21] | Fork PR cannot obtain deployment secrets |
| Restore re-executes a write | Reconcile independent destination receipts before resuming | Restore pre-ack backup after destination commit; one incident |

## Important limits

The reference checks application permissions but has no real OIDC issuer, expiring sessions, production TLS, RLS, key rotation, remote MCP authentication, distributed fencing or external security review. Its opaque tokens identify local seeded users only. Its same-origin check is not a complete general-purpose CSRF/session implementation.

Current team visibility is intentional: members can read permitted runs within their team. A production requirement for owner-only conversations needs an additional policy and tests. Do not assume team equality satisfies every confidentiality requirement.

Authorization has a defined execution-grant point. Revocation after a remote action has been dispatched cannot retroactively erase an incident; report the actual state. RLS owner/superuser bypass must be tested with the runtime database role. [S07]

## Safe disclosure and repository hygiene

Do not include credentials, production documents, private traces, model weights or invented scan badges in the public repository. Choose an explicit code/data license and review dependency/model licenses before publication. Keep third-party security findings factual and version-specific. Establish a private reporting channel when publishing; no external contact is assumed in this kit.

# Problems found, and what changed because of them

This project began as an AI-generated build package. Before writing any code, the plan went through six adversarial review rounds (`docs/reviews/`), each with fresh reviewers told to assume every claim was false until shown evidence. This page lists the problems those rounds found and how the design changed. It is written for a reader who wants to know what engineering judgement went into the plan, not only what the plan says.

Each entry gives the problem, where it was found, and the change. The round number points to the review file with the full finding.

## 1. The diagrams had the pipeline backwards

**Problem.** The overview diagrams showed the LLM reasoning first, choosing its own tools, and then handing "tool call intents" to the tool layer. The detailed specs said the opposite: the workflow engine retrieves evidence first, then the model drafts from that evidence, and the model never chooses tools. (Round 0, the diagram comparison.)

**Change.** The detailed specs were adopted as authoritative and the overview diagrams were marked for correction. The runtime order is fixed as: admit → retrieve through controlled tools → draft → independent review → guarded write → receipt-backed result.

## 2. A crash at the wrong moment left a run stuck forever

**Problem.** The reference implementation marked a run "executing", then called the incident service. If the process died between those two steps, nothing could ever move the run again: re-execution was refused and reconciliation raised without saving state. The spec defined recovery for only one of four crash windows. (Round 1.)

**Change.** An explicit attempt protocol: *intent* (grant recorded, nothing sent) → *sent* (request definitely left) → *resolved*. Each window has a defined recovery. A never-sent action can be closed for certain through an **abort tombstone** at the destination, so "no incident exists" is a provable state, not an assumption.

## 3. "Exactly-once" was promised and cannot be delivered

**Problem.** The marketing diagrams said "ensure exactly-once semantics". There is no universal exactly-once guarantee across arbitrary services. (Rounds 0–1.)

**Change.** The system is honest about uncertainty: an action can end **unknown**, then **escalated**, then (by an audited operator decision) **abandoned-unverified**. The destination owns the truth through an idempotent action key that is never deleted. Retries always reuse the same key; nothing is ever retried under a new identity.

## 4. The write-fencing did not actually fence

**Problem.** Fences were per job, but the work was per run, so two workers could both believe they owned a run. The fence check was a plain read, which a stale worker could pass. Expiry checks used `now()`, which PostgreSQL freezes at transaction start, so a slow transaction could pass a check after its lease had expired. (Rounds 2–3.)

**Change.** One lease and one monotonic fence **per run**; every fenced write first locks the lease row (`FOR SHARE`, acquisition `FOR UPDATE`); all time comparisons use `clock_timestamp()` after locks are taken; one published lock order; the heartbeat runs on its own thread and connection so a long model call cannot lose the lease.

## 5. The checkpoint library behaved differently from what the spec assumed

**Problem.** The spec assumed graph checkpoints were written before the next step. LangGraph's default is asynchronous: it persists *while the next step runs*. Resuming from a stored checkpoint ID re-runs already-finished tasks instead of restoring their writes, and a crash-recovery resume forks the checkpoint. The library has no option to put its tables in a separate schema. (Rounds 2–3 and 5, verified in the library source.)

**Change.** Synchronous durability is required; the accepted checkpoint ID is stored on the run and read only after the library confirms it; every node must be idempotent; the saver's schema is set through the connection's search path. Version 1 runs a single worker replica and says so, instead of claiming fenced multi-worker checkpoints it cannot prove.

## 6. The tool server would have held the keys to the authority tables

**Problem.** The MCP tool server, the most network-exposed internal service, was specified to perform the final execution grant itself. That required write access to the approval, membership and grant tables, across tenants. (Rounds 1–2.)

**Change.** The tool server's database role has **no table access at all**. It can only execute a fixed set of `SECURITY DEFINER` functions that resolve its capability handle, perform the grant, record each attempt step and read tenant-filtered evidence. Later rounds found the first version of this design could not even run the system (the API could not create jobs; the worker could not update runs) and had no row-security policy for the function owner. The 1.3.3 rewrite replaced the prose matrix with exact column-level grants, a function-contract table (callers, inputs, locks, transitions, events), append-only state rows instead of updates, and explicit policies. Every state transition and every event now goes through a function.

## 7. The worker wrote its own tool allowlist

**Problem.** The party being restricted (the worker) chose which tools its capability handle was allowed to call. (Round 1.)

**Change.** The allowlist is derived on the server from the job type, the run state and the attempt state. Job types themselves were undefined until round 5; they are now a table with creator, purpose, allowed tools and dedup keys.

## 8. The local model needed settings nobody had measured

**Problem.** `qwen3:8b` "thinks" by default; thinking tokens would eat the output budget and leak reasoning the spec forbids showing. No context window was set (Ollama defaults to 4k on this GPU). A cold model load measured 53 seconds against a 60-second timeout. (Rounds 1, 4.)

**Change.** Thinking is explicitly disabled and verified; the context window is explicit; a warm-up call runs at worker start and verifies the pinned model digest; a measured probe on 30 distinct inputs precedes any use of the model, and its result is an owner decision rather than a fixed gate the probe could not justify statistically.

## 9. Identity revocation was not what the spec thought

**Problem.** Disabling a user in Keycloak does not trigger back-channel logout; the auth library has no helper for it; introspection is audience-checked in current Keycloak; the MCP SDK's built-in audience check expects a URL, not a client ID; token issuer differs between host and container callers. (Rounds 2, 4.)

**Change.** Decision-class actions check the user's status through the admin API with a fail-closed timeout; a membership sync bounds the window; audiences are resource URLs; the Keycloak hostname settings that make the issuer identical were verified in a live container before being written into the plan.

## 10. The evaluation could not support its claims

**Problem.** The test corpus was 463 words, smaller than one planned chunk. Only 2 of 32 scenario cards exercised the model. With 25 holdout cases, differences under about 30 points are not reliably detectable, not 15–20 as first written. Repeated trials were clustered and the 2-of-3 rule inflated rates. The owner would author the holdout, write the manual baseline and label the outputs, so the comparison was biased. A hash proves a holdout was not edited, not that it was not seen. (Rounds 1, 3, 5.)

**Change.** A larger corpus; the deterministic scenario suite is separated from the model-quality evaluation; case-level Wilson intervals and paired McNemar tests; safety metrics fail a case on any single bad trial; the manual condition is scored only with deterministic metrics; labelling is blind; the holdout is written before any prompt tuning, kept off the machine, and its hash is recorded outside the repository. The README is required to state the 30-point detectability floor.

## 11. The second-incident guard missed the common case

**Problem.** Two conversations could both be approved for the same asset and time window. The first guard blocked only *unresolved* actions, so once the first incident succeeded the second was created. The next version blocked only incidents committed *after* the second proposal froze, which is the uncommon ordering. (Rounds 5–6.)

**Change.** A grant is refused whenever any committed incident overlaps the same tenant, asset and interval, regardless of timing, unless the proposal explicitly names the run it supersedes and the reviewer approved that payload. Refusals move the run back to review rather than leaving it stuck holding the conversation slot.

## 12. The task plan could not be executed in order

**Problem.** All 32 tasks formed one serial chain; requirements were scheduled before the capabilities they test existed; every task had the same copied definition of done; evaluation sat behind Kubernetes and restore drills; nothing was showable until the last tasks. Later, three tasks had grown to 6–14 days each. (Rounds 2, 3, 6.)

**Change.** A dependency graph; each requirement placed where it first becomes testable; a walking skeleton through every service before any hardening; early secret-free CI; the holdout sealed first; oversized tasks split; a critical path of 15 tasks.

## 13. Library facts were stale or wrong

**Problem.** The MCP import in the example code did not exist in the current SDK; the spec described an older handshake model; it recommended a network plugin that the local Kubernetes tool does not support; the model-integration dependency was missing from the manifest; there was no lockfile. (Round 1.)

**Change.** Every library claim was checked against live sources or downloaded package source, exact versions were recorded, and the stale examples were marked historical.

## 14. The plan's own documents over-claimed

**Problem.** The README, the start guide and the agent prompt said "tested Kubernetes deployment" and "production-ready"; the first git commit labelled "unmodified" had one modified file; an edit of mine corrupted a rule by writing a real line break where the literal `\r` belonged; the machine's local model server was listening on every network interface with permissive firewall rules. (Rounds 5–6, and the environment checks.)

**Change.** The entry documents now state that implementation has not started and make no Kubernetes claim; the original package is committed as a zip and verified byte-for-byte; the corruption was fixed and a no-carriage-return check added; the network exposure was reported to the owner, who chose to restrict it (the runbook is a task; the agent changes no system settings).

## 15. What the process taught

Six rounds found the following pattern: each round's fixes introduced the next round's high-severity findings, because new mechanisms (functions, tombstones, locks, matrices) arrive with their own gaps. The fourth round, which dry-ran the first tasks on the real machine, found more actionable problems per hour than any prose review. The plan therefore ends spec-wide review here and reviews each implementation slice against its code and tests, where a grant either lets admission commit or it does not.

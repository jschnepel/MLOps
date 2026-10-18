# Threat model: the write path

Who this is for: anyone deciding whether an incident the system reports really exists, reviewing a change to the write
path, or answering "what if this service were compromised?". It covers v1's write path only: the worker, mcp-write,
the definer functions in the application database, and the synthetic destination incident-sim. The design is AM-13,
AM-15 and AM-20 in `SPEC_AMENDMENTS.md` and BUILD_SPEC §13 and §14; T47 (Plan K) added this file.

## The outcome-truth statement

**v1 trusts mcp-write for outcome truth.** mcp-write is the only service that calls incident-sim and the only role
(`mcp_exec`) that may record an outcome (`app.record_outcome`). `record_outcome` checks the receipt's action id and
payload hash against the grant, but the receipt reaches it through mcp-write, so a compromised mcp-write could record
an outcome the destination never gave: a SUCCEEDED for an action that did not commit, or a FAILED for one that did.
Nothing inside the application database can tell such a record from a true one.

The control is detective, not preventive: `uv run python scripts/skeleton.py keys` (T10) reads every destination key
and every grant and lists each key whose `(action_id, payload_sha256)` no grant carries, exiting 1 if there is one. It
finds an incident created outside a grant. It does not compare recorded outcomes with the keys, and nothing runs it on
a schedule yet (T32).

Optional hardening for v1.1, not built: incident-sim signs each receipt and tombstone with an HMAC key held in a
table only `app_definer` can read, and `record_outcome` verifies the signature, so mcp-write could relay a receipt but
not forge one.

## Who is trusted for what

| Party | Trusted for | Not trusted for | What holds it to that |
|---|---|---|---|
| Worker | driving jobs; minting a handle for its own job under its live lease | contacting the destination; recording an outcome; choosing a tool | it holds no write-path function, and it has no client code and no credential for incident-sim; the server derives the allowed tools from the job type, run state and attempt state |
| mcp-write | outcome truth (above); the grant gate's result | anything without a live handle of an execute or recover job | `mcp_exec` executes seven functions and reads no table; every function resolves the handle again |
| mcp-read | read tools for investigate and resume_input jobs | the write path | `mcp_read` executes `current_time` and `resolve_invocation` only; a write handle is refused there |
| incident-sim | whether an incident exists (its permanent keys) | who may write | it accepts only mcp-write's token (`aud` incident-sim, `azp` ops-mcp-write) |
| The model | nothing on this path | tools, handles, outcomes | it never sees a handle or a write tool |

## Threats and the controls that answer them

| Threat | Control | Evidence |
|---|---|---|
| An incident without an approved proposal | the POST happens only after `grant_execution` committed a grant for an approved, unexpired, hash-matching proposal; an abort never creates an incident | `tests/e2e/test_definers_write_path_live.py`, `tests/e2e/test_mcp_write_t47_live.py` |
| A second incident for one approval | one grant per run, a random action id, and the destination's `INSERT … ON CONFLICT DO NOTHING` key; a re-send uses the same key | `tests/e2e/test_mcp_write_t47_live.py` (the re-send), `tests/e2e/test_incident_sim_live.py` |
| A lost reply read as "nothing happened" | every unanswered call is UNKNOWN; only a destination tombstone proves no commit; a 404 lookup is never a no-commit | `tests/plan_k/test_recovery_tools.py` |
| A send after a cancel or past the dispatch deadline | `mark_sent` re-checks both under the runs lock for a first send and for a re-send of a SENT attempt alike, and answers `cancelled` or `expired`; the tool then aborts instead of sending. Only `sent` or `already_sent` from `mark_sent` lead to the incident POST; `cancelled` and `expired` lead to the abort POST instead, after `request_abort` committed it; the others (`abort_requested`, `not_redispatchable`, `resolved`) send nothing. A cancel that lands between `mark_sent`'s commit and the POST is AM-13's own window, the same for both | `tests/e2e/test_migration_0010_live.py`, `tests/e2e/test_mcp_write_t47_live.py`, `tests/plan_k/test_recovery_tools.py` |
| A stolen or replayed handle | only its hash is stored; it lives 60 s, for one job of one run, at one lease fence, for one server and one `azp`, and is never logged | `tests/e2e/test_mcp_read_t15_live.py`, `tests/e2e/test_migration_0010_live.py` |
| Receipt lookup used to probe or to act | the recovery tools answer recover handles only; the receipt lookup creates no grant, attempt, job or key, and an abort adds only its attempt-state rows and the destination's tombstone | `tests/e2e/test_mcp_write_t47_live.py` (R030) |
| A foreign token at a server | each server's verifier checks issuer, audience, `azp` and the access token's `typ`; incident-sim answers mcp-read's token 403 | `tests/plan_k/test_verifier_t47.py`, `tests/e2e/test_mcp_write_t47_live.py` |

## Not covered here

Network isolation between the containers (mcp-read cannot reach incident-sim at all) is T30's; until then the token
checks above are the only barrier. The worker's recovery loop (backoff, scheduled recover jobs, escalation) is T22's.

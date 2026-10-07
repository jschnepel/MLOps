# Adversarial review, round 4: OPS-BUILD-1.3

**Reviewed:** commit `87d5e18` (1.3 diff `a537300..3b12a1a`).
**Date:** 2026-10-06.

**Method:** two fresh reviewers:
1. closure of round-3 B1–B14, plus regressions introduced by the 1.3 edits;
2. a **dry run** of T01–T08 on this machine, using isolated checks outside the repo: `uv pip compile`, wheel inspection, live Ollama calls, and a throwaway Keycloak 26.8.0 container.

The lead spot-checked the findings. **Legend:** ✓ verified by the lead · ○ reviewer finding · ✗ rejected.

## Verdict

**Conditional GO.** T01 and T03 can start now. A small **1.3.1** documentation edit (about 6 items, below) unblocks T02, T04 and T07. No architectural issues were found.

## Evidence gathered (dry run) ○

- **Dependencies:** the reference pins and the full AM-30 stack resolve on win/py3.13, linux/py3.13 and win/py3.12.
- **Hashes:** all 19 reference hashes and 8 fixture hashes recompute correctly, and there are no CRLF line endings.
- **Libraries:** mcp 2.3.0 exposes `mcp.server.mcpserver.MCPServer`/`Context`, `mcp.Client`, a `TokenVerifier` protocol and revision 2026-07-28. langchain-ollama 1.1.0 has `reasoning` mapping to `think`.
- **Ollama 0.33.3 + qwen3:8b:** `think:false` works with no thinking field returned. At `num_ctx=16384` the model uses 7.4 GB, entirely on GPU (8.7 of 10 GB total).
  - **The first cold call took 53 s, against the 60 s timeout. A warm call took 4.7 s.**
  - The `host.docker.internal:11434` bridge works from containers.
- **Keycloak 26.8.0:** `KC_HOSTNAME=http://localhost:18080` plus `KC_HOSTNAME_BACKCHANNEL_DYNAMIC=true` gives an identical `iss` for host and container callers.
- **Cleanup** ✓: no probe containers remain. The `quay.io/keycloak/keycloak:26.8.0` image (751 MB) is still cached locally; T05 will use it anyway. The repo has no stray `egg-info` and a clean `git status`.

## Round-3 closure (B1–B14) ○

| Status | Items |
|---|---|
| CLOSED | B1, B2, B6, B7, B8, B9, B11 |
| PARTIAL | B3 (CLI role and operator identity), B4 (concurrent slot check), B5 (no test for abstain without a question), B10 (starter prompt not sealed), B12 (T07 doesn't read `seed-ids.json`; `iss` not asserted), B13 (Alembic rev 1 missing from T08 DoD and T09), B14 (venv location not in DoD) |

## 1.3.1 edits needed before the affected task starts

| # | Blocks | Finding | Edit |
|---|---|---|---|
| E1 | T04 | **The reference unit is incomplete** ✓: the reference `Dockerfile` (`COPY scripts`), `Makefile` and `compose.yaml` all use `scripts/init_demo.py`. It is also undecided whether `reference/` is a workspace member, and there is no `make` on this machine. | Add `scripts/init_demo.py` and `scripts/check_reference.sh` to the moved unit. `reference/` is **not** a uv workspace member (`exclude=["reference"]`), and root ruff, mypy and pytest exclude it. The "one command" is a uv/Python script, not `make`. |
| E2 | T02 | **The "sealed starter prompt" is undefined** ✓/○. | The probe uses `handoff/prompts/incident-draft-v1.md` and `schema-repair-v1.md` at their MANIFEST hashes, validated against 1.0 `model-draft.schema.json`. T03 records those two hashes externally alongside the holdout seal. The command is `uv run --isolated --no-project --with langchain-ollama==1.1.0`, with the freeze taken via `importlib.metadata`. Cold and warm latency are reported separately. Inputs carry synthetic evidence bundles. |
| E3 | T01 | **The `-e` install** ○ would leave the external venv pointing at `src/`, which breaks after T04, and writes `src/*.egg-info`. | Install without `-e`. Re-create the venv from `reference/` after T04 (R121). |
| E4 | T07 | **Late evidence after ABANDONED_UNVERIFIED** ○: `action.confirmed` requires status SUCCEEDED, but `payload.status` is the *run* enum. | Late destination evidence on an abandoned run emits `action.late_evidence` with `outcome` and a receipt or tombstone, and the run status stays ABANDONED_UNVERIFIED. `record_outcome` makes **no transition** from terminal states. Recover jobs remain allowed in ABANDONED_UNVERIFIED (allowlist row). |
| E5 | T07 | **The AM-80 negative probes aren't listed** ○, so the DoD is self-defined. The checker also reads text without an encoding, under the cp1252 locale. | T07 commits at least one negative example per AM-80 row, before code. The checker uses `encoding="utf-8"` and rejects `\r` in fixtures and schemas. |
| E6 | — | **M00 lists T01, T02, T03**, but T02 depends on T03 ✓. | Reorder to T01, T03, T02. |

## Fix in task (no spec change needed) ○

| Task | Note |
|---|---|
| T03 | The hash procedure is `sha256` of the exact file bytes, using the documented command. Owner attestation of the external record. |
| T05 | Host vs container split; pin the Postgres major version; realm secrets via import placeholders; a dev-only direct-grant test client for the `sub`/`iss` assertions. **Do not route host callers through `host.docker.internal`**: it resolves to the LAN IP, and ports bound to 127.0.0.1 are unreachable that way. |
| T08 | Alembic rev 1 runs as an owner role (listed as debt); T09 ALTERs owners and enables RLS in later revisions. Add Alembic rev 1 to T08's DoD. |
| T09/T22 | Add `sweeper` and `operator` roles to AM-02. The operator CLI takes the operator identity as a required argument and does not use `migrator`. |
| T12/T21 | The slot rule is enforced by a partial unique index on `runs(conversation_id)` over active states, with a concurrent R120 test. |
| T13/T21 | The advisory lock needs `asset_id NOT NULL`, read before locking. Prefer `hashtextextended`. Test that `app_definer` can call `pg_advisory_xact_lock`. |
| AM-31 | **The cold model load (53 s) nearly hits the 60 s timeout.** Add a warm-up call at worker start, and measure it in T02. |

## Rejected ✗

- "R071, R120, R098 and R031 sit in milestones earlier than their owning tasks." By design, each requirement's milestone is its **earliest** owner: T03 is M00, T07 is M01, T10 is M02, T04 is M01. Verified.

## Recommendation

Apply 1.3.1 (E1–E6), then start T01 and T03 immediately. Spec review rounds stop here. The remaining risk is empirical, and the slices' tests will surface it.

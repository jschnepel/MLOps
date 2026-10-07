# Adversarial review, round 8: OPS-BUILD-1.3.5 and Plan A

**Reviewed:** commits `7e41962` (1.3.5) and `89d2c9d` (Plan A, `docs/superpowers/plans/2026-10-07-first-slice-a-baseline-workspace.md`).
**Date:** 2026-10-07.

**Method:** three fresh reviewers: (1) closure of round 7 and regressions in 1.3.5; (2) a builder dry-run of Plan A, executing each step on scratch copies outside the repo (uv 0.11.8, Python 3.13.7, ruff, pytest, the langchain-ollama 1.1.0 source, the live `/api/tags` and `/api/version`, `git ls-remote` for the action tags); (3) Plan A against the spec and the plan-writing rules. The lead verified every finding marked ✓.

## Bottom line

| | Result |
|---|---|
| Round-7 closure | 8 of 10 closed, 2 partial; the LATER list landed except three items |
| 1.3.5 regressions | 2 high (both structural), 4 medium, 6 low; all LATER (T09/T12/T45), none affects Plan A |
| **Plan A** | **Not executable as written**: 9 blocking defects, all reproduced; the plan's "Expected: passed / GREEN" lines were false in five places |
| Verified sound | `create_run` is grant-complete; `transition_run` targets ⊆ AM-10; the `ChatOllama` kwargs `reasoning`, `num_ctx`, `num_predict`, `temperature`, `base_url` exist in 1.1.0; `/api/tags` carries per-model digests; the Wilson values; the MANIFEST matches the zip 161/161; `git ls-remote` parsing is right for both lightweight (`checkout@v5`) and annotated (`setup-uv@v6`) tags |

The plan failed the same way the original package did: it asserted outcomes ("4 passed", "CHECK: GREEN") that the author had not run. The dry-run reviewer caught them by running. Lesson applied in 1.3.6: Plan A now orders the reference move before any root pytest, and every "Expected" line names only what the step's own command prints.

## Plan A: blocking defects (all ✓ reproduced by the dry-run reviewer)

| # | Step | Defect | Fix in the rewritten plan |
|---|---|---|---|
| P1 | T5 s1/s4/s5 | `provenance/reference-code-hashes.json` is `{"description", "files": [...]}`; three code blocks iterate it as a list → `TypeError` | iterate `["files"]` |
| P2 | T4 s6/s10 | `tests/conftest.py` (reference) sits above `tests/plan_a/`; pytest loads it and fails on `import operations_copilot` | the reference move (T42) now precedes the workspace (T04) |
| P3 | T4 s6 | `uv sync --locked` installs only the dev group on a `package = false` root; all seven `ops_*` imports fail | `uv sync --locked --all-packages` (plan and CI) |
| P4 | T4 s10 | `ruff check .` 11 errors and `ruff format --check` 8 files, all in hash-pinned reference files; "fix with ruff format" would alter pinned bytes | move first; `extend-exclude = ["reference"]`; format only repo-owned scripts |
| P5 | T4 ruff | `extend-exclude = ["src"]` matches basenames, so no member's `src/` is ever linted | exclude `reference` only |
| P6 | T2 s7/s8 | `hashlib.sha256(b'{}' + b'\\n')` inside an f-string hashes a backslash-n; the test fails against a correct implementation | `b"{}\n"` |
| P7 | T1 s2 | non-editable in-tree install writes `build/` and `src/*.egg-info`; `.gitignore` hides only the latter; the step's "-e" diagnosis is wrong | add `build/` to `.gitignore`; delete both after install; check with `ls src` |
| P8 | T3 s7, T4 s9 | PowerShell `>` writes UTF-8 BOM + CRLF; `json.loads` fails on the BOM; Git Bash writes CRLF | generators write their own files with LF |
| P9 | T3 s7 | the thinning rule emits only `no_alerts` and `injected` (18 each); three scenarios never appear | thin by `(asset_idx + hours_idx + scenario_idx) % 3`, giving 60 cases across all five |

Also fixed: the "cold" latency measured whatever state the model was in (now unloads with `keep_alive: 0` first); `uv run --isolated` picked CPython 3.14.4 (now `--python 3.13` and a `.python-version`); `thinking_in_metadata` was recorded but never aggregated; the probe never checked that the holdout seal exists; the layout test could not detect a cross-member import (now an AST scan); the checker edit step was prose ("replace every…", a placeholder in disguise; now the complete new tail is shown); `write_report` was untestable (now a pure `summarize()` with a test); `Tee-Object` wrote BOM + CRLF; "pins" in the environment capture was always true; the manifest assertion `"161" in stdout` was brittle; Task 2 claimed "4 passed" for 5 tests; `PROJECT_HISTORY` still said "six rounds".

**Coverage gaps acknowledged in the plan now:** R003 is partial in Plan A (images are T05's); R031's import half is deferred to the first task that adds the SDK dependencies (T07/T15), stated explicitly; a clean-clone `uv sync --locked --all-packages` step is added to T04.

## 1.3.5 regressions (spec text; fixed in 1.3.6)

| # | Finding | Fix |
|---|---|---|
| R1 (high) | **`create_run` cannot find its tenant** ✓: functions resolve the tenant through `run_directory` or a handle; a new run has neither, and `conversations` is under RLS → every admission returns zero rows. | `create_run(tenant_id, …)`; the API passes the tenant from the authenticated session (it is already the identity trust anchor). |
| R2 (high) | **`freeze_proposal(run_id, draft_id)` has no bytes to canonicalize** ✓: `drafts` holds IDs only and R091 forbids proposal text in checkpoints. | `freeze_proposal(run_id, draft_id, payload)`; the function verifies `sha256(canonical(payload)) = drafts.draft_sha256`. |
| R3 | `status.answered` and the conversation-level clarification have no event enum, no sequence source and no schema. | They are **messages**, not events: the API inserts `messages` with `kind ∈ {status_answer, clarification_question}`; `record_status_answer` is removed. |
| R4 | The sweeper can see only `memberships` and `jobs`; `expire_proposals`, `deliver_outbox` and deadline escalation read tenant tables with no tenant set. | The sweeper iterates `tenants` (no RLS) and sets `app.tenant_id` per tenant; "exactly these policies" relaxed to name `sweeper_all`. |
| R5 | `clarify` has no resume path and no ordering against an active run. | Replies re-enter admission as new messages; rule order: active-run `reject` before `clarify`. |
| R6 | AM-20.5 says FORCE RLS binds `migrator`, which `BYPASSRLS` makes false. | Wording corrected. |
| R7–R12 (low) | `ABORT_REQUESTED` missing from the attempt-state enum and allowlist rule; ADR-0003 lists five routes (AM-16 has six); ARCHITECTURE's sweeper row contradicts its callers; T43 never mentions the seed migration; R015 evidence says `create_run` commits the message (the API does, in the same transaction); PROJECT_HISTORY says "six rounds". | All corrected. |

## Go / no-go

**GO for Plan A after the rewrite** (T01, T03, T02, T42, T04, T06 in that order). The spec regressions are T09/T12/T45 items and are fixed in text now so those tasks do not inherit them. The next plan (B: T05, T43, T44) should be written after T04's `uv.lock` and `data/seed-ids.json` exist, and must be dry-run the same way before anyone executes it.

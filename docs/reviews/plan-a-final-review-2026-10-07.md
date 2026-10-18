# Plan A final whole-branch review (2026-10-07)

Branch `plan-a`, range a638801..289c16a, reviewed after six subagent-implemented tasks each passed a task-scoped review. Outcome: 0 Critical, 5 Important, 7 Minor; all five Important and four of the minors were fixed in one wave (commits 927e547..61c0f0a) and confirmed by a scoped re-review. Deferred: M3 (cancel-timing restructure), M6 (derive the mypy member list).

The report below is the reviewer's text, unedited.

---

# Final whole-branch review: plan-a (a638801..289c16a)

Reviewer: final broad pass (single reviewer, no subagents). I read the review package in three passes: config/members/data, scripts, then tests/lock. I also read the plan header, Global Constraints, Review Focus and T42 Files/Interfaces, SPEC_AMENDMENTS AM-31/AM-50/AM-60, and the ledger.
Read-only. I ran all commands below in a temporary detached worktree (`git worktree add --detach … 289c16a`), which I then removed. HEAD, the index and the working tree of this checkout were not touched.

## Evidence I ran

| Check | Command (in temp worktree unless noted) | Result |
|---|---|---|
| Reference bytes vs zip | Python script comparing every `git ls-files reference` blob to `operations-copilot/<path>` in `provenance/handoff-1.0.zip` | 26/26 delivered files identical; `reference/README.md` is the plan-mandated addition (no zip counterpart) |
| Zip identity | sha256 of `provenance/handoff-1.0.zip` | `49df5852…09f6`, the same as the ledger |
| Checker baseline | `python -I scripts/verify_handoff.py --reference-code --manifest` | rc 0, 19 + 161 PASS |
| Checker under tampering | appended to `reference/Makefile` and `reference/pyproject.toml`, deleted `reference/Dockerfile`, added `reference/src/operations_copilot/evil.py`, re-ran the checker | **rc 0, same PASS lines** (see I1) |
| Lock consistency | `uv lock --check` | rc 0; the lock has all 7 members plus the root dev group |
| One command after sync | `uv sync --locked --all-packages && uv run python scripts/check.py` | `CHECK: GREEN`: ruff clean, 67 files formatted, mypy 7 files, `36 passed, 1 skipped` |
| One command on a fresh clone | `rm -rf .venv && uv run python scripts/check.py` | **`CHECK: RED`**: `ModuleNotFoundError: No module named 'ops_core'` (see I2) |
| CI interpreter path | `uv run --no-project --python 3.12 python -I scripts/verify_handoff.py --reference-code --manifest` | PASS on 3.12 (ubuntu-24.04 `python3`) |
| Encoding | Python scan of all 84 A/M/R blobs at 289c16a | 0 CR, 0 BOM, all UTF-8; the only files without a trailing newline are the two empty `__init__.py` |
| p95 float risk | compared `ceil(0.95*n)` with the integer `ceil(95n/100)` for n=1..1000 | 0 mismatches |

## Strengths

- **T42 kept the reference intact.** All 27 moves are pure renames, and every delivered file under `reference/` is byte-identical to the zip. That covers the 7 files with no hash pin, not just the 19 that have one. The remap generator refuses to write if any hash differs.
- **The probe gate comes before any network I/O.** `main()` checks that the seal exists and that the prompt hashes match before it contacts Ollama. Every network call is bounded: `urlopen(timeout=120)`, `asyncio.wait_for(…, 60)` around every `ainvoke` (first pass, repair, repeats, post-cancel), and the wait on the cancelled task. `nvidia-smi` has a 10 s timeout.
- **The report wording is now truthful.** The fix round removed the false "verified against seal" sentence. Errors, repeat errors and cancel errors are rendered, never hidden.
- **CI is minimal and hardened.** It runs on `pull_request` (not `pull_request_target`), with `permissions: contents: read`, `persist-credentials: false`, no secrets, actions pinned to full SHAs, and a 15-minute timeout. A fork PR cannot write anything or exfiltrate a secret, and its cache scope is the PR ref.
- **Layout guards are real.** The AST scan covers every member's `src/`, including `core`: `core` importing `ops_api` fails, because `top in ("ops_core","ops_core")` is false. The workspace-members test forces `MEMBERS` to stay in sync with the root pyproject.
- **Encoding discipline holds.** All scripts write with `encoding="utf-8", newline="\n"`, and the committed blobs are clean.
- **Pure helpers are tested at the edges.** `probe_stats` (Wilson, p95, summarize) has known-value tests, and thinking is counted as a failure, never stripped.

## Declined to judge

- **Live probe results and model pins:** the run is deliberately pending the owner's seal, and I was told not to run `probe.py`.
- **Holdout case content and the seal file:** the owner authors these off-machine (AM-50 custody).
- **The first GitHub Actions run and the push:** these are owner decisions (T06 step 7).
- **Whether the pinned SHAs really are `actions/checkout@v5` / `astral-sh/setup-uv@v6`:** checking needs network `git ls-remote`. The format is verified, and `pin_actions.py` reproduces it.
- **Behaviour and quality of the reference code:** it is byte-pinned delivered material, so it is out of scope.
- **Trust-boundary README wording for the six services:** the text is copied from the plan, and its fidelity to ADR-0003 is for T15/T47 to judge.
- **Security advisories for the versions in `uv.lock`:** I had no advisory database. The pins come from the plan.
- **What the Ollama server does when an asyncio-cancelled httpx request stops mid-generation:** settling it needs a live model, which is exactly what the probe will measure.
- **Plan-document defects ("Expected: 5 failed" in T42/T04 step 2):** these concern the accuracy of the plan text, not the code. The ledger already records them.

## Issues

### Critical (Must Fix)

None. No hash-pinned file was modified, no secret was committed, and the evidence I checked has no fabricated measurement.

### Important (Should Fix)

**I1. `scripts/verify_handoff.py:33-74`: the "nothing under `reference/` differs" invariant is not enforced. This is a plan-level defect from the T42 design.**

- **What:**
  - `--reference-code` checks only the 19 entries in `reference-code-hashes.json`.
  - `--manifest` now checks the committed manifest against the committed zip, which is a closed loop. It no longer reads the working tree.
  - So no check covers the 7 other delivered files under `reference/`: `Dockerfile`, `Makefile`, `compose.yaml`, `.dockerignore`, `pyproject.toml`, `scripts/init_demo.py`, `scripts/check_reference.sh`. Additions and deletions under `reference/` are not covered either.
- **Proven:** the tampering run above (modify, delete, add a `.py` under `reference/src/`) still exits 0.
- **Regression:** before T42, `--manifest` hashed those 7 files in the working tree.
- **Remap redirect:** a remap value can point anywhere inside the repo (`remap.get(..., default)` plus `within()`). Nothing asserts the remap targets live under `reference/`.
- **Why it matters:** the brief names this checker as the enforcement of a binding constraint. An injected file under `reference/src/` is executed when the reference suite is installed and run.
- **Fix:** in `check_reference_code` (or a new `--reference-tree`):
  1. Map each manifest entry that was moved (the git-mv list in plan T42 step 3) to `reference/<path>`, and compare the working-tree bytes with the zip member `operations-copilot/<path>`.
  2. Assert that the set of files under `reference/` (skipping `__pycache__`, `build`, `*.egg-info`) equals that mapped set plus `{reference/README.md}`.
  3. Assert that every remap value starts with `reference/`.
  4. Add a test that tampers a temporary copy, the way `test_manifest_check_fails_on_corrupted_zip` does.

**I2. `pyproject.toml:1-11` and `scripts/check.py:1`: on a fresh clone, the documented one command is RED. This is plan-level: the Global Constraints acknowledge it, but no user-facing doc says it.**

- **What:**
  - `uv run python scripts/check.py`, the "one command" (AM-01, check.py docstring), fails on a fresh clone with `ModuleNotFoundError: ops_core`. The cause is that a `package = false` root only syncs the dev group.
  - A plain `uv sync` (exact) after an `--all-packages` sync uninstalls the members again.
  - Only `ci.yml` knows to run `uv sync --locked --all-packages` first. No doc mentions it: README, START_HERE, AGENTS and the check.py docstring all lack it.
- **Why it matters:** an interviewer who clones and runs the advertised command sees RED, and so does the owner after a routine `uv sync`.
- **Fix (preferred):** make the virtual root depend on the members, so every default `uv sync`/`uv run` installs them:

  ```toml
  [project] dependencies = ["ops-core", "ops-api", "ops-worker", "ops-mcp-read", "ops-mcp-write", "ops-asset-sim", "ops-incident-sim"]
  [tool.uv.sources] ops-core = { workspace = true } …
  ```

  Then re-lock.
- **Fix (minimum):** have `check.py` probe `import ops_core` first and print `run: uv sync --locked --all-packages`. Also document this in the check.py docstring and START_HERE.

**I3. `scripts/probe.py:64-74,128,214`: VRAM is reported as a measurement when it is a default.**

- **What:**
  - `peak = max(peak, vram_mb() or 0)` renders `Peak VRAM (nvidia-smi) | 0 MB` when `nvidia-smi` is missing or fails.
  - Even when nvidia-smi works, the sample is whole-GPU `memory.used`, taken only after each call has finished. It is not a peak during generation.
- **Why it matters:** this conflicts with the binding "no measurements fabricated" constraint and with AM-31's "peak VRAM". The owner's R081 decision and T19's sizing will read this number. The probe has not run yet, so the fix is cheap now and expensive after the report is committed.
- **Fix:**
  - Keep `None` when no sample succeeded, and render `not measured (nvidia-smi unavailable)`.
  - Either sample in a background task during each call (for example every 0.5 s while `ainvoke` is pending), or relabel the row "max of post-call whole-GPU samples".
  - Record the GPU name and the sample count.

**I4. `scripts/probe.py:1,84`: the probe does not use AM-31's structured-output setting. This is plan-level: the plan's step code omits it too.**

- **What:**
  - AM-31's drafting profile is `reasoning=False … plus with_structured_output(method="json_schema")` plus application-side validation.
  - The probe calls plain `llm.ainvoke` with no JSON-schema constraint.
  - The JSON-valid and schema-valid rates therefore measure free-form compliance, not the profile the docstring says is measured ("Measure qwen3:8b for the drafting profile (AM-31)").
- **Why it matters:** AM-31 says the owner decides proceed / change model / adjust prompts from these rates. Measuring the wrong configuration can lead to the wrong decision.
- **Fix (preferred):** measure the AM-31 configuration, for example `llm.with_structured_output(schema, method="json_schema", include_raw=True)`, keeping the raw text for thinking detection. Optionally keep the free-form pass as a second column.
- **Fix (minimum):** state in the report header that structured output was not applied.
- Either way, do it before the live run.

**I5. `SESSION_STATE.md:5`, `STATUS.md`, `handoff/tasks.json`, `START_HERE.md:27,44,47`: the handoff state is stale, and START_HERE commands no longer work.**

- **What:**
  - `SESSION_STATE.md` still says "Next task: execute Plan A … T01".
  - The six tasks are `"status": "PLANNED"` in `tasks.json`.
  - START_HERE still lists `src/`, `tests/`, `integrations/` at the root.
  - START_HERE still tells readers to run `PYTHONPATH=src python -m operations_copilot.cli`, which now fails because `src/` moved.
  - START_HERE still says `--manifest` "will fail … until task T42".
  - AGENTS.md:17 requires STATUS.md and SESSION_STATE.md to be updated at slice end, with tasks, actual tests, skips, blockers and the next step. The plan's "After Plan A" section and T03 step 9 also require it.
- **Why it matters:** CLAUDE.md says to continue from SESSION_STATE.md, so the next session would restart at T01. The open owner inputs (holdout seal → live probe; push → first CI run) are recorded only in the untracked ledger.
- **Fix:** one docs commit before merge:
  - Set task statuses to the truth: T01/T42/T04 done; T03, T02 and T06 done except their owner steps.
  - Record `36 passed, 1 skipped (seal)`.
  - List the open owner inputs and the next step (Plan B/C writing).
  - Fix START_HERE: `cd reference && PYTHONPATH=src python -m operations_copilot.cli`, the `reference/` row, the `--manifest` sentence, and add `uv sync --locked --all-packages && uv run python scripts/check.py`.

### Minor (Nice to Have)

- **M1. `scripts/probe.py:231-240`: the seal gate checks only that the file exists.** A seal that is empty or malformed passes the gate. The prompt check compares against the constants in the script, yet the message says "!= sealed". The risk is low: once the seal exists, `test_holdout_seal_file_has_three_lines_and_prompt_hashes` covers it, but only if check.py runs before the probe. Fix: parse the seal; require 3 lines matching `^[0-9a-f]{64}  \S+$`, and require that lines 2-3 equal `EXPECTED[name]  name`. Otherwise exit 2 with a message saying which line failed.
- **M2. `scripts/probe.py:118-125,215`: thinking accounting has gaps.**
  - A repair output that contains `<think>` text is never counted as thinking; it only makes `repaired_ok` False.
  - The row "Thinking present in repair/repeat/post-cancel calls" counts only repeat and post-cancel metadata, because repair metadata is folded into the per-input row.
  - AM-31: "If thinking cannot be disabled, the probe fails."
  - Fix: count `classify_output(ftext) == "thinking_present"` for repairs and the `<think>` text in repeat outputs, and make the row labels match what is counted.
- **M3. `scripts/probe.py:171-182,217`: the cancel row measures something other than its label.** "Next call start after cancel" actually covers the `/api/ps` round-trip plus the complete "ok" generation, not start latency. AM-31 also asks for a GPU reading after cancel, and none is taken. Fix: time the first chunk via `astream`, keep `/api/ps` outside the timer, and record `vram_mb()` right after cancel.
- **M4. `scripts/probe_stats.py:41`: the cold row can show a timeout as a latency.** `cold_seconds` takes the first row even when it errored, so a 60 s timeout would be shown as cold-start latency. Fix: use the first row only when `error is None`, otherwise render the error.
- **M5. `scripts/probe.py:52`: the digest source conflicts with the spec.** The probe pins the digest from `/api/tags` and asserts that `/api/show` carries none. AM-31 says T19's worker compares the `/api/show` digest against the pin. Reconcile this in a spec errata note or in T19's review_notes before T19, or the fail-closed check will be designed against a field that does not exist.
- **M6. `scripts/check.py:8`: the mypy member list is hard-coded.** `MEMBER_SRC` duplicates the workspace member list, and nothing ties the two, so a new member would silently skip mypy. Fix: derive the list from `pyproject.toml` with `tomllib`, or add a test asserting equality.
- **M7. `scripts/gen_seed_ids.py:12` / `tests/plan_a/test_seed_ids.py`: a regenerated ID change would go unnoticed.** The drift guard cannot catch a change to the namespace string or to the `tenant/`/`user/` name format followed by regeneration. T05 (Keycloak realm) and T45 (fixtures) consume these IDs. Fix: add one golden assertion, for example `tenants.alpha == "3ea79c95-914c-52cb-9d10-c4e19dda8ff7"`, plus one persona ID. The namespace itself is stable: `uuid5(NAMESPACE_URL, "https://github.com/jschnepel/MLOps/seed")`.

## Deferred-minor triage

| Task | Deferred minor | Ruling | Reason |
|---|---|---|---|
| T1 | absolute venv path in `pytest-output.txt` | stays deferred | It is a verbatim capture (editing it would alter evidence) and not a secret. |
| T1 | README capture timestamp predates the re-capture | stays deferred | The README's `22:48:48Z` matches the T01 commit time (15:48:56 -0700) of the environment capture. Only the pytest re-capture is a minute later. |
| T1 | exit codes not in the committed evidence | stays deferred | The pytest summary line is the result. Worth adding next time evidence is captured. |
| T2 | em dash in `HOLDOUT.md` | stays deferred | The file is UTF-8 without BOM; this is cosmetic. |
| T2 | relative paths in the schema tests | stays deferred | Plan-mandated; pytest runs from the root (testpaths, CI). |
| T3 | drift guard compares parsed JSON, not bytes | stays deferred | The write tests cover LF/BOM, and `.gitattributes` normalizes. |
| T3 | loose bundle-shape assertions | stays deferred | The generator is deterministic and the committed file is guarded. |
| T3 | VRAM 0 reads as a measurement when nvidia-smi is absent | **fix before merge** | Promoted to I3: binding no-fabrication constraint; a 3-line change before the live run. |
| T3 | `ceil(0.95*n)` float risk | stays deferred (closed) | No mismatch for n=1..1000 (checked). |
| T3 | `probe.py` mixes helpers, loop and report | stays deferred | A structural preference; the pure parts already live in `probe_stats.py`. |
| T4 | cwd-relative paths in the checker tests | stays deferred | Plan-mandated and consistent with the testpaths. |
| T4 | malformed manifest line surfaces as a generic FAIL | stays deferred | It still fails closed: ValueError is caught and reported as `FAIL: …`. |
| T4 | corrupted-zip test exercises the mismatch branch, not the missing-member branch | stays deferred | Superseded by I1. Add a missing-member case when the I1 test is written. |
| T5 | relative-import branch skipped in the AST test | stays deferred | A relative import cannot reach another top-level package. |
| T5 | nothing guards the ruff exclude list | stays deferred | Low risk; see the ruling below. |
| T5 | `generate()` untyped in `scripts/` | stays deferred | `scripts/` is outside the mypy scope by plan. |
| T6 | cwd-relative workflow path in the tests | stays deferred | Plan-mandated. |
| T6 | tests do not enforce the `# vN` comment or `persist-credentials` | stays deferred | Adding `persist-credentials is False` to `test_token_is_read_only…` costs one line; recommended, not blocking. |
| T6 | verify_handoff step uses system `python3`, untested until the first run | stays deferred (mitigated) | I ran the checker under CPython 3.12 (the ubuntu-24.04 `python3`), and it passed. |

### Rulings

| Ruling | Verdict | Reason |
|---|---|---|
| Work on branch `plan-a` in this directory | sound | The external venv and owner commands assume this path. HEAD is on `plan-a` and the tree is clean. |
| Keep the plan's drift-guard tests | sound | They do catch hand edits. Add golden values for the seed IDs (M7), since external systems consume them. |
| Owner-only steps are non-blocking; seal test `skipif` | sound | Pytest stays honest (it shows 1 skip with its reason), and the probe still refuses to run without the seal. Tighten the gate's content check (M1). |
| Task 3 builds steps 1-8 and defers the live probe | sound | Matches AM-50 ordering (seal before probe). Nothing in Plan A consumes the pins. |
| Task 3 fixes three plan-mandated Important findings in `probe.py` | sound | The fixes are correct against AM-31: bounded calls, truthful wording, and thinking counted on all calls. The thinking count is incomplete for repair text (M2). |
| `[tool.ruff] extend-exclude = ["reference", "docs"]` | sound | `git ls-files docs` contains exactly one `.py`, `docs/diagrams/build_charts.py`, which is delivered material in the 1.0 manifest and should not be reformatted. Everything else is markdown, images, mermaid, HTML and JSON. Nothing repo-owned that needs lint lives under `docs/`. |
| Accept the S110 hand-fix (`contextlib.suppress`) in `probe.py` | sound | The semantics are identical, and the file is repository-owned. |

## The eight focused checks

1. **probe.py gate, timeouts, claims.**
   - It hard-fails (exit 2) before any network or model call when the seal is missing or a prompt hash differs.
   - A seal file that is present but malformed is **not** rejected (M1).
   - Every network call is bounded.
   - Report claims: the VRAM claim is not supported by what is measured (I3); the cancel row and the thinking-row labels say more than is measured (M2, M3); the "drafting profile" claim omits structured output (I4).
2. **verify_handoff.**
   - `--manifest` does verify against the zip, not the working tree.
   - `--reference-code` lets these slip past: modified non-hashed reference files, added files, deleted non-hashed files, and remap redirection (I1, demonstrated).
3. **Cross-import scan.** It covers all seven `src/` trees, and `core` → service imports are caught. Dynamic `importlib` imports escape it, which is expected of an AST scan.
4. **CI.** A fork PR has no write route and no secrets. `uv lock --check` passes, and the lock includes all members and the dev group. A fresh clone is RED without `--all-packages` (I2).
5. **Seed IDs.** The namespace is stable. A hand edit is caught; a regenerated generator change is not (M7).
6. **Reports.**
   - Every number in `reports/baseline/*` has a capture: `environment.json` from `baseline_env.py`, pytest summaries verbatim, CLI output verbatim.
   - No `reports/model-probe-*` file is committed.
   - The only "default read as a measurement" is in the pending probe code (I3).
7. **Encoding.** Clean across all 84 changed blobs.
8. **Ruff `docs` exclude.** Sound (see the rulings table).

## Recommendations

1. Fix I1 to I5 in one short follow-up round. I1, I3 and I4 are contained code changes. I2 is one pyproject change plus a re-lock. I5 is documentation.
2. Before the owner's live probe run, also apply M1 to M4. They are cheap, and they decide whether the committed probe report is accurate.
3. Record the M5 `/api/show` vs `/api/tags` discrepancy as a review_note on T19.

## Assessment

**Ready to merge?** With fixes

**Reasoning:** The core of the slice is sound: the reference bytes are intact, the workspace and CI are clean, and check.py is GREEN after sync. But the reference-integrity checker does not enforce the invariant it is relied on for (I1). The advertised one command is RED on a fresh clone (I2). The pending probe would commit a VRAM default as a measurement and would measure a non-AM-31 configuration (I3, I4). The handoff state still points the next session at T01 (I5).

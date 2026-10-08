# Adversarial review of Plan C (core contracts, schema alignment, traceability): rounds 1–2 (2026-10-08)

**Reviewed:** `docs/superpowers/plans/2026-10-08-first-slice-c-contracts-schemas.md` (T07, T45, T46) before execution. The planner had already run the plan's Tasks 1–4 code on scratch copies (ruff, mypy strict, 132 tests) before the round.

**Method:** the same two-critic gauntlet as Plans A and B — a static critic cross-checking every claim against the spec, pydantic and jsonschema behaviour (measured in the repo's environment) and a builder executing all nine tasks on a throwaway worktree.

**Round-1 verdicts:** static — 2 Blocking (the checker cannot import `scripts.*` under `python -I`; the traceability regex rejects empty table cells), 15 Important (among them real spec errors in the planner's transition table: the `BLOCKED_REVIEW` reason sets at freeze and decision were too wide, and the ABORTED-to-reason mapping ignored whether the request had been sent), 14 Minor; builder — EXECUTABLE WITH FIXES: 11 Blocking, 8 Misleading, 8 Risky, every task reachable with labelled workarounds, and the schema prose turned into a generator script that the controller adopted as the deliverable. The fixes are summarised in `docs/PROJECT_HISTORY.md`.

The reports below are the reviewers' text, unedited.

---

## Round 1 — static critic

# Plan C static review (adversarial, default UNPROVEN)

Plan: `docs/superpowers/plans/2026-10-08-first-slice-c-contracts-schemas.md` (2678 lines). "SA:n" = SPEC_AMENDMENTS.md line n, "BS:n" = BUILD_SPEC.md line n, "P:n" = plan line n.

Evidence method: read the authority texts; extracted every `Create <path>:` python block from the plan into the scratchpad (`x/pkg/ops_core`, `x/repo_like/...`) and ran read-only checks with the repo venv (Python 3.13.13, pydantic 2.13, jsonschema 4.26.0). Nothing in the repository was modified. Scripts: `extract.py`, `hashcheck.py`, `js.py`, `js2.py`, `conf.py`, `trace.py`, `probe_import.py`, `rufftest/`, `layout/`, `ids/` in this directory.

---

## Lens 1: Spec compliance

### T07 / T45 / T46 instruction and DoD coverage

| Claim | Verdict |
|---|---|
| T07 "canonical JSON v1" -> Task 1 | PROVEN (P:157-243; tests pass, 16) |
| T07 "transition table incl. creation row, ESCALATED, ABANDONED_UNVERIFIED, BLOCKED_REVIEW rows, slot rule" -> Task 2 | PROVEN (P:589-646; `test_table_matches_the_allowed_set_exactly` passes; 42 rows, 38 pairs reproduced) |
| T07 "runs.intent and requester-asserted supersedes_run_id **as run fields** (never from drafts)" | DENOUNCED. No `Run`/run-record contract exists; only the `Intent` enum (P:533) and `MessageRequest.supersedes_run_id` (P:1713). Needs a `RunFields`/`RunRecord` model (intent, supersedes_run_id, set only by create_run/create_revision) or an explicit `TODO(T09)` deferral. |
| T07 "shared reason enum" | PROVEN (P:509-521 = SA:152). |
| T07 "job-type model (AM-20.4 dedup keys)" | PROVEN for type/tools/states/creators/dedup (P:1030-1102 vs SA:340-346, SA:498-504). Gap: AM-15 says allowed tools derive from type **plus run state plus attempt state** (SA:338, SA:334, SA:345 "create_incident (INTENT only)"); JobRule has no attempt-state dimension and no `TODO(T15/T47)`. |
| T07 "tombstone object" | PROVEN (P:1232-1246 = SA:260). |
| T07 "supersedes_run_id in the hashed payload" | PROVEN (P:1869; `test_proposal_payload_and_hash` passes, hash changes). |
| T07 "state_version-only-on-transition defined here" | PROVEN as a trivial function (P:709-711); the test asserts `src is not dst`, which is structure, not behaviour. |
| T07 DoD "Property tests (Hypothesis) show ... authority fields rejected" | DENOUNCED. Authority rejection is a plain parametrize (P:1481-1491), not a Hypothesis property. Evidence needed: a `@given` test drawing field from `AUTHORITY_FIELDS`, depth (top/nested) and arbitrary JSON value. |
| T07 DoD "every allowed transition tested; every disallowed rejected" | PROVEN for pairs (P:393-404). Partial: for allowed pairs, wrong performers are not exhaustively rejected (only one spot check, P:411-413); disallowed pairs are only probed with `TRANSITION_RUN`. |
| T07 DoD "revision from BLOCKED_REVIEW needs a free slot" | PROVEN (P:439-446). |
| T07 DoD "the answer_only refusal is **in the table**" | DENOUNCED (weakly). It is a separate function `freeze_allowed` (P:703-706); `require_transition(DRAFTING, AWAITING_APPROVAL, FREEZE_PROPOSAL)` succeeds for an answer_only run, so a caller that forgets `freeze_allowed` passes R082's "one table". Fix: rows carry an `intent` guard or `require_transition` takes `intent`. |
| T07 DoD "draft containing supersedes_run_id fails" | PROVEN (P:1540; passes). |
| T45 "apply every AM-80 row" | Mostly PROVEN by prose (P:2227-2302); exceptions below (proposal-valid authored_by, fake-success, tool-result guards, evals row). |
| T45 / AM-80 SA:754 "**before writing contract code**, T45 commits at least one negative per row" | DENOUNCED. Plan order is T07 contract code (Tasks 1-4) then negatives (Task 6). tasks.json makes T45 depend on T07, so the spec contradicts itself; the plan neither follows SA:754 nor records this as a ruling. |
| T45 "update verify_handoff.py (renamed field, tools/ and evals/ meta-validation, UTF-8, reject CR)" | renamed field PROVEN (P:2348-2353); tools/ + evals/ PROVEN (P:2314); CR PROVEN (P:2319-2321); "UTF-8": governed files are read as bytes only, `.md`/`.txt` never decoded; no BOM check despite Global Constraint P:28. Partial. |
| T45 "evals/holdout-case.schema.json is T03's, tolerate absence" | PROVEN (glob tolerates absence). |
| T45 DoD "index.json version 1.3.3" | PROVEN (P:2304, P:2324). |
| T46 "58 tests mapped; owning task per replacement; ported tests pass" | DENOUNCED as executable: the row regex fails to parse 38/58 rows (see Lens 6). Content of dispositions otherwise PROVEN. |

### Transition table (Task 2) vs AM-10, AM-20.3 performers, SA:451

Every row checked. All 38 pairs are licensed by AM-10 (SA:132-143), BS §8 (BS:311-322) or the performer table (SA:478-490); no spec transition is missing given rulings 1, 4 and 5. Specific checks:

| Row / set | Verdict |
|---|---|
| Worker rows = SA:451 list exactly (QUEUED->RETRIEVING; RETRIEVING->DRAFTING/AWAITING_INPUT/INSUFFICIENT_EVIDENCE/FAILED; DRAFTING->AWAITING_INPUT/ANSWERED/INSUFFICIENT_EVIDENCE/FAILED; AWAITING_INPUT->QUEUED) | PROVEN (P:594-606) |
| No QUEUED->AWAITING_INPUT (ruling 4) | PROVEN consistent with SA:451, SA:481, SA:136 |
| Cancel from QUEUED..APPROVED + BLOCKED_REVIEW | PROVEN (SA:485 + SA:139 + BS:321) |
| expire_proposal AWAITING_APPROVAL/APPROVED -> BLOCKED_REVIEW(expired) | PROVEN (SA:457) |
| record_outcome from EXECUTING/OUTCOME_UNKNOWN/ESCALATED -> SUCCEEDED/FAILED; -> ESCALATED(conflict) | PROVEN (SA:464, SA:488-489) |
| escalate_run {conflict, escalation_deadline} | PROVEN (SA:468) |
| No row out of a terminal state (record_outcome makes no transition from terminal) | PROVEN (SA:128; test P:407) |
| **freeze_proposal DRAFTING->BLOCKED_REVIEW reasons = `_BLOCKED` (5 reasons)** | DENOUNCED. SA:137 and SA:150 name only `asset_action_unresolved` / `asset_incident_exists` at freeze; `expired`, `stale_evidence`, `authority_revoked` are grant-time reasons (SA:140). |
| **record_decision AWAITING_APPROVAL->BLOCKED_REVIEW reasons = `_BLOCKED`** | DENOUNCED. SA:454 has one blocking path, lazy expiry -> `expired`. |
| grant_execution APPROVED->BLOCKED_REVIEW reasons = `_BLOCKED` | PROVEN (SA:140, SA:150, SA:462) |
| FAILED via record_outcome = {cancelled_before_send, aborted_no_commit, rejected, expired} | PROVEN (SA:241, SA:280, SA:348, SA:465) |
| REJECTED = {rejected} | PROVEN (SA:152) |
| RETRIEVING/DRAFTING -> FAILED with **no** reason | UNPROVEN either way: SA:152 says terminal states carry a reason from the enum, but no enum value fits "exhausted infrastructure policy" (BS:315). Should be recorded as a ruling. |

### The five header rulings

| Ruling | Verdict |
|---|---|
| 1 AWAITING_APPROVAL -> QUEUED by create_revision | Sound (SA:455 and BS:317 include it; SA:484 omits). |
| 2 `expired` in FAILED_NO_COMMIT reasons | Sound (SA:348 is explicit: create_incident returns FAILED_NO_COMMIT(`expired`)). |
| 3 keep `lexical | vector_exact` | Questionable: AM wins over the 1.0 schemas (CLAUDE.md), so "the delivered schema" is not authority; SA:461 `mode=vector` is a **value**, not an "argument name" as P:16 says. Acceptable only if the translation point (mcp-read maps `vector_exact` -> SQL `vector`, or T09 accepts `vector_exact`) is written into T09/T17 notes. |
| 4 QUEUED -> RETRIEVING only | Sound (SA:451, SA:481, SA:136, AM-12 node list drops `resolve_context` SA:207). |
| 5 cancel from BLOCKED_REVIEW | Sound (SA:139, BS:321). |
| Recorded where the owner sees them | Partial: Task 9 puts them in tasks.json notes, SESSION_STATE and PROJECT_HISTORY, but P:2654 says "the four spec contradictions" (five rulings), Task 9 has no exact text, and two further rulings are unrecorded (AM-80 negatives-before-code ordering; reasonless FAILED from transition_run). |

---

## Lens 2: Canonical JSON v1 (Task 1) vs BS §6 (BS:252-256)

| Claim | Verdict |
|---|---|
| NFC on strings and keys | PROVEN (P:189, P:197; `hashcheck.py`: `{"é":1}` and `{"é":1}` give identical bytes) |
| **Duplicate keys rejected** | DENOUNCED for `canonical_json`: two distinct keys that NFC-normalise to the same key silently collapse, last wins (`hashcheck.py`: `{"é":1,"é":2}` -> `{"é":2}`). The hashed bytes then describe a different payload than the input. The same defect makes `test_round_trip_and_key_order_independence` latently flaky: `st.dictionaries(st.text())` can generate such a pair, and reversing the dict changes which value survives. Fix: raise `CanonicalizationError("duplicate key after NFC")`. |
| Floats rejected ("integers only") | PROVEN (parametrized tests pass; `1e2` is rejected by `parse_float`). |
| Non-finite rejected | PROVEN (`parse_constant`; `allow_nan=False`). |
| "documented stable array order" (BS:254) | DENOUNCED: nowhere documented. Arrays keep caller order, so `evidence_refs` order changes the hash. Also undocumented: the timestamp spelling inside the hash comes from pydantic (`…Z`, 6-digit fraction: `00.500000Z` measured), so a pydantic upgrade can change hashes. Both belong in the canonical v1 definition (module docstring and README). |
| Checker hash of `proposal-valid.json` unchanged | PROVEN: checker algorithm, plan `canonical_sha256`, model `canonical_dict()` and stored value all = `9d5c1fb0…4cf7`; payload is ASCII (`hashcheck.py`). |
| `model_dump(mode="json")` renders UTC as `…Z` | PROVEN (`+00:00`, `-00:00` and tz-aware inputs all emit `Z`; test passes). |
| `exclude_none=True` gives "absent and missing hash alike" | PROVEN by construction (only optional field is `supersedes_run_id`); note it also strips any future optional field silently. |

## Lens 3: Pydantic strict semantics (Tasks 3-4)

| Claim | Verdict |
|---|---|
| Python-mode constructions (`Receipt`, `Tombstone`, `ActionOutcome`) with datetime objects and enum members validate | PROVEN (8/8 pass) |
| `model_validate_json` accepts ISO strings for `AwareDatetime`, UUID strings for `UUID` in strict mode | PROVEN (98/98 contract tests pass) |
| `StringConstraints(strip_whitespace=True)` applies in strict mode | PROVEN (`" "` rejected) |
| `Field(ge=1, le=168)` on `int | None` rejects `True`, `1.5`, `"24"` | PROVEN |
| `extra="forbid"` holds on nested `MessageContext` | PROVEN (ClarificationReply/MessageRequest nested cases pass). Review Focus 1's wording ("every example", "`payload`/`data` sub-objects") overclaims: the test covers 8 request models only, none has `payload`/`data`. |
| PEP 695 `def load[M: BaseModel]` passes mypy strict | PROVEN (`mypy --strict`: "no issues found in 8 source files") |
| Schema/model agree on UTC spelling | DENOUNCED: `proposal` and `manual-proposal` schemas require `…Z$` (P:2241, P:2252) but `_utc` accepts `+00:00` (P:1686-1690) and the Task 4 fixture itself uses `+00:00` (P:1417). OpenAPI is generated from pydantic (BS:285), so the published contract and the schema disagree. The conformance test only feeds examples, so it cannot see this. |

## Lens 4: JSON Schema semantics (Task 6)

| Claim | Verdict |
|---|---|
| The prose specifies one correct file per schema | DENOUNCED. Ambiguities: (a) the guard of the replaced `create_incident`/`get_incident_receipt` data rules (currently `status ∈ [ok, unknown]`); if left, `status=outcome` data is never shape-checked; (b) the guard of the new `abort_incident` data rule; (c) where TOMBSTONE/RECEIPT live (`$defs` or copies); (d) the run-manifest "model_route != fake" encoding; (e) `job` per-type `run_states` are not constrained, though AM-80 SA:772 says "with allowed tools and run states". |
| `if` without `required` misfires | PROVEN harmless: every guarded property (`source`, `type`, `status`, `tool_name`, `kind`, `grant_exists`, `model_route`) is top-level `required`. |
| R083 probes enforced | PROVEN by reconstruction (`js.py`, `js2.py`): #1 `'receipt' is a required property`, #2 `$.type: 'action.granted' is not one of`, #4 `'SUCCEEDED' was expected`, model_summary `$.type: 'explanation.ready' was expected`. |
| `best_match` deterministic enough | Mostly PROVEN for single-error negatives (n=1 in every reconstruction). DENOUNCED for `outcome-invalid-fake-success.json` as delivered: after the schema change it has 4 errors and `best_match` returns `$: 'tombstone' is a required property`, not the stated `$.receipt: None is not of type 'object'`. Step 4 (P:2263-2270) does not update this file, so "tune the regex" (P:2304) would make the probe certify the wrong rule, exactly Review Focus 4's failure. Several stated regexes are unanchored alternations (#4 P:2280, #7 P:2283, #9 P:2285, #13 P:2289, #21 P:2297) that match regardless of path. |
| `date-time` gap closed by patterns | DENOUNCED. FormatChecker has no `date-time` checker (measured); `event.occurred_at: "yesterday"` validates (`js2.py`). P:2674 says tool inputs carry patterns, but P:2259 gives none; receipt `committed_at`, tombstone `decided_at`, tool-result `observed_at` have none. Fix: add `rfc3339-validator` (enables jsonschema's date-time) as a dev dependency, or the UTC pattern on every date-time. |
| proposal UTC pattern vs existing `proposal-valid.json` | PROVEN consistent (`…Z`). |
| `evals/holdout-case.schema.json` `$id` ("ops-copilot/evals/holdout-case") meta-validates | PROVEN (`check_schema` passes); new tool `$id` `urn:…:tools/…-input:1` also passes. |
| Existing examples conform after Step 4 | DENOUNCED: `proposal-valid.json` has no `authored_by`, the schema now requires it (P:2241), and Step 4 does not add it. Measured: `c.Proposal` rejects it (`authored_by: missing`). Task 7 P:2466 knows this, but Task 6 Step 7 expects a pass first. |
| event `source` rule completeness | Minor gap: `source=application` with `action.confirmed`/`action.failed` validates (`js2.py`), though SA:464 says these come only with `source=destination`; the code `event_rules_ok` has no `action.failed requires reason` rule (schema rule 6), so code and schema drift. |

## Lens 5: Checker changes

| Claim | Verdict |
|---|---|
| `governed` includes `.md` under data/handoff-fixtures; agrees with `test_text_hygiene.py` | PROVEN (suffix set includes `.md`; hygiene scans all tracked files, a superset). Governed scan also hits untracked files under `evals/` (none today). Governed set omits `tests/`, `core/` despite P:28. |
| Base checks importing `scripts.gen_fixture_meta` keep `python3 -I scripts/verify_handoff.py` working | **DENOUNCED (Blocking).** Under `-I` (safe_path) neither the script directory nor the repository root is on `sys.path`; the root is not an installed package (`tool.uv.package = false`). Measured: `.venv/Scripts/python.exe -I probe_import.py` -> `ModuleNotFoundError: No module named 'scripts'`. `ModuleNotFoundError` is not in the `__main__` except-tuple, so the checker dies with a traceback. This breaks `CHECKER` in every existing `tests/plan_a/test_verify_handoff.py` test (incl. `test_checker_skips_venv_dirs`), `_run_tree`, the new `_run_contracts`, CI, and Task 5 Step 5. Also `uv run python scripts/gen_fixture_meta.py` (P:2120) fails: `sys.path[0]` is `scripts/`, so `from scripts.gen_seed_ids import NS` raises (reproduced in `layout/`). `scripts/probe.py:36-38` already shows the fix: `sys.path.insert(0, str(ROOT))` before the import. |
| `-I` + `uv run` sees venv site-packages | PROVEN (jsonschema imports under `-I`; venv site-packages is not "user site"). |
| `_tracked_copy` includes new files | DENOUNCED. It copies `git ls-files` only (test file line 79). Tests run before each commit, so: Task 5's `meta.json` and `gen_fixture_meta.py` are absent from the copy (base check fails); Task 6's new examples and schemas are absent ("Missing example"); Task 8's `TRACEABILITY.md` is absent, and `check_reference_tree` requires every `TREE_REPO_OWNED` file to exist (verify_handoff.py:148). So the "Expected" lines at P:2156, P:2362/2367 and P:2637-2640 cannot hold. Fix: `git add` before the run steps, or have `_tracked_copy` also list `--others --exclude-standard`. |
| New checker tests read failure text from `r.stdout` | DENOUNCED. `check()` raises and `__main__` prints `FAIL:` to **stderr** (verify_handoff.py:357); 4 of 5 new tests (P:2192, 2203, 2211, 2221) assert on stdout and would fail. Fix: assert on `r.stdout + r.stderr`. |
| "Add `import re`" | `re` is already imported (verify_handoff.py:20); minor. |

## Lens 6: Traceability (Task 8)

| Claim | Verdict |
|---|---|
| 58 node ids rebuilt from AST + parametrize | PROVEN (`trace.py` -> 58; `integration/` correctly excluded: 11 + 47). |
| `'24'` renders `[24]`; no collision with `test_valid_hours[24]` | PROVEN (pytest `--collect-only` on a mirror in `ids/`). |
| Dispositions match inventory / AM-70 | PROVEN: 10 port / 46 replace-by / 2 drop; both drops cite AM-70 (SA:736) or reference-only UI; every owning task exists in tasks.json. |
| "port" targets exist | PROVEN (`test_invalid_hours_rejected`, `test_valid_hours`, `test_known_bytes_and_hash` exist in Tasks 1 and 4). |
| The row regex matches the table as written | **DENOUNCED (Blocking).** `ROW` (P:2506-2508) requires `" \| "` around each cell, so an empty cell (`| |`) never matches: 38 of 58 rows fail (every row with an empty reason, and both drops with empty target/task). `test_traceability_covers_all_58` fails. Fix: `\|\s*(?P<target>[^|]*?)\s*\|` style cells, and strip. |
| "37 functions = 47 cases" | Wording: test_control.py has 39 `def test_`; 37 plain + 2 parametrized. |

## Lens 7: Test design and hygiene

| Claim | Verdict |
|---|---|
| Measured counts 16/10/8/98 | PROVEN (132 passed in scratch). |
| Base `92 passed, 11 skipped` | PROVEN as recorded (STATUS.md:92); not re-run. |
| Totals 108/118/126/224 | PROVEN arithmetic; GREEN not reachable at Tasks 3-4 (ruff, below). 229/234 unreachable (Lens 5). |
| `ruff check` clean | DENOUNCED: in a mirrored layout with the repo `pyproject.toml`, `core/src/ops_core/contracts.py` and `outcomes.py` raise I001 (ruff treats `ops_core` as first-party inside its own package, so it must be a separate block after `pydantic`). `ruff format --check` clean. |
| Hypothesis cannot generate rejected inputs | PROVEN for floats (no float strategy); DENOUNCED for NFC-colliding keys (Lens 2). |
| Tests assert behaviour | Mostly; `bumps_state_version` and `test_version_is_one` are structural. |
| `test_section_hashes_follow_the_documented_rule` hygiene | Writes `scratch.md` into the repo cwd (P:2011) instead of `tmp_path`; the first test takes an unused `tmp_path`. |
| SA citations (spot-check) | 4 wrong: P:608 `SA:481` (freeze is SA:482); P:612 `SA:482` (decision row is SA:483); P:623 `SA:463` (grant is SA:462; 463 is mark_sent); P:607 `SA:149` (asset-guard refusals are SA:150). Correct: SA:134, 139, 143, 145, 151-154, 260, 280, 451, 454, 455, 457, 458, 464, 467-469, 771, 778. |
| `git add` covers created files | PROVEN (Task 6 `git add schemas` covers `schemas/tools/`, examples and `index.json`). |
| Task 9 with no code block | Acceptable for docs, but the five errata should be given verbatim; "four contradictions" (P:2654) contradicts "five rulings". |
| Docstrings per CODE_COMMENTS rule 9 | DENOUNCED: many public classes and functions lack docstrings (`RunState`, `TransitionRow`, `JobRule`, `Tool`, `JobType`, `Receipt`, `EventSource`, `EventType`, `MessageContext`, `ClarificationReply`, `RevisionRequest`, `CancelRequest`, `SourceSnapshot`, `ErrorCode`, route enums, `sha256_hex`, `server_for`, `generate`, `write_meta`). |
| No secret or authority leak | PROVEN (no tokens; authority fields only as rejection lists). |

### Outcome mapping (Task 3)

`outcome_from_destination(state, cancel_requested)` (P:1213-1219) is DENOUNCED:
- ABORTED after a cancel on a **SENT** attempt maps to `cancelled_before_send`, a false "never sent" claim. SA:152 limits it to "a cancel in INTENT"; SA:242 maps an ABORTED tombstone after SENT to `aborted_no_commit`.
- ABORTED from INTENT after the dispatch deadline maps to `aborted_no_commit`; SA:241 says `expired`.

The mapping needs the attempt state at abort plus the abort reason (`request_abort` reason, SA:465). The test (P:839-846) pins the wrong behaviour.

## Lens 8: Plan hygiene

- Counts contradict: Files line P:2171 "22 negative … 9 positive" vs Step 5's 25 and 10; Step 3 "ten new schemas" (8 top-level + 6 tools); P:2359 "Expected `25 JSON Schema documents`" while `evals/holdout-case.schema.json` exists (26).
- Review Focus 3 and 4 point to "Task 5" for CR/reason checks (they are Task 6).
- P:2364 cites `tests/plan_b/test_ci_workflow.py` (it is `tests/plan_a/`). Its substring assertion does still hold.
- Checker module docstring ("Default checks need only Python's standard library") and the CI comment above the step become false after Task 5; the plan does not update them.
- `gen_fixture_meta.generate` reads `data/seed-ids.json` relative to cwd while the checker passes `ROOT`-based paths.
- New README text (P:2144) says evidence rows carry the per-section hash, but `proposal-valid.json`, `evidence-valid.json` and `tool-search_procedures-valid.json` cite `ALPHA-INCIDENT:v2:review` with the whole-file hash `8bc76…` (measured section hash `62a909…`). No reconciliation or `TODO(T17)`.
- AM-80 row SA:765 (evals schemas) is not in P:2302's list of rows covered elsewhere.
- No nested-fence problems; Interfaces match code except `revision_allowed`'s keyword-only argument (trivial).

---

## Consolidated findings

### Blocking
1. **P:2129-2131, P:2120, P:2364: `scripts.gen_fixture_meta` cannot be imported under `python -I`, nor when run as a script.** This breaks every existing checker test, CI and Task 5 Step 3/5. Fix: in both scripts, `sys.path.insert(0, str(ROOT))` before the import (the `scripts/probe.py:36-38` pattern), or make the meta check stdlib-inline in verify_handoff. Run the generator as `uv run python -m scripts.gen_fixture_meta`, and add `ImportError` handling.
2. **P:2506-2508: the traceability regex rejects empty cells; 38/58 rows unparsed.** Fix: `^\|\s*`(?P<node>[^`]+)`\s*\|\s*(?P<disposition>port|replace-by|drop)\s*\|(?P<target>[^|]*)\|(?P<task>[^|]*)\|(?P<reason>[^|]*)\|$` plus `.strip()`.

### Important
1. P:2192/2203/2211/2221: failure text goes to stderr. Assert on `stdout + stderr`.
2. P:2147-2156, P:2356-2367, P:2629-2640: `_tracked_copy` omits uncommitted new files, so Tasks 5, 6 and 8 cannot be GREEN before commit. Stage the files first or include untracked non-ignored files.
3. P:2241 and P:2261-2270: `proposal-valid.json` needs `authored_by`, and `outcome-invalid-fake-success.json` needs `"tombstone": null, "reason": null`, otherwise best_match reports the tombstone. List both in Step 4.
4. P:1213-1219 and P:839-846: the outcome mapping mislabels SENT+cancel as `cancelled_before_send` and INTENT+deadline as `aborted_no_commit`. Key it on the attempt state at abort and the abort reason.
5. P:609-615: the reason sets for freeze -> BLOCKED_REVIEW should be {asset_action_unresolved, asset_incident_exists}, and record_decision -> BLOCKED_REVIEW should be {expired}.
6. P:192-198: an NFC key collision silently drops data, and the key-order property is latently flaky. Raise on collision and add a test.
7. Task 1: canonical v1 lacks the BS:254 "documented stable array order" and documentation of the timestamp format. Document both and pin them with tests.
8. P:1188-1192 and P:1641-1648: ruff I001 fires on `contracts.py` and `outcomes.py`. Put the `ops_core` imports in their own block after `pydantic`.
9. SA:754 vs the tasks.json T45->T07 dependency: the "negatives before contract code" contradiction is unrecorded. Add it as ruling 6, or commit the Task 6 negatives before Tasks 1-4.
10. T07: there are no run fields (`intent`, `supersedes_run_id`), the answer_only refusal sits outside the table, and authority rejection has no Hypothesis property. Add a run-fields contract, an intent guard in `require_transition`, and a `@given` authority test.
11. P:2241/2252 vs P:1686-1690: the schemas demand `Z` while the models accept `+00:00`. Pick one spelling for both.
12. P:2245: the guards for the create_incident/get_incident_receipt/abort data rules are unspecified. State `status ∈ [ok, outcome]`.
13. P:2674 vs P:2259 and the event schema: the date-time hole is open (`occurred_at: "yesterday"` validates). Add `rfc3339-validator` as a dev dependency, or patterns on every date-time.
14. P:2280/2283/2285/2289/2297: the reason_match alternations are unanchored. Group each alternation under its path anchor.
15. P:2144: the per-section-hash statement contradicts the examples' whole-file hash. Reword it ("from T17") or migrate the examples.

### Minor
- Count and label contradictions: P:2171, the Step 3 heading, P:2359, P:2654 ("four"), Review Focus 3/4 task numbers, P:2364 path, P:2487 "37 functions".
- SA citation errors: P:607, 608, 612, 623.
- Missing docstrings (CODE_COMMENTS rule 9).
- `scratch.md` written into the repo (P:2011); cwd-relative seed path in gen_fixture_meta.
- Stale checker docstring and CI comment; duplicate `import re` instruction.
- The governed set omits `tests/` and `core/`, and has no BOM check (P:28 vs P:2319).
- Event schema and code allow `source=application` for `action.confirmed`/`action.failed`; `action.failed requires reason` exists only in the schema.
- Review Focus 1 overclaims coverage.
- The exhaustive transition test probes disallowed pairs with one performer only; `bumps_state_version` is a tautology test.
- R082 "and logged" is not addressed and has no TODO.
- JobRule has no attempt-state dimension (AM-15) and no TODO; `job.schema` has no per-type `run_states`.
- AM-80 evals row (SA:765) is not listed as deferred.
- Reasonless FAILED from transition_run is not recorded as a ruling.
- Task 9 gives no exact errata text and does not touch acceptance-matrix evidence fields.
- Ruling 3 wording.

## Declined to judge
- Whether `scripts/check.py` is GREEN today: I did not run it, because its tests create files in the repo. Taken from STATUS.md:92.
- Exact `best_match` output on the final schemas: they exist only as prose, so I reconstructed them from the plan text (`js.py`, `js2.py`).
- How likely Hypothesis is to hit an NFC key collision within 200 examples. The bug is proven; how often it causes a flaky failure is not.
- GitHub-runner behaviour of `uv run python -I` beyond the local measurement. The import failure is platform-independent Python semantics.

---

## Round 1 — builder dry-run

# Plan C dry-run: builder report

Plan: `docs/superpowers/plans/2026-10-08-first-slice-c-contracts-schemas.md` (2,678 lines). Executed literally in a detached
worktree of `plan-b` (af17395) at `scratchpad/planc-dryrun`, Git Bash on Windows 11, `uv sync --locked`, the venv's Python 3.13,
jsonschema 4.26.0. Baseline `scripts/check.py`: `92 passed, 11 skipped`, GREEN (matches the plan).

**Verdict: EXECUTABLE WITH FIXES.** I found 11 Blocking, 8 Misleading and 8 Risky items. After the labelled workarounds below, every task ends GREEN with
the plan's totals (224, 229 and 234), and Tasks 7 and 8 match the plan's formulas (281/29 and 284/29).

## Execution log

| Step | Expected (plan) | Actual | Verdict |
|---|---|---|---|
| 1.3 RED | ModuleNotFoundError ops_core.canonical, 1 error | same | PROVEN |
| 1.5 | 16 passed; mypy 3 files; 108/11 GREEN | 16 passed; `Success: no issues found in 3 source files`; 108 passed, 11 skipped, GREEN | PROVEN |
| 2.2 RED | 1 error | 1 error (ModuleNotFoundError) | PROVEN |
| 2.4 | 10 passed; mypy 4; 118/11 GREEN | 10 passed; 4 files; 118/11 GREEN | PROVEN |
| 3.2 RED | 1 error | 1 error | PROVEN |
| 3.6 | 8 passed; mypy 7; 126/11 GREEN | 8 passed; 7 files; 126 passed/11 skipped, **CHECK: RED**: ruff I001 in `core/src/ops_core/outcomes.py` | **BLOCKING** |
| 4.2 RED | 1 error | 1 error | PROVEN |
| 4.4 | 98 passed; mypy 8; 224/11 GREEN | 98 passed; 8 files; 224/11, **CHECK: RED**: ruff I001 in `contracts.py` (and outcomes.py) | **BLOCKING** (GREEN after `ruff check --fix`) |
| 5.2 RED | ImportError gen_fixture_meta, 1 error | same | PROVEN |
| 5.3 | prints path, `3 N`, three alert lines | **`ModuleNotFoundError: No module named 'scripts'`** for `uv run python scripts/gen_fixture_meta.py`. With `python -m scripts.gen_fixture_meta`: `data\handoff-fixtures\meta.json`, `3 10`, A17-alert-001 `cfa4e790-6f70-5e49-b73f-e9e8d613f52e`, A17-alert-002 `8fd07823-d6b4-5ffc-a691-3bba680494e1`, A17-old-001 `4f165b6c-3bda-5839-a401-6be0086b9dfc` | **BLOCKING** |
| 5.5 tests | 5 passed | 5 passed | PROVEN |
| 5.5 checker | PASS lines, `fixture meta.json current` | **traceback `ModuleNotFoundError: No module named 'scripts'`** (uncaught, not a FAIL line) | **BLOCKING** |
| 5.5 check | 229/11 GREEN | as written: ruff I001 + format failure; **9 failed, 220 passed**. With the sys.path fix and before `git add`: 5 failed (tracked-copy tests), 224 passed. After `git add`: 229/11 GREEN | **BLOCKING** |
| 6.1 RED | 5 failed | 5 failed | PROVEN |
| 6.7 checker | `PASS: 25 …; 30 …; 34 …` | first run: `FAIL: Valid example schemas/examples/proposal-valid.json failed: ["'authored_by' is a required property"]`. After the fixes: **`PASS: 26 JSON Schema documents; 30 accepted examples; 34 negative examples failed for their stated reason; governed files LF-only`** | **BLOCKING** (proposal-valid, fake-success, decision regex); **MISLEADING** (25 vs 26) |
| 6.7 tests | 5 passed | unstaged: 5 failed; staged: 4 failed (stderr) then 1 failed (Windows CRLF); after both fixes: 5 passed | **BLOCKING** |
| 6.7 check | 234/11 GREEN | after `ruff format` and staging: 234/11 GREEN | PROVEN with fixes |
| 7.2 | N+M = 65 | **47 passed, 18 skipped** (= 65), no failures | PROVEN |
| 7.2 check | 234+N / 11+M | 281 passed / 29 skipped GREEN | PROVEN |
| 8.1 RED | 1 failed, 1 passed | 1 failed, 1 passed | PROVEN |
| 8.2 | test passes with the 58 rows | **fails**: the ROW regex matches only 20 of 58 rows | **BLOCKING** |
| 8.3 checker | all PASS incl. `26 delivered reference/ files` | PASS (after the TREE_REPO_OWNED edit; before it: `FAIL: unexpected file: reference/TRACEABILITY.md`, as expected) | PROVEN |
| 8.3 tests | all passed | before `git add`: 2 failed (tracked copy lacks TRACEABILITY.md, which is now *required*); after: 18 passed | Risky/Blocking (staging order) |
| 8.3 check | T7 + 2 + 0/1 | 284/29 GREEN (281 + 2 + 1 new tree test) | PROVEN |
| 9.1 | same totals as T8, GREEN | 284/29 GREEN | PROVEN |

`git status --short` after each `git add` showed only the plan's paths, plus the untracked plan-file copy.

## Blocking

1. **T3.6 / T4.4: ruff I001.** Inside `core/src`, ruff treats `ops_core` as first-party, so `from pydantic import …` must come before `from ops_core…` (with a blank line between) in `outcomes.py` and `contracts.py`. The test files are fine because `ops_core` is third-party there. The planner's "ruff clean" claim is wrong for these two files. Fix: reorder both import blocks.
2. **T5.3: the generator cannot run as written.** `uv run python scripts/gen_fixture_meta.py` puts `scripts/` on `sys.path`, not the repo root. Fix: `uv run python -m scripts.gen_fixture_meta` (and update its Usage docstring), or add a sys.path insert.
3. **T5.4/5.5 and T6.7 CI: the base-check import fails under `-I`.** `uv run` does **not** put the repo root on `sys.path`: `uv run python -I -c "import scripts"` raises ModuleNotFoundError. The workspace root is `package = false`, and the only `.pth` files are the members' `src` dirs. `-I` drops both the script dir and the cwd. Result: the checker crashes with a traceback (ModuleNotFoundError is not in `__main__`'s caught tuple). 9 existing tests in `tests/plan_a/test_verify_handoff.py` fail, because they run `sys.executable -I scripts/verify_handoff.py`. The new CI line would fail the same way. Fix (applied): `sys.path.insert(0, str(ROOT))` before the import, as `scripts/probe.py` already does. The plan's claim that "`uv run` provides `scripts.*`, `-I` keeps isolation" is false.
4. **T5.5, T6.7, T8.3: staging order.** `_tracked_copy` copies `git ls-files`, so new files are absent from the copies until `git add`. The plan runs the checks before the commit step:
   - Task 5: 5 tree tests fail (meta.json and gen_fixture_meta.py missing).
   - Task 6: `test_contracts_pass_on_the_committed_tree` fails.
   - Task 8: two tests fail, because TREE_REPO_OWNED makes TRACEABILITY.md *required*.
   Fix: `git add` the task's paths before its check run.
5. **T6.4: `proposal-valid.json` is not in the update list.** Step 2 makes `authored_by` required, so `--contracts` fails on the first valid example. Fix: add top-level `"authored_by": ["00000000-0000-4000-8000-000000000011"]` (outside the payload, so the hash is unchanged).
6. **T6.4: `outcome-invalid-fake-success.json` is not in the update list.** It still has `reason: ""` and no `tombstone`, so best_match is `$: 'tombstone' is a required property` (4 errors) and it fails for the wrong reason. Fix: add `"tombstone": null, "reason": null`. It then fails only on `$.receipt: None is not of type 'object'`.
7. **T6.5 #22: wrong regex for `decision-invalid-old-hash-field`.** The example has two inherent errors, and best_match is `$: Additional properties are not allowed ('payload_sha256' was unexpected)`. The plan's regex `'expected_payload_sha256' is a required property` does not match. A regex that works: `Additional properties are not allowed \('payload_sha256'|'expected_payload_sha256' is a required property`.
8. **T6.1: the checker tests read only `r.stdout`.** `verify_handoff.py` prints `FAIL:` to **stderr** (the `__main__` handler), so 4 of the 5 tests fail. Fix (applied): the helper uses `stdout=PIPE, stderr=STDOUT`. Alternatively, assert on `stdout + stderr`.
9. **T6.1: CRLF on Windows.** `test_contracts_fail_when_a_negative_example_validates` rewrites the file with `write_text(..., encoding="utf-8")` and no `newline="\n"`, which produces CRLF on Windows. The CR check then fires first and the output is `FAIL: carriage return in governed file …` instead of "validated". Fix: `newline="\n"`.
10. **T5.4 and T6.6: pasted checker code is not ruff-formatted.** Lines run past 120 columns (the long `check(...)`, the `governed` comprehension, the alert-count check). `ruff format --check` fails and check.py is RED. Task 5's local import also trips I001. Fix: run `ruff format` and paste the formatted code (`# noqa: I001` or an import placement that ruff accepts).
11. **T8.1: the ROW regex misses 38 of 58 rows.** ` \| (?P<reason>[^|]*) \|$` needs two spaces for an empty cell (`|  |`), but every row with an empty Reason, or empty Target/Task for the drops, is written `| |`. The 20 rows with non-empty cells match; 38 do not. Fix (applied): `\|(?P<target>[^|]*)\|(?P<task>[^|]*)\|(?P<reason>[^|]*)\|$`. The cells are already `.strip()`ed. Port count 10, replace-by 46, drop 2: confirmed.

## Misleading

1. **T6 Files vs Steps: counts disagree.**
   - The Files list says "22 negative examples … and 9 positive examples"; Step 5 lists 25 negatives and 10 positives.
   - Step 3 says "Create the ten new schemas" but lists 8 top-level schemas plus 6 tool inputs (14 files).
2. **T6.7: schema count.** The expected line says `25 JSON Schema documents`. The real count is **26**: `evals/holdout-case.schema.json` exists on plan-b. The plan's own parenthesis admits it.
3. **T6.6: `import re` is already imported** in `verify_handoff.py`. Adding it again triggers ruff F811.
4. **T5.5 and T6.7 notes: false isolation claim.** "`uv run` is needed … `-I` keeps the isolation" and "`uv run` provides both": false (see Blocking 3).
5. **Coverage notes: two claims the steps don't deliver.**
   - "Known limitation recorded in the checker's PASS line": the PASS line in Step 6 does not mention the FormatChecker or date-time limitation.
   - "timestamps … constrained by regex patterns in … tool inputs": Step 3 gives the tool inputs plain `date-time` with no pattern.
6. **T9: the history entry is under-specified and inconsistent.**
   - "PROJECT_HISTORY §18 entry": §18 already exists ("What the process taught").
   - "the four spec contradictions" vs the header's five rulings, each "noted in docs/PROJECT_HISTORY.md". Ruling 5 is a reading, not a contradiction, so say which.
7. **T5.4: odd separator.** Appending ` ; fixture meta.json current` gives `6 SVG XML files ; fixture meta.json current` (stray space before `;`).
8. **T6.4 "event-invalid-model-success.json: unchanged".** It still passes for its stated reason, but it now has **6** errors: the flat `receipt_id`/`incident_id` are now additional properties. It is no longer a single-violation probe.

## Risky

1. **`gen_fixture_meta.generate(root)` depends on the cwd.** It reads `Path("data/seed-ids.json")` relative to the cwd, not to `root`. The checker resolves everything else from `ROOT`, so running it from another cwd raises FileNotFound. Derive the path from `root` (`root.parents[1] / "data/seed-ids.json"`) or from ROOT.
2. **Several negatives pass only through best_match ranking.**
   - Multi-error probes: tool-invalid-read-tool-outcome (3 errors, needs the regex alternation), tool-invalid-outcome-no-action-id (2), outcome-invalid-failed-reason (2), outcome-invalid-committed-tombstone (2), run-manifest-invalid-model-route (2), decision-invalid-old-hash-field (2, inherent) and event-invalid-model-success (6).
   - A jsonschema upgrade that changes the relevance heuristics can flip these.
3. **Schema and model diverge outside the examples.** The conformance test passes only because no example probes these; the probes I ran:

   | Probe | Schema | Model | Spec-wrong side |
   |---|---|---|---|
   | proposal/manual-proposal `+00:00` offset | reject (Z-only pattern) | accept (`_utc` accepts `+00:00`) | depends whether "UTC-only" means a Z spelling or a zero offset; pick one |
   | inverted interval | accept | reject | stated code-only rule (OK) |
   | blank `text`, blank draft `question`, blank `ModelPins.model` | accept | reject | the schema is laxer (strip_whitespace) |
   | explicit `null` for optional `hours`, `question`, `reason`, `feedback.text`, `clarification.asset_id` | reject | accept | pydantic `X \| None = None` accepts null; the contract (schema) is right |
   | event `action.failed` without `reason` | reject (rule 6) | accept (`event_rules_ok` lacks the rule) | code is wrong per AM-80 |
   | `explanation.ready` from model_summary with `{}` or extra keys | reject | accept | code is laxer |
   | `action.late_evidence` with `outcome: SUCCEEDED` and only a tombstone | accept | accept | semantic hole in both |

4. **Two hash procedures.** `Proposal._hash_matches` hashes pydantic's re-serialisation, so a payload spelled `…12:00:00.000Z` verifies with the same hash although its bytes differ. The base checker hashes the raw JSON payload. AM-13 says the destination hashes the bytes it receives.
5. **Unspecified envelope guard.** The plan never says which envelope statuses guard the write-tool data rules (create_incident / get_incident_receipt / abort_incident). I chose `status ∈ {ok, outcome}`.
6. **TRACEABILITY.md becomes required.** Adding it to `TREE_REPO_OWNED` makes `--reference-tree` FAIL if the file is missing (`missing: reference/TRACEABILITY.md`). That is consistent, but unstated.
7. **Ordering differs from AM-80.** AM-80 says T45 commits negatives "before writing contract code"; the plan writes code (Tasks 1–4) first. `tasks.json` (T45 depends on T07) backs the plan, so record which source wins.
8. **CI now runs the checker under `uv run`.** Correct only with Blocking-3's fix. The ubuntu runner behaves the same (`-I` semantics).

## Answers 1–8

1. **Tasks 1–4.** Per-file totals 16/10/8/98 and check totals 108/118/126/224 with 11 skipped all match. mypy strict is clean (3/4/7/8 source files). `ruff format --check` is clean on every pasted file. **`ruff check` fails (I001) on outcomes.py and contracts.py**, so check.py is RED at Tasks 3 and 4.
2. **Task 5.**
   - `scripts.gen_seed_ids.NS` exists with that spelling (`NS = uuid.uuid5(uuid.NAMESPACE_URL, "https://github.com/jschnepel/MLOps/seed")`).
   - 10 sections across the 8 documents (catalog sections ⊆ meta), 3 alerts.
   - The script fails when run by path.
   - `uv run python -I scripts/verify_handoff.py --reference-code --manifest` **fails** (ModuleNotFoundError) until the repo root is inserted on sys.path. The Task 6 CI command fails the same way.
   - With the fix, all PASS, with suffix `fixture meta.json current`.
3. **Task 6.**
   - `--contracts`: **26 / 30 / 34** (plan: 25 / 30 / 34).
   - Negatives whose stated `reason_match` failed: decision-invalid-old-hash-field (working regex above). Two examples needed content fixes the plan omitted (proposal-valid, outcome-invalid-fake-success). Every other plan regex matched as written (including the ones with alternations).
   - R083 probes, all failing for the right reason:
     - `tool-invalid-ok-unknown` → `$.data.status: 'SUCCEEDED' was expected` (rule d; 1 error).
     - `event-invalid-model-success` → `$.type: 'explanation.ready' was expected` (6 errors).
     - `event-invalid-confirmed-no-receipt` → `$.payload: 'receipt' is a required property` (1 error; it validated with 0 errors under the plan-b schema, which is "the R083 probe that validated before").
     - `tool-invalid-outcome-no-action-id` → `$.data: 'action_id' is a required property` (2 errors).
   - The five checker tests are 5 passed after the stderr, newline and staging fixes.
4. **Task 7.** 47 passed + 18 skipped = 65 (12 tool envelopes, 2 tool inputs, 2 job, 1 route, 1 evidence skipped). No verdict disagreement on the 64 examples. The latent divergences are in Risky 3.
5. **Task 8.**
   - The AST rebuild yields exactly the 58 ids that `pytest --collect-only -q` prints (external venv `%LOCALAPPDATA%\ops-ref-venv`, run on a copy of reference/). The diff is empty both ways.
   - pytest renders the string `'24'` as `[24]`, the same as the int, but `test_invalid_hours[24]` and `test_valid_hours[24]` are different functions, so there is no collision. `[None]`, `[0]`, `[True]`, `[1.5]`, `[-1]` all match.
   - The ROW regex fails 38 of 58 rows (Blocking 11).
   - `--reference-tree` accepts the file after the TREE_REPO_OWNED change: `PASS: 26 delivered reference/ files byte-identical …`.
6. **Task 9.**
   - The plan *instructs* carrying the five rulings (tasks.json, SESSION_STATE) and the FormatChecker limitation (PROJECT_HISTORY).
   - PROJECT_HISTORY says "four contradictions" (vs five rulings), and §18 is already taken.
   - The FormatChecker note is promised "in the checker's PASS line" but is not there.
   - I executed it with reasonable text: still 284/29 GREEN.
7. **After each task.** `ruff check`: RED after T3, T4 and T5 as written; format RED after T5 and T6 as written. check.py: T1 108/11, T2 118/11, T3 126/11 RED, T4 224/11 RED, T5 220 passed + 9 failed RED (as written) → 229/11 with fixes, T6 234/11 (fixed), T7 281/29, T8 284/29, T9 284/29.
8. **What else a fresh engineer trips on.**
   - The staging-order dependency of `_tracked_copy` tests (unstated, repeats in three tasks).
   - The checker printing FAIL to stderr.
   - Windows CRLF from `write_text` in tests.
   - `uv run` not providing `scripts.*`.
   - The cwd-relative paths in gen_fixture_meta.
   - Task 6 gives only prose for about 14 schemas and 35 example files, so the engineer has to write a generator. The engineer also needs Task 5's UUIDs and must find the two example updates the plan omits.

## Ambiguities resolved while writing the schemas from prose

1. **Write-tool data rules.** Their envelope guard is not stated; I used `status ∈ ["ok","outcome"]` for create_incident, get_incident_receipt and abort_incident.
2. **action-outcome allOf.** Written as three if/then rules on `status`: const SUCCEEDED; const FAILED_NO_COMMIT; enum [UNKNOWN, CONFLICT]. No `else`.
3. **FAILED_NO_COMMIT reason.** Written as `{"type":"string","enum":[4 reasons]}` (the plan says "the enum (`{"type":"string"}` not null)").
4. **abort_incident data.** One if/then/else on `outcome` (SUCCEEDED → receipt object + tombstone null; else tombstone object + receipt null).
5. **Read-tool data rules.** Their old `status ∈ [ok, unknown]` guard became `const ok`. The `next_cursor` property was added to get_recent_alerts data and to its `required`.
6. **event rule (1).** Kept verbatim (model_summary ⇒ type const explanation.ready and a closed payload {message (required), evidence_refs}).
7. **TOMBSTONE in event payload.** The same object as in action-outcome (state enum ABORTED/REJECTED).
8. **run-manifest rule.** `if model_route not const fake then model_digest type string`.
9. **job per-type rules.** `if type in maintenance(4) then allowed_tools maxItems 0, run_states maxItems 0`; `investigate/resume_input` → items enum of the read tools; `recover` → items enum of the write tools; `execute` → `const ["create_incident"]`.
10. **cancel-response rule.** `if grant_exists const false then attempt_state type null`.
11. **route schema.** Kept `required: []` plus `minProperties: 1` literally.
12. **Tool-input `$id`/title.** `$id` `urn:operations-copilot:schema:tools/<tool>-input:1`; I chose the title `Operations Copilot tool input <tool> v1` (the plan's generic title template uses `<name>`).
13. **Tool-input timestamps.** get_recent_alerts `start_at`/`end_at` are date-time only, without the UTC pattern (Step 3), which contradicts the coverage notes.
14. **Example values the prose leaves open.**
    - `authored_by` UUID `…0011`.
    - Tombstone reason text "cancelled before send".
    - job-valid `created_by` `["mark_unknown","worker","reclaim_leases"]`.
    - model-pins `ollama_version` "0.12.3".
    - The `event-valid` receipt keeps receipt/incident ids with `committed_at` 2026-10-06T12:00:05Z, as the plan says. That time is earlier than outcome-success's 12:04:00Z, so the examples disagree on the commit time.
15. **Negative example bodies.** Each is derived from a valid example with one change, where possible.
16. **Index notes for new entries.** They reuse "Synthetic target contract example; not a live result."
17. **Reasons for the 9 old negatives.** Taken from the plan's list; regexes as given (all matched once fake-success was fixed).

## Workarounds applied (all labelled in the scratch commits; none in the real repo)

- `ruff check --fix` on outcomes.py and contracts.py (commit "WORKAROUND: ruff isort").
- `python -m scripts.gen_fixture_meta` instead of the path form.
- `sys.path.insert(0, str(ROOT))` plus `# noqa: I001` before the local import in `verify_handoff.py`; `ruff format` on `verify_handoff.py` in Tasks 5 and 6.
- Example fixes: `authored_by` added to proposal-valid; tombstone/reason null added to outcome-invalid-fake-success; the decision-invalid-old-hash-field regex replaced.
- `_run_contracts` merges stderr into stdout; `newline="\n"` in the "validates" test.
- The ROW regex loosened for empty cells.
- `git add` before each task's check run.

## Produced artifacts

`planc-review/produced/` holds:
- the full `schemas/` tree (26 schema docs incl. 6 tools, 64 index entries);
- `reference/TRACEABILITY.md`;
- `data/handoff-fixtures/meta.json`;
- the fixed `scripts/verify_handoff.py`, `scripts/gen_fixture_meta.py`, `tests/plan_a/test_verify_handoff.py` and `tests/plan_c/test_traceability.py`;
- `build_schemas.py`, the generator that writes every schema, example and the index from the prose;
- `workaround-and-plan-diffs.patch`.

## Cleanup

See the final reply: the worktree is removed and pruned, `git worktree list` shows only the main checkout, and the real repo's `git status --short` is unchanged (one untracked plan file).

---

**Round-2 verdicts (after the fix pass):** static — 29 of 31 round-1 findings addressed, 2 partially, 0 Blocking, 2 Important (ruling-6 wording inconsistent in four places; an NFC-collision test that depended on an invisible combining character), 9 Minor, READY TO EXECUTE; builder — EXECUTABLE WITH FIXES: 0 Blocking, 6 Misleading, 4 Risky, every task reaching its stated totals (`291 passed, 29 skipped`, `--contracts` 26/30/36). The residual text fixes were applied before execution.

## Round 2 — static re-review

# Plan C static re-review, round 2 (adversarial, default UNPROVEN)

Plan: `docs/superpowers/plans/2026-10-08-first-slice-c-contracts-schemas.md` (4,497 lines). "P:n" = plan line, "SA:n" = SPEC_AMENDMENTS.md line.

## Evidence method

Nothing in the repository was modified. In `planc-review/r2/` I did the following:
- `git archive HEAD` of branch `plan-c` into `tree/`.
- Extracted the 16 `Create` blocks with `extract2.py`, plus `TRACEABILITY.md`.
- Applied the plan's non-Create edits (checker Steps 4/5, `TREE_REPO_OWNED`, the checker tests) with `patch.py`.
- Ran `gen_fixture_meta` and `build_schemas`, with `rfc3339-validator` installed into `r2/extra` and a scratch `venv`. `git init` + `git add -A` was run only in the scratch tree.

Measured results:
- Generator: `25 schema documents (19 contracts, 6 tool inputs); 66 examples (30 valid, 36 invalid); index.json version 1.3.3`.
- `ruff check` / `ruff format --check`: clean on the extracted files.
- `mypy core/src`: `Success: no issues found in 8 source files`.
- `pytest tests/plan_c`: `193 passed, 18 skipped`. That is 17+9+8+101+5+2+49+2; the 18 skips match P:4251.
- `--contracts` (with rfc3339-validator): `PASS: 26 JSON Schema documents; 30 accepted examples; 36 negative examples failed for their stated reason; governed files LF-only`.
- `--contracts` under `-I` without rfc3339-validator: fails closed (`event-invalid-occurred-at.json validated`).
- `tests/plan_a/test_verify_handoff.py`: `16 passed`.
- `val.py`, checking every generated schema:
  - every schema meta-validates;
  - no duplicate `$id`;
  - no object with `properties` lacks `additionalProperties:false`;
  - all 30 positives validate;
  - all 36 negatives match their `reason_match`.
- Against delivered HEAD: 8 schemas, 12 examples and the index differ; 3 schemas and 17 examples are byte-identical, exactly as P:2430 states.
- `proposal-valid.json`:
  - payload identical to 1.0;
  - `canonical_sha256` = `9d5c1fb0…4cf7`;
  - `c.Proposal` accepts it;
  - `evidence_refs` is sorted, with one snapshot;
  - `authored_by` is alex `2fc05986-…`, matching `data/seed-ids.json`.

## 1. Round-1 verdict table

| # | Round-1 finding | Verdict | Proof |
|---|---|---|---|
| B1 | `scripts.*` not importable under `python -I` | ADDRESSED | P:2367-2375 inserts `sys.path` after `ROOT` (the probe.py pattern); P:32; P:2276-2278 runs it with `-m`. Measured: `python -I scripts/verify_handoff.py` imports `gen_fixture_meta` and prints `fixture meta.json current`. |
| B2 | Traceability regex rejects empty cells | ADDRESSED | P:4293-4296 plus `.strip()` at P:4322. Measured: `test_traceability` passes (58 rows; 10/46/2). |
| I1 | Checker FAIL goes to stderr | ADDRESSED | P:2455, 2465, 2477, 2485, 2495 assert on `stdout + stderr`. 16/16 pass. |
| I2 | `_tracked_copy` misses new files | ADDRESSED | P:33; staging steps at P:2401-2406, P:4133-4138, P:4437-4440. |
| I3 | `proposal-valid` `authored_by`; fake-success shape | ADDRESSED | P:3474. `outcome()` P:3406-3415 always emits `tombstone`/`reason`. Measured: fake-success has 1 error, `$.receipt: None is not of type 'object'`. |
| I4 | Outcome mapping mislabels SENT+cancel and INTENT+deadline | ADDRESSED | P:1328-1350. Test P:895-923 covers every `sent` × `cancel` combination. Matches SA:229, SA:241, SA:242 and SA:280 (as amended by ruling 2). |
| I5 | Reason sets for freeze and record_decision → BLOCKED_REVIEW | ADDRESSED | P:620-628, P:654, P:662, P:664, P:669. Tests P:457-473 (freeze+EXPIRED rejected; record_decision+STALE_EVIDENCE rejected). |
| I6 | NFC key collision merges silently | ADDRESSED | P:216-218; test P:127-130 (but see new Important I-2). Hypothesis keys are NFC-mapped, P:90. |
| I7 | Array order and timestamp spelling undocumented | ADDRESSED | P:178-184, P:227-228, P:1872-1875, P:2094-2104. Test P:1742-1754. |
| I8 | Ruff I001 in contracts/outcomes | ADDRESSED | P:1301-1303, P:1831-1834. Measured: ruff clean. |
| I9 | SA:754 ordering not recorded | ADDRESSED | Ruling 7 at P:20; erratum 7 at P:4472. |
| I10 | Run fields, answer_only outside the table, no Hypothesis authority test | ADDRESSED (as ruled) | `RunRequestFields` P:1913-1923 + test P:1649-1656. `@given` P:1640-1646. `freeze_allowed` rationale P:763-770. |
| I11 | Schema `Z` vs model `+00:00` | ADDRESSED in behaviour (ruling 6, P:2607-2608, P:3135-3141, P:3181-3191) | The ruling's wording is inconsistent across the plan; new Important I-1. |
| I12 | Write-tool data guards unspecified | ADDRESSED | P:3057-3066 (`status ∈ [ok, outcome]`). |
| I13 | `date-time` hole | ADDRESSED | P:2537-2540, P:2604, P:3795-3801, P:4081, P:4493. Measured `'yesterday' is not a 'date-time'`. Without the package the checker fails closed. |
| I14 | Unanchored alternations | PARTIALLY | Every regex now starts `^\$`. P:3830 still alternates across two paths (`^\$\.(tool_name: …\|status: …)`), contrary to the plan's own constraint at P:30. |
| I15 | README per-section-hash claim | ADDRESSED | P:2398; `TODO(T17)` at P:3350-3352. |
| m1 | Count and label contradictions | ADDRESSED | P:2429-2430, P:4141, P:4272, P:4131, P:4463 ("eight", §19). Totals are consistent: 92→109→118→126→227→232→239→288/29→291/29. |
| m2 | SA citation errors | ADDRESSED | Rows now cite sections (P:634-691); `SA:` numbers appear only in the header and Global Constraints. |
| m3 | Missing docstrings | ADDRESSED (one gap) | `ModelDraft.clarification_requested` (P:2051) still has none. |
| m4 | `scratch.md` written into the repo; cwd-relative seed path | ADDRESSED | P:2240-2242 (`tmp_path`); P:2291-2293 (root-relative paths). |
| m5 | Stale checker docstring and CI comment; duplicate `import re` | ADDRESSED | P:2385, P:4116, P:4126-4129, P:4116 ("re is already imported"). |
| m6 | Governed set; BOM check | ADDRESSED | P:4075 (BOM); P:31 (hygiene test covers `tests/` and `core/`). |
| m7 | Event source rules; `action.failed` reason missing in code | ADDRESSED | Code P:1466-1480; schema P:2968-2997; negative P:3788-3794; tests P:993-1008. |
| m8 | Review Focus 1 overclaims | ADDRESSED | P:41. |
| m9 | Exhaustive transition probe; `bumps_state_version` tautology | ADDRESSED | P:422-435 (18×17×12); state_version deferred to T09 at P:301. |
| m10 | R082 "logged" had no TODO | ADDRESSED | P:512-513. |
| m11 | JobRule attempt-state TODO; per-type run_states in job schema | ADDRESSED | P:1115-1117; P:3243-3254. |
| m12 | AM-80 evals row not listed | ADDRESSED | P:4492. |
| m13 | Reasonless FAILED had no ruling | ADDRESSED | Ruling 8 at P:21; P:649-652 (premise is over-broad; see Minor). |
| m14 | Task 9 errata text; acceptance-matrix evidence | PARTIALLY | Errata are verbatim (P:4465-4473). `handoff/acceptance-matrix.json` (`evidence_status: NOT_RUN` for R004/R005/R082/R083/R104/R123) is still not in Task 9's Files list (P:4463). Either update it or state why it waits for `tests/acceptance/`. |
| m15 | Ruling 3 wording | ADDRESSED | P:16; `TODO(T15)` at P:1271 and P:3300. |

Counts: 29 ADDRESSED, 2 PARTIALLY (I14, m14), 0 NOT ADDRESSED. Round 1 listed 15 minor bullets; all 15 are judged here.

## 2. New findings

### Blocking

None. Every executable claim I could reproduce held.

### Important

**I-1. Ruling 6 is recorded in contradictory words, and the contradiction reaches the proposed spec erratum.**

The header (P:19), the generator (`model_pins()` P:3181-3191, which uses `UTC_REQUEST`) and the Coverage note (P:4493) all agree that only the hashed `proposal` requires `Z` and that `model-pins` accepts `Z` or `+00:00`. Four other places still say "stored" documents require `Z`:
- P:184 (canonical docstring): "stored and hashed documents use `Z`";
- P:2544 (Step 3 prose): "`proposal` and `model-pins` timestamps require `Z`";
- P:2605 (`UTC_STORED` comment): "a stored or hashed document";
- P:4471 (erratum 6, proposed verbatim to the owner): "stored and hashed documents spell UTC as `Z`".

`model-pins` is a stored document. An executor reading P:2544 could "fix" the generator. The owner would receive an erratum that the plan itself does not follow.

Fix:
- At P:184, P:2605 and P:4471, say "hashed documents (the proposal)" instead of "stored and hashed".
- At P:2544, write: "`proposal` timestamps require `Z`; `manual-proposal`, `model-pins` and the `get_recent_alerts` input accept `Z` or `+00:00`".
- Optionally rename `UTC_STORED` to `UTC_HASHED`.

**I-2. The NFC-collision test depends on an invisible combining character (P:130).**

The source is `canonical_json({"é": 1, "é": 2})`, where the first key is `e` + U+0301. An executor that retypes the block, rather than copying its bytes, will very likely emit NFC twice. The dict literal then collapses to one key, the test fails with "DID NOT RAISE", and the obvious wrong fix is to weaken `canonical.py`.

Fix: `canonical_json({"é": 1, "é": 2})`. The comment at P:128 already explains it.

### Minor

- **P:3830, cross-path alternation.** `tool-invalid-read-tool-outcome` uses `^\$\.(tool_name: 'get_asset_status'|status: 'outcome') is not one of`, which violates P:30. The best match is measured and stable: `$.tool_name: 'get_asset_status' is not one of [...]`, from rule (b) "outcome belongs to write tools". Use `^\$\.tool_name: 'get_asset_status' is not one of` and reword the reason accordingly, or relax P:30.
- **P:3182-3185, `model_pins` docstring.** It says "exactly as ops_core.model_pins accepts it", but `ModelPins.probed_at` is `AwareDatetime` with no zero-offset check (`core/src/ops_core/model_pins.py`). It accepts `+02:00`, which the schema rejects. Reword ("the schema additionally pins a zero offset"), or leave a `TODO(T19)`.
- **Duplicate negative.** `tool-invalid-status-unknown` (P:3818-3824) and `tool-get_incident_receipt-invalid-unknown` (P:3963-3969) are the same document, `{**receipt_unknown, "status": "unknown"}`. The "25 AM-80 probes" therefore include one duplicate. Drop one, or make the second a distinct probe.
- **P:1478, exception type.** `event_rules_ok` raises pydantic `ValidationError`, not `EventRuleViolation`, for a malformed receipt, which contradicts its docstring at P:1460. Conformance still passes because it catches `ValueError`. Wrap it in `EventRuleViolation`.
- **Code/schema drift on `model_summary` payloads.** The schema's `summary_payload` (P:2934-2936) requires `message` and forbids every key except `evidence_refs`. The code (P:1463) forbids only `status`, so `{"code": "x"}` passes the code and fails the schema. Mirror the closed shape in code, or note the gap.
- **Ruling 8's premise is too broad (P:21).** It reads SA:152 as "terminal states carry a reason". By that reading, CANCELLED, ANSWERED, INSUFFICIENT_EVIDENCE, SUCCEEDED and ABANDONED_UNVERIFIED also violate it, since all are reasonless in the table, yet only FAILED-from-worker is ruled. Reword: "a reason, where one is recorded, comes from the enum; FAILED via `transition_run` records none".
- **Mixed tenants in `proposal-valid.json`.** `authored_by` is alex, a real alpha persona (P:3474), while `payload.tenant_id` is the placeholder `0…01`. Harmless today; T21's "reviewer ∉ authored_by" fixtures should not copy it.
- **cwd-relative tests.** `test_schema_conformance.py` (P:4188) and `test_traceability.py` (P:4289-4290) open cwd-relative paths. They work only from the repository root, which is how `check.py` runs them.
- **Coverage gap carried over (m14).** `acceptance-matrix.json` is not touched by Task 9.

## 3. Generator lens, item by item

| Check | Result |
|---|---|
| Each schema vs its AM-80 row | Every AM-80 row (SA:760-778) maps to a generator function or example. The `evals` row is deferred (P:4492). The `fixtures` row is Task 5. |
| Reason sets in schemas | `FAILED_REASONS` and `REASONS` come from `ops_core` (P:2592-2593); `action-outcome` uses the 4-value FAILED set; the event `reason` uses the full enum, the same as the code. |
| `Z` vs `(Z\|\+00:00)` | `proposal` uses `UTC_STORED` (P:2866, 2867, 2877). `manual-proposal` (P:3141), `model-pins` (P:3190) and the `get_recent_alerts` input (P:3287) use `UTC_REQUEST`. Header and Coverage agree with this; P:184, 2544, 2605 and 4471 do not (I-1). |
| `if/then` under Draft 2020-12 | Every `if` tests only top-level-required properties: `status`, `outcome`, `kind`, `source`, `type`, `tool_name`, `grant_exists`, `model_route`. Nested `then` clauses test `data.status` / `data.outcome`, which the matching data rule makes required. No misfire found. |
| `additionalProperties` | Every object with `properties` is closed (measured). |
| `$id` uniqueness | 25 unique `$id`s; tool inputs use `tools/<name>-input` (measured). |
| Examples | 30/30 valid and 36/36 negatives match their stated `reason_match` (measured). Multi-error negatives resolve to the stated path. |
| Index version | `"version": "1.3.3"`, `"specification": "OPS-BUILD-1.3.6"` (P:3980). |
| Writes | LF and UTF-8, written with `write_bytes` (P:3999); `ROOT`-relative (P:2581, P:3439-3441). |
| Ruff | Clean (measured). No unused names. |

## 4. States, outcomes, canonical, contracts, checker (lenses 3-6)

- **Reason sets** (P:621-628) agree with AM-10 (SA:137, SA:138, SA:140, SA:150) and AM-20.3 (SA:454, SA:457, SA:462, SA:464, SA:468).
- **`outcome_from_destination`** (P:1328-1350) agrees with SA:229 (INTENT means never sent), SA:241 (INTENT abort → `cancelled_before_send` / `expired`), SA:242 (an ABORTED tombstone after SENT → `aborted_no_commit`) and SA:280 + ruling 2.
- **`event_rules_ok` vs the schema:**
  - The destination-only rule for the four evidence types matches schema rules (2) and (3).
  - `action.failed` requires a reason in both.
  - Late evidence and `action.confirmed` agree.
  - One divergence remains on the `model_summary` payload shape (Minor).
- **Canonical:**
  - Collision raises (P:217-218).
  - Array-order rule documented (P:178-181).
  - `proposal-valid` arrays are sorted.
  - Hash unchanged at `9d5c…4cf7` (measured).
- **Hypothesis authority property** (P:1640-1646): all ten names are extra on both `MessageRequest` and `MessageContext`, so no drawn value can validate and the property cannot pass vacuously or flake.
- **Strict constructions** in the tests pass (measured). PEP 695 `load` passes mypy (measured).
- **Checker:**
  - The `sys.path` insert sits before the import, which is correct under `-I` (measured).
  - Staging steps are present.
  - Tests assert on `stdout + stderr` and write with `newline="\n"`.
  - The drift test compares both file set and bytes (measured: 2 passed).
  - `rfc3339-validator` breaks no existing valid example (measured).
- **Traceability:** the regex handles empty cells and the trailing pipe; 58 rows; 10/46/2 (measured).
- **Hygiene:**
  - Totals arithmetic is correct.
  - Task 1 has 17 tests.
  - Counts are 27 new negatives, 10 new positives, 14 new schema files and 26 meta-validated documents.
  - `git add` lists are complete.
  - No nested-fence problems.
  - §19 and "eight rulings" are correct.
  - No attribution text.

## 5. The eight header rulings

| Ruling | Verdict |
|---|---|
| 1. AWAITING_APPROVAL → QUEUED by `create_revision` | Sound: SA:455 and BUILD_SPEC §8 include it; SA:484 omits it. |
| 2. `expired` in FAILED_NO_COMMIT | Sound: SA:241, SA:348, SA:465. |
| 3. `vector_exact` externally, `mode=vector` internally | Sound as reworded; TODO(T15) recorded at P:1271 and P:3300. |
| 4. QUEUED → RETRIEVING only | Sound: SA:451, SA:136. |
| 5. Cancel from BLOCKED_REVIEW | Sound: SA:139. |
| 6. Timestamp spelling | Sound in substance and in code. Recorded inconsistently (I-1), including in erratum 6. |
| 7. Negatives before services, not before contract code | Acceptable. It is openly an erratum to SA:754, justified by the T45→T07 dependency and by the conformance test needing both. |
| 8. Reasonless FAILED from the worker | Sound outcome; the premise is worded too broadly (Minor). |

## Declined to judge

- Behaviour on a real GitHub runner (`uv sync --locked --all-packages` pulling the new dev dependency, then `uv run python -I …`). Locally, the scratch venv equivalent passed.
- The exact `uv add` console output quoted at P:2540. I did not run `uv add` against the repository.
- Full `scripts/check.py` totals on the real tree. Every per-file count I measured matches the plan's arithmetic, but I did not run the whole suite in the repository.
- How likely an executor is to retype the NFD literal (I-2). The mechanism is certain; the likelihood is not.

READY TO EXECUTE: yes. There are no Blocking findings, and every executable claim reproduced. Fix I-1 (four wording edits, including erratum 6) and I-2 (escape the NFD literal) first; both are text-only edits.

---

## Round 2 — builder dry-run of the revised plan

# Plan C builder dry-run, round 2 (2026-10-08)

Plan: `docs/superpowers/plans/2026-10-08-first-slice-c-contracts-schemas.md` (4,497 lines, revised).
Scratch: detached worktree of `plan-b` (af17395) at `scratchpad/planc-dryrun2`, `uv sync --locked`, Git Bash, Python 3.13.
Code blocks were copied byte-for-byte from the plan by a fence extractor (`planc-review/tools/extract.py`, `block.py`); "Modify" edits were applied by exact-string scripts so that a non-matching anchor would raise. Baseline before Task 1: `92 passed, 11 skipped`, CHECK: GREEN.

## Verdict

**EXECUTABLE WITH FIXES.** All nine tasks reach their stated totals, and every measured "Expected" output matches: 109/118/126/227/232/239/288/291/291 with 11/11/11/11/11/11/29/29/29. The generator, `--contracts`, the drift test, the probes and the conformance test all behave as the plan says. Nothing is Blocking. Six instructions do not survive literal execution or contradict the generated artefacts (Misleading), and there are four Risky items.

Counts: **Blocking 0 / Misleading 6 / Risky 4.**

## Execution log

| Task.Step | Command / action | Plan expected | Actual | Status |
|---|---|---|---|---|
| 1.1 | `__init__.py`, testpaths | — | done | PROVEN |
| 1.3 RED | pytest test_canonical | ModuleNotFoundError ops_core.canonical; 1 error | same; `1 error` | PROVEN |
| 1.5 | pytest / mypy / check | 17 passed; 3 files; 109/11 GREEN | 17 passed; 3 files; `109 passed, 11 skipped, 1 warning`; GREEN | PROVEN |
| 1 | ruff check + format | clean | clean (88 files) | PROVEN |
| 2.2 RED | pytest test_states | ModuleNotFoundError ops_core.states; 1 error | same; `1 warning, 1 error` (the warning is the Hypothesis notice disclosed in Global Constraints) | PROVEN |
| 2.4 | pytest / mypy / check | 9; 4 files; 118/11 | 9; 4 files; 118/11 GREEN | PROVEN |
| 3.2 RED | pytest | ModuleNotFoundError ops_core.jobs | same | PROVEN |
| 3.6 | pytest / mypy / check | 8; 7 files; 126/11 | 8; 7 files; 126/11 GREEN | PROVEN |
| 4.2 RED | pytest test_contracts | `ModuleNotFoundError: No module named 'ops_core.contracts'` | `ImportError: cannot import name 'contracts' from 'ops_core'` (the test does `from ops_core import contracts as c`) | MISMATCH (M1) |
| 4.4 | pytest / mypy / check | 101; 8 files; 227/11 | 101; 8 files; 227/11 GREEN | PROVEN |
| 5.2 RED | pytest test_fixture_meta | ImportError gen_fixture_meta | same | PROVEN |
| 5.3 | `uv run python -m scripts.gen_fixture_meta` + print | path, `3 10`, three UUIDs | identical, byte for byte | PROVEN |
| 5.4 | checker edits | — | sys.path insert/import/check/PASS-suffix applied; docstring instruction ambiguous (M2) | WORKAROUND |
| 5.4 | README append | — | applied | PROVEN |
| 5.5 | stage; pytest | 5 passed | 5 passed | PROVEN |
| 5.5 | `uv run python -I verify_handoff --reference-code --manifest \| tail -6` | 2nd PASS ends `…; fixture meta.json current`, then 4 PASS + LIMIT, exit 0 | exact | PROVEN |
| 5.5 | the same without `uv run`: `python -I` (Isaac venv 3.13.7) and CI-form `python3 -I` from cwd `C:\` | works | rc 0 both | PROVEN |
| 5.5 | check | 232/11 | 232/11 GREEN | PROVEN |
| 5 extra | hand-tampered `meta.json` | base check fails | `FAIL: Fixture meta.json is stale: …` | PROVEN |
| 6.1 | append checker tests + `import os`; create drift test | — | literal append gives ruff format failure (M3); 2 blank lines added | WORKAROUND |
| 6.1 RED | `-k contracts` | 5 failed | 5 failed | PROVEN |
| 6.1 RED | test_schemas_generated | ImportError build_schemas; 1 error | same | PROVEN |
| 6.2 | `uv add --group dev "rfc3339-validator>=0.1.4,<1"` | `+ rfc3339-validator==0.1.4`, `+ six==1.17.0`; pyproject dev gains line; uv.lock updated | exact; pyproject +1 line in dev group; uv.lock +23 | PROVEN |
| 6.2 | FormatChecker on `"yesterday"` | rejected after | before: 0 errors; after: `'yesterday' is not a 'date-time'` | PROVEN |
| 6.3 | create generator | ruff-clean | `ruff check` + `format --check` clean; 0 CR, no BOM | PROVEN |
| 6.4 | `uv run python -m scripts.build_schemas` | `schemas/: 25 schema documents (19 contracts, 6 tool inputs); 66 examples (30 valid, 36 invalid); index.json version 1.3.3` | exact | PROVEN |
| 6.4 | modified/new file sets | 8 schemas + 12 examples change; 8 new top-level + 6 tools; 10 new positives; 27 new negatives | git status matches every list; cancellation/clarification/evidence and the other 17 examples are byte-identical | PROVEN |
| 6.4 | generated output encoding | LF/UTF-8 | 92 JSON files: 0 CR, 0 BOM, all end with LF | PROVEN |
| 6.4 | drift test | 2 passed | 2 passed | PROVEN |
| 6.4 | re-run generator | idempotent | no diff | PROVEN |
| 6.4 | tamper route.schema.json; stray `schemas/examples/stray.json` | drift test fails | `1 failed, 1 passed` both times; message names the file | PROVEN |
| 6.4 | schemas/README append | — | applied | PROVEN |
| 6.5 | checker edits (hash link, contracts body, docstring, CI) | — | all anchors matched once | PROVEN |
| 6.6 | stage; `--contracts \| tail -2` | `PASS: 26 JSON Schema documents; 30 accepted examples; 36 negative examples failed for their stated reason; governed files LF-only` + LIMIT, exit 0 | exact, rc 0 | PROVEN |
| 6.6 | `-k contracts` | 5 passed | 5 passed | PROVEN |
| 6.6 | CI form `uv run python -I … --reference-code --manifest --contracts` | — | rc 0, 7 PASS lines | PROVEN |
| 6.6 | bare `python3 -I … --contracts` (no jsonschema) | — | `BLOCKED: …`, rc 2 | PROVEN |
| 6.6 | check | 239/11 | 239/11 GREEN | PROVEN |
| 7.2 | conformance | `49 passed, 18 skipped` (12/2/2/1/1) | `49 passed, 18 skipped`; skip reasons 12 tool-result, 2 tool input, 2 job, 1 route, 1 evidence | PROVEN |
| 7.2 | check | 288/29 | 288/29 GREEN | PROVEN |
| 8.1 RED | traceability | 1 failed, 1 passed | same | PROVEN |
| 8.2 | TRACEABILITY.md rows by `ROW` | 58: 10/46/2 | 58: port 10, replace-by 46, drop 2; 0 unmatched `| \`` lines; 0 CR | PROVEN |
| 8.2 extra | `pytest --collect-only reference/tests` | parametrize ids | real ids `[None] [0] [169] [-1] [True] [1.5] [24]`, `[1] [24] [168]`; same as the AST rebuild | PROVEN |
| 8.3 | TREE_REPO_OWNED; docstring; test append | — | TREE_REPO_OWNED applied; the docstring anchor does not exist verbatim (M4) | WORKAROUND |
| 8.3 | `--reference-code --manifest \| tail -3` | 26 delivered … / 161 … / LIMIT; exit 0 | exact, rc 0 | PROVEN |
| 8.3 | traceability + checker tests | 18 passed | 18 passed | PROVEN |
| 8.3 | check | 291/29 | 291/29 GREEN | PROVEN |
| 9.1 | handoff edits; check; `--contracts` | 291/29 | 291/29 GREEN; `--reference-code --manifest --contracts` rc 0, same PASS line | PROVEN (prose step; see Risky R3, R4) |

After every task, `ruff check .` and `ruff format --check .` were clean, with the fix in M3 applied in Task 6.

## Findings

### Misleading

- **M1 (Task 4.2):** the stated RED message is `ModuleNotFoundError: No module named 'ops_core.contracts'`. The actual message is `ImportError: cannot import name 'contracts' from 'ops_core'`, because the test imports `from ops_core import contracts as c`. It is still an honest RED, but the text differs.
- **M2 (Task 5.4):** "In the module docstring, replace the first paragraph's first sentence with: 'Default checks need only…'". Read literally, the first paragraph's first sentence is the summary line, "Validate this handoff package, not the target production application.", and replacing it would destroy that line. The intended target is the first sentence of the second paragraph. *Workaround:* replaced "Default checks need only Python's standard library." This leaves a docstring line of more than 120 columns; ruff does not flag it (E501 is not selected).
- **M3 (Task 6.1):** "Append to `tests/plan_a/test_verify_handoff.py`". The block starts at `def _run_contracts` with no leading blank lines, and the file ends right after the last `assert`. A literal append makes `ruff format --check` fail ("would reformat"), so `check.py` at 6.6 prints CHECK: RED instead of the expected GREEN. Task 8's append block includes the two blank lines; Task 6's does not. *Workaround:* inserted two blank lines.
- **M4 (Task 8.3):** "change 'except the repository-owned reference/README.md (caches and build output skipped), and' to …". In the file the text is wrapped: "(caches and build output skipped),\nand". The literal string occurs 0 times, so an exact-match edit fails. *Workaround:* replaced it with the line break included.
- **M5 (Task 6.3 prose):** "`proposal` and `model-pins` timestamps require `Z`". This contradicts ruling 6, Coverage notes and the generated `model-pins.schema.json`, whose `probed_at` pattern is `(Z|\+00:00)`, and `scripts/probe.py` writes `+00:00` via `isoformat()`. The code is right and the sentence is wrong.
- **M6 (Global Constraints vs Task 6):** the constraints say an alternation appears "only inside the anchored part (`^\$\.field: (a|b)`)", and Step 3 says "or for two errors at the same path". But `tool-invalid-read-tool-outcome.json` uses `^\$\.(tool_name: 'get_asset_status'|status: 'outcome') is not one of`, an alternation across two different paths. It passes today, but it weakens R104: the probe has 3 errors (tool_name, status, data.action_id), and either path counts as the "stated reason".

### Risky

- **R1 (Task 6.5 CI):** CI's only bare-`python3 -I` run of the checker is replaced by `uv run python -I … --contracts`. After Plan C, nothing in CI proves that the default checks stay stdlib-only, even though Task 5 adds an in-repo import to them. Today the import is stdlib-only: `scripts.gen_fixture_meta` plus `scripts.gen_seed_ids` pull in only stdlib modules (checked by diffing `sys.modules`), and bare `python -I` works. A future edit to `gen_seed_ids.py` or `scripts/__init__.py` could break it silently. Consider keeping a `python3 -I scripts/verify_handoff.py` step.
- **R2 (Tasks 7, 8 tests):** `test_schema_conformance.py` (`Path("schemas/examples/index.json")`) and `test_traceability.py` (`Path("reference/tests")`, `Path("handoff/tasks.json")`) resolve paths from the working directory, unlike `test_fixture_meta.py` and `build_schemas.py`, which use ROOT. They pass under `check.py` and `pytest` from the root, but fail at collection or with FileNotFoundError from any other cwd. The existing plan_a tests do the same, so this is consistent rather than new.
- **R3 (Task 9):** apart from the eight errata, the step has no exact text. Tasks T45 and T46 have no `review_notes` key, so it must be created. `SESSION_STATE.md`'s "Exact next step" still lists `python -I scripts/verify_handoff.py --reference-code --manifest` without `uv run … --contracts`, and the plan does not say to update it. A fresh agent would leave the CI form and the documented local form out of step.
- **R4 (Task 9):** the review note must "name the commits", but Task 9's own commit cannot be named in itself. I used `<first>..<T46 commit>`. This is harmless but unstated.

### Not findings (checked)

- `.hypothesis/` is ignored. It never appears in `git status --short`, because Hypothesis writes `.hypothesis/.gitignore` containing `*`; `git status --ignored` shows `!! .hypothesis/`. The repository `.gitignore` does not list it, so it is ignored only because of Hypothesis's self-ignore file.
- After each `git add` the staged set was exactly the plan's paths. Only the untracked plan copy remained (`?? docs/superpowers/plans/…`, an artefact of this scratch setup).
- Task 1's RED shows `1 error` with no warning, because `.hypothesis/` does not exist yet. Later REDs show `1 warning, 1 error`, as Global Constraints discloses.

## Answers 1–8

1. **Totals:** 109/11, 118/11, 126/11, 227/11, 232/11, 239/11, 288/29, 291/29, 291/29, all as stated, each with `1 warning` (Hypothesis). ruff check and format were clean after every task, with M3's two blank lines applied.
2. **Task 5:** the generator printed exactly the expected 5 lines. Bare `python -I scripts/verify_handoff.py --reference-code --manifest` (no `uv run`) gives rc 0. The CI form, `python3 -I` from another cwd, gives rc 0. The `sys.path.insert(0, ROOT)` works under `-I`. The stdlib-only promise holds: the imported modules are all stdlib plus `scripts`, `scripts.gen_fixture_meta` and `scripts.gen_seed_ids`. A stale `meta.json` makes the base check FAIL.
3. **Task 6:**
   - Generator output matches: 25 (19+6) schemas; 66 examples (30 valid, 36 invalid); version 1.3.3.
   - The `--contracts` PASS line matches exactly.
   - The drift test passes (2). A hand-tampered `route.schema.json` and a stray JSON file each make it fail.
   - The 5 checker tests fail at RED and pass at GREEN.
   - All 36 negatives match their `reason_match`.
   - The four R083 probes (`event-invalid-model-success`, `event-invalid-confirmed-no-receipt`, `tool-invalid-ok-unknown`, `tool-invalid-outcome-no-action-id`), `event-invalid-occurred-at` and `event-invalid-confirmed-application-source` each fail at the stated path. Each validates once only the stated field is repaired, so the rule is the cause.
   - `model_summary` + `explanation.ready` + `status` is still rejected.
   - The generator writes LF/UTF-8 (92 files, 0 CR, 0 BOM) and is ruff-clean.
   - `uv add` changed pyproject (dev group +1 line) and uv.lock (+23 lines), and installed rfc3339-validator 0.1.4 and six 1.17.0. FormatChecker now rejects `"yesterday"`; before the add it accepted it.
4. **Task 7:** `49 passed, 18 skipped`; no disagreement, so nothing to fix on either side. I also checked the pydantic-side error for each of the 30 modelled negatives: each fails on the same field or rule as the schema's stated reason. `decision-invalid-old-hash-field` reports 2 errors on both sides (extra field and missing field).
5. **Task 8:** the `ROW` regex parses 58 rows: 10 port, 46 replace-by, 2 drop, with 0 unmatched table lines. Real pytest collection of `reference/tests` confirms the parametrize ids. `--reference-tree` accepts the file (26 / 161 PASS, rc 0). The new `test_reference_tree_accepts_traceability` passes, and the checker plus traceability tests give 18 passed.
6. **Task 9:** I made the edits as described: T07/T45/T46 set to DONE with review notes, the eight errata verbatim in SESSION_STATE and in the T07/T45 notes, PROJECT_HISTORY §19 after §18, a STATUS section, and backlog ticks. After that: check.py 291/29 GREEN; `--reference-code --manifest --contracts` rc 0 with the same PASS line; tasks.json still valid (47 acyclic tasks, 131 requirements). Text quality is my own wording, because the plan gives none beyond the errata (R3).
7. **Staging:** after each `git add`, `git status --short` showed only the plan's paths plus the untracked plan copy. `.hypothesis/` never appeared, because it is self-ignored by its own `.gitignore` and not by the repository `.gitignore`.
8. **Fresh-engineer traps:**
   - The Task 6 append needs blank lines (M3).
   - The two docstring edits cannot be done by literal string match (M2, M4).
   - The Task 4 RED text is wrong (M1).
   - Running `pytest --collect-only reference/tests`, or anything else that imports the reference, leaves `__pycache__` under `reference/`. The tree check skips caches, but don't commit them. I removed them.
   - My own heredoc mangled a `\n` in a README append. That was my tooling, not the plan; it was fixed with byte-level writes.
   - The zip `provenance/handoff-1.0.zip` is tracked, so the worktree had it without any copying.

## Workarounds applied (all minimal)

- M2: edited the second paragraph's first sentence of the checker docstring.
- M3: added two blank lines before `def _run_contracts`.
- M4: matched the docstring text with its embedded line break.
- Task 9: prose written by me (no exact text in the plan beyond the errata).

## Real outputs

- `--contracts`: `PASS: 26 JSON Schema documents; 30 accepted examples; 36 negative examples failed for their stated reason; governed files LF-only`
- Final check.py: `291 passed, 29 skipped, 1 warning in 18.15s` / `CHECK: GREEN`

## Cleanup

`git worktree remove --force …/planc-dryrun2 && git worktree prune` done. `git worktree list` shows only `C:/Users/joeys/Desktop/MLOps af17395 [plan-c]`. The real repo's `git status --short` is unchanged: the same two untracked files (`docs/reviews/plan-review-c-2026-10-08.md` and the plan), branch `plan-c`, HEAD af17395. Nothing was committed or pushed in the real repo. Scratch commits existed only in the removed detached worktree.

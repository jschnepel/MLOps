# Plan C final whole-branch review (2026-10-08)

Branch `plan-c`, range af17395..4012ec6 (Plan C tasks T07, T45, T46 and the slice-end handoff docs), reviewed after each of the nine tasks passed its own gate. Outcome: 0 Critical, 5 Important, 10 Minor, 13 behaviours declined to judge. The five Important findings and five of the Minors were fixed in one wave (commits 2a25585..9af6c53); a new mutation-based differential test written in that wave found two further schema-versus-code seams, both fixed in the same wave. A scoped re-review on the same model confirmed every finding addressed with no new Critical or Important breakage and three cosmetic minors, which were fixed in the closing commit (381 passed, 30 skipped, GREEN; 25 schemas, 87 examples: 34 valid, 53 negatives).

The sections below are, in order, the reviewer's text unedited, the controller's rulings on every finding, the implementer's fix report, and the scoped re-review.

---

# Part 1 — Reviewer's report (unedited)

# Final whole-branch review: plan-c (af17395..4012ec6)

Reviewer: final whole-branch review (read-only on the tree). Date: 2026-10-08.
Method: four passes as asked (1: `core/src/ops_core/*`, `scripts/*.py`; 2: `tests/plan_c/*`, `tests/plan_a/test_verify_handoff.py`; 3: `schemas/` checked against the generator plus differential probes instead of reading all 68 examples; 4: docs and handoff). I read narrower `git diff`/`git show` slices instead of the 750 KB package. The probe scripts are in the session scratchpad (`.../scratchpad/probes/p1.py` to `p5.py`). None of them touched the repository.

### Verification performed

| Command / probe | Result (tail) |
|---|---|
| `git status --short` | empty (clean tree), HEAD 4012ec6 |
| `PYTHONUTF8=1 uv run python scripts/check.py` | ruff clean, format clean (102 files), mypy `Success: no issues found in 14 source files`, `333 passed, 29 skipped in 19.66s`, `CHECK: GREEN` (exit 0) |
| `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts; echo exit=$?` | `PASS: 26 JSON Schema documents; 30 accepted examples; 38 negative examples failed for their stated reason; governed files LF-only`; reference/manifest PASS (26 files, 161 checksums); `exit=0`. The 26 are the 25 generated schemas plus T03's `evals/holdout-case.schema.json` (the generator docstring explains this). |
| Drift test: `uv run python -m pytest -q tests/plan_b/test_text_hygiene.py tests/plan_c/test_schemas_generated.py` | `3 passed`. The drift test regenerates into tmp and compares bytes. Text hygiene is collected (`--collect-only` shows `test_no_carriage_return_or_bom_in_tracked_text`) and is in `testpaths`, so check.py runs it. |
| commit messages af17395..4012ec6 grepped for attribution trailers | no output (grep exit 1) |
| Probe p1: canonical edge cases | float, NaN, non-str key, set, oversized int (both directions), lone surrogate, NFC key collision, duplicate key, NaN/float/exponent literals: all raise `CanonicalizationError`. `true` and `1` give different bytes. NFD and NFC give the same hash. **`canonical_json` of a 5000-deep Python list/dict raises a bare `RecursionError`.** |
| Probe p1b: parse, then canonicalise | depth 500/900/990 ok. **Depth 2000: `parse_json_strict` accepts it and `canonical_json` then raises a bare `RecursionError`.** Depth 10000: the parser raises `CanonicalizationError`. |
| Probe p2: contracts | NFC-equivalent titles give the same hash. NFC-equivalent `evidence_refs` are rejected as duplicates. `load()` rejects duplicate keys at top level, nested, and via `text` escape spelling. Deep nesting gives `ValidationError`, never `RecursionError`. bool/str/float `hours` and nested `tenant_id` are rejected. **`CancelResponse(status=FAILED, grant_exists=false)` is rejected.** `CancelResponse(status=QUEUED, grant_exists=true, attempt_state=SENT)` is accepted. 9-digit fractions are truncated (two distinct inputs give the same instant). `12:00Z` without seconds is accepted. |
| Probe p3: differential mutation, schema vs code, on every valid example (null, `''`, `'   '`, trailing `\n`, `0`, `true`, `[]`, duplicate item per field) | Classes of disagreement: explicit `null` on optional fields (code accepts, schema rejects); whitespace-only strings (schema accepts, code rejects); **trailing `\n` on `$`-anchored patterns and `date-time` (schema accepts, code rejects)**; event envelope fields (no code model yet, expected). |
| Probe p4: cancel-response product (17 states × 2 × 2 × 5 attempt values) | **113 of 340 combinations disagree.** The schema accepts `CANCELLED` + `grant_exists=true` and `cancel_requested=false`; the code rejects `FAILED` without a grant. |
| Probe p4: event (27 types × 3 sources × 12 payloads = 972) | Only 2 disagree, both **`action.failed` with `reason=conflict`: the schema accepts, the code rejects**. `model_summary` is accepted only for `explanation.ready`. `destination` is accepted only for the 4 evidence types. None of the 4 destination types is accepted from `application`. |
| Probe p4b: action-outcome | **The schema accepts a tombstone for another action or payload, a REJECTED tombstone with `cancelled_before_send`, and an ABORTED tombstone with `rejected`. The code rejects all four.** No valid FAILED_NO_COMMIT example is committed. |
| Probe p5: independent transition expectation from the AM-20.3 performer table, AM-10 and rulings 1/4/5/8/9 | 44 rows / 38 pairs / 13 performers. Extra = ∅, missing = ∅. No row leaves a terminal state. No self-loops. No worker row into a post-grant state. Active ∪ terminal ∪ {BLOCKED_REVIEW, ESCALATED} = all 17. |
| Dedup probe | **`dedup_key(INVESTIGATE, run_id=r, revision=2)` == `dedup_key(RESUME_INPUT, run_id=r, clarification_event_id=2)` == `"<r>:2"`.** `revision=0` and `run_id="x:y"` are accepted. |
| Proposal probe | `Proposal` accepts a document whose raw payload (`"  Café review  "`, `+00:00`) does **not** hash to `payload_sha256`; the hash matches only after strip/NFC/`Z` normalisation. |
| Negative-example error multiplicity | 9 of 38 negatives fail on more than one error. `event-invalid-model-success` has 5. |
| reason_match anchoring | All 38 start with `^\$`. Nothing enforces it. |
| `uv run pytest` (no `-m`) | Collection error, `No module named 'scripts'`. This is a pre-existing pattern from Plans A/B; check.py uses `python -m pytest`. |
| Acceptance matrix | 6 `RECORDED_LOCALLY` / `IMPLEMENTED_LOCALLY_VERIFIED`, 125 `NOT_RUN`. Every `evidence_paths` file exists. Task statuses: T07/T45/T46 `DONE`. |

### Strengths

- `core/src/ops_core/states.py:111-208`: the transition table is plain data, and each row carries a spec note and a reason set. `require_transition` (`:239`) separates "pair not in table", "wrong performer" and "reason missing/forbidden". An independent derivation from AM-20.3 and the rulings matched it exactly (p5). `tests/plan_c/test_states.py` enumerates all 18×17×13 combinations and pins every row's reason set. That is a real, non-vacuous guard.
- `core/src/ops_core/contracts.py:68-72, 89-98`: NFC runs as a `BeforeValidator` before the length, uniqueness and order checks. The Task 4 Critical is fixed at the root: NFC-equivalent payloads hash alike and duplicate NFC refs are refused (p2).
- `core/src/ops_core/contracts.py:116-131`: `load()` rejects duplicate keys with its own scan, including escape-spelled duplicates, and never leaks `RecursionError` (p2).
- `core/src/ops_core/outcomes.py:43-65`: `outcome_from_destination` keys the reason on `sent`. Claiming `cancelled_before_send` after SENT would be false, and the docstring says why.
- `core/src/ops_core/outcomes.py:201-250` with `scripts/build_schemas.py:378-490`: the AM-14 source/authority rules hold on both sides. 970 of 972 type×source×payload combinations agree (p4), and no forged destination evidence from `application` gets through either side.
- `scripts/build_schemas.py`: one generator, with every enum imported from `ops_core`, a byte-for-byte drift test, and `if` conditions on required properties so conditions cannot pass vacuously (`when()` docstring). This is the right structural fix for drift between hand-edited schemas.
- `scripts/verify_handoff.py:342-347, 389-396`: it fails closed (exit 2) without a `date-time` checker. Negatives must match an anchored `<path>: <message>` regex, and `tests/plan_a/test_verify_handoff.py:165-215` proves the wrong-reason, validated-negative, CR and missing-validator paths on tampered copies.
- `tests/plan_c/test_traceability.py`: rebuilds the 58 node ids from the AST, pins the row count and requires owning tasks to exist in `tasks.json`.
- Handoff honesty: STATUS, SESSION_STATE and the matrix use the new vocabulary, claim no running capability, keep R120 `NOT_RUN`, and present all nine rulings as proposals the owner decides, with the spec authoritative until then. The commit messages carry no attribution.

### Issues

#### Critical (Must Fix)

None.

#### Important (Should Fix)

**I1. `canonical_json` leaks a bare `RecursionError` on deep input, including input `parse_json_strict` accepts.** `core/src/ops_core/canonical.py:37-57, 69-77`
- **What's wrong.** `_normalize` recurses outside the `try` that wraps `json.dumps`. A value nested about 1000 deep or more raises `RecursionError`, not `CanonicalizationError`. JSON nested 2000 deep passes `parse_json_strict` (probe p1b) and then blows up in `canonical_json`.
- **Failure scenario.** The destination path in T13 parses received bytes, re-canonicalises them and catches `CanonicalizationError` to answer 4xx. A hostile or buggy 2000-deep body escapes as a 500 or a crashed handler.
- **Contradictions.** The comment at `:70-71` ("must never surface … RecursionError") and PROJECT_HISTORY §18 ("Canonical JSON now raises its own error for every input it refuses") are both untrue of the tree. No test covers deep nesting for `canonical_json`.
- **Fix.** Call `_normalize` inside the `try` (or catch `RecursionError` around it). Add a test that parses a 2000-deep array and canonicalises it, and a test for a 5000-deep Python list.

**I2. `CancelResponse` rejects a truthful response for a run that FAILED before any grant.** `core/src/ops_core/contracts.py:39-50, 256-257`
- **What's wrong.** `_POST_GRANT_STATES` includes `FAILED`. The comment says "a run can only be here if a grant was issued", but the table has RETRIEVING/DRAFTING → FAILED via `transition_run` (ruling 8), with no grant.
- **Failure scenario.** A user cancels a run that has just failed on exhausted infrastructure policy. If T10 reports the current state (`status=FAILED, grant_exists=false`), the response contract raises and the API returns a 500 instead of the truth. A developer working around it may set `grant_exists=true`, which is a false claim.
- **Fix.** Remove `FAILED` from `_POST_GRANT_STATES`. The set then only holds states that imply a grant: EXECUTING, OUTCOME_UNKNOWN, ESCALATED, SUCCEEDED, ABANDONED_UNVERIFIED. Add the case to `test_cancel_response_reports_grant_and_never_undo`.

**I3. The schema and the code disagree on authority-relevant rules that none of the 68 examples exercises.** The conformance test only replays committed examples, so it cannot see these. Measured in probes p4/p4b:
- **(a) `cancel-response`** (`scripts/build_schemas.py:646-663`). The schema accepts `status=CANCELLED` with `grant_exists=true`, which is the "undo" claim AM-13 forbids. It also accepts `cancel_requested=false` and post-grant states without a grant. `CancelResponse` rejects all of these. In total 113 of 340 combinations disagree. The schema is the published contract for this response (and the OpenAPI source later), so a client or test written against it is told an undo claim is valid.
- **(b) `event`** (`scripts/build_schemas.py:462-466`). Rule (7) requires `reason` on `action.failed` but leaves it as any `Reason`. `event_rules_ok` requires the FAILED_NO_COMMIT set, so the schema accepts `action.failed` with `reason=conflict`.
- **(c) `action-outcome`** (`scripts/build_schemas.py:162-192`). "REJECTED tombstone iff reason `rejected`" is expressible in JSON Schema but absent, and there is no valid FAILED_NO_COMMIT example. Tombstone↔`action_id`/`payload_sha256` identity is not expressible; say so in a `$comment`.
- **Fix.**
  - Add the expressible rules to the generator: cancel-response `cancel_requested: const true`; `if status=CANCELLED then grant_exists=false`; `if grant_exists=false then status ∉ post-grant`. Event rule (7) `reason ∈ FAILED_REASONS`. The action-outcome REJECTED⇔`rejected` pair.
  - Add a negative for each new rule, plus a valid FAILED_NO_COMMIT example.
  - Turn probes p3/p4 into a mutation-based differential test in `tests/plan_c/test_schema_conformance.py`, so future seams are caught without hand-written examples.

**I4. `$`-anchored schema patterns and `date-time` accept a trailing newline under the validator this project uses.** `scripts/build_schemas.py:68-72` (UTC_HASHED, UTC_REQUEST, SHA256, DIGEST, ASSET_ID)
- **What's wrong.** Python's `jsonschema` applies `pattern` with `re.search`, where `$` matches before a final `\n`, and rfc3339-validator accepts `"…Z\n"` (probe p3). The schemas therefore accept `"A17\n"`, `"<64 hex>\n"` and `"2026-10-05T12:00:00Z\n"`. This is the same defect Task 3 fixed in `jobs.py` with `fullmatch`, and PROJECT_HISTORY §18 says "key patterns use full matches", which is true only of `jobs.py`.
- **Failure scenario.** `NO_MODEL` says tool inputs are "enforced by the MCP server's argument validation (T15)". If T15 validates `get_asset_status` arguments with these schemas, `"A17\n"` passes and reaches asset-sim, and the `get_recent_alerts` interval accepts a newline-suffixed instant.
- **Fix.** Use an ECMA-compatible end anchor that Python honours too: `…(?![\s\S])` instead of `$`, or `\z`-free equivalents. Add `maxLength` to the fixed-length patterns (sha256 = 64). Add one trailing-newline negative per pattern family.

**I5. `dedup_key` lets two job types mint the same key in the globally UNIQUE `jobs.dedup_key`.** `core/src/ops_core/jobs.py:129-156`
- **What's wrong.** Every part accepts any `UUID | int | str`. `INVESTIGATE(run_id=r, revision=2)` and `RESUME_INPUT(run_id=r, clarification_event_id=2)` both give `"<r>:2"` (probe). `revision=0`, negative revisions and `run_id="x:y"` (ambiguous splitting) are also accepted.
- **Failure scenario.** T12 passes the clarification event's per-run `sequence` (an int) instead of its `event_id`. AM-20.4's `INSERT … ON CONFLICT (dedup_key) DO NOTHING` then silently drops the `resume_input` job, and the run sits in AWAITING_INPUT forever. The module exists to make uniqueness "a database uniqueness fact rather than a hope", and these inputs defeat that silently.
- **Fix.** Type the parts per job: UUID for `run_id`, `proposal_id`, `action_id` and `clarification_event_id`; int ≥ 1 for `revision`. Raise a module error type rather than bare `ValueError`. Add a cross-type collision test.

#### Minor (Nice to Have)

1. **`Proposal` accepts a document whose hash matches only after normalisation** (`contracts.py:419-423`). Strip, NFC and `+00:00`→`Z` are applied before hashing, so a stored document's raw payload need not hash to its own `payload_sha256` (probe). BUILD_SPEC §6 says "persist those exact bytes". Either require `payload == canonical_dict()` for a stored `Proposal`, or document that consumers must send `canonical_json(payload.canonical_dict())` and never the raw document. The checker (`verify_handoff.py:305-308`) hashes the raw payload, so it and the model use two different definitions of "the payload's hash".
2. **Null and whitespace conventions differ between code and schema** (probe p3).
   - The code accepts explicit `null` for optional fields (`context`, `supersedes_run_id`, `reason`, `text`, `asset_id`, `hours`); the schemas reject it.
   - The schemas accept whitespace-only strings, which the code strips and rejects.
   - The decision and cancellation `reason` has `minLength: 0` in the schema but ≥ 1 after strip in the code.
   - Pick one convention per side and state it in the generator.
3. **`CancelResponse` accepts `grant_exists=true` with a pre-grant status** (`QUEUED`, `APPROVED`, … with `attempt_state=SENT`). Grants and APPROVED→EXECUTING commit in one transaction, so this is self-contradictory (`contracts.py:247-258`).
4. **Timestamp edge cases.** More than 6 fractional digits are silently truncated, so two different inputs freeze to the same instant. `"…T12:00Z"` (no seconds) is accepted by the code and rejected by the schema (`contracts.py:75-84`).
5. **`event_rules_ok` robustness and evidence pairing** (`outcomes.py:191-250`).
   - A non-Mapping payload raises `AttributeError`.
   - `_validated`'s `json.dumps` can raise `RecursionError`.
   - `action.failed` may carry a receipt and `action.confirmed` a tombstone, on both sides.
   - The late-evidence tombstone is not cross-checked against `payload.action_id`.
6. **Comment standard** (`docs/CODE_COMMENTS.md`).
   - `tests/plan_c/test_jobs_routes_outcomes.py:258` keeps a `# type: ignore[arg-type]`, while line 335 says none is needed.
   - `outcomes.py:223-224` is a changelog in code ("the former … check … is gone").
   - `contracts.py:5-7` ("Tasks 6-7 of Plan C add …") and `canonical.py:12` ("Task 4 of Plan C") are future-tense process narration that is already stale.
   - `canonical.py:70-71` contradicts the behaviour (I1).
   - `jobs.py:68` exports a public `S = RunState` alias, while `states.py` made its aliases private.
7. **Unreadable `require_transition` messages** (`states.py:253-256`). `sorted(row.reasons)` renders as `[<Reason.ABORTED_NO_COMMIT: 'aborted_no_commit'>, …]`. These messages will reach logs and 409 bodies, so render `r.value`.
8. **Handoff wording.**
   - PROJECT_HISTORY §18 overstates two fixes (see I1 and I4).
   - R082 is `IMPLEMENTED_LOCALLY_VERIFIED` in the matrix although its expected evidence includes "logged" (`TODO(T09)`). STATUS and SESSION_STATE say so, but the matrix row does not. Add a note there.
   - T07's DoD says the answer_only refusal is "in the table". It is a separate guard (`freeze_allowed`), well justified in its docstring, but not recorded as a ruling.
9. **Conformance test gaps** (`tests/plan_c/test_schema_conformance.py:68-72`).
   - Negatives only assert "some `ValidationError`", so the model may reject for a different reason than the schema.
   - The 12 tool-result examples are skipped, although their write-tool `data` could be validated with `ActionOutcome`. The skip reason even names it.
10. **Negative-example rigour.**
    - Neither the generator nor the checker enforces the "every reason_match starts with `^\$`" constraint (all 38 comply today).
    - 9 negatives fail on several rules: `event-invalid-model-success` on 5, and `run-manifest-invalid-model-route` also trips the digest rule. Such a negative does not isolate the rule it names.

### Declined to judge

- `uv run pytest` without `-m` fails to import `scripts`: a pre-existing pattern from Plans A/B (six earlier test files do the same); check.py and CI use `python -m pytest`.
- `index.json` version `1.3.3` under specification 1.3.6: AM-80 literally prescribes 1.3.3.
- Event envelope fields (`event_id`, `sequence`, `tenant_id`, payload `action_id`) are not validated in code: no Event model until T14, stated in the conformance docstring.
- `request_abort`'s reason `deadline` is absent from `Reason`: it is an abort-request argument owned by T13, not a run reason.
- AM-14 "late_evidence status = the run's terminal status" is unenforced: it needs run state (T13/T14).
- The merits of the nine rulings themselves: the owner decides. I checked only that they are presented as proposals, with the spec authoritative until then (they are).
- The checker's proposal hash omits NFC: the plan's Global Constraints accept this explicitly for the ASCII examples.
- The fixture section-hash definition and duplicate-heading shadowing in `gen_fixture_meta.py`: parked Task 5 minors in the ledger.
- No input-size limit in `load()`: an API-layer concern (T12), not a core contract.
- `ModelRoute` holds only `fake` and `qwen3:8b`: AM-16's "future named model" is deferred to T19.
- `strip_whitespace` altering requester text before hashing: a reviewed Task 4 design choice, outside the spec's "normalise to NFC".
- Ledger-parked items (tool-input `$id` convention, port rows checking existence only, six "same" reasons, dated STATUS lines): already ruled by the executor.
- A committed negative for "draft carrying `supersedes_run_id`" (AM-80 proposal row): the row already has two negatives and the code test covers it, so the per-row requirement is met.

### Recommendations

- Before Plan D consumes these contracts, fix I1 and I2 (minutes each) and I5 (types on `dedup_key` before any SQL uses it).
- Close I3 and I4 in the generator, and add the mutation-based differential test so the next contract change cannot reopen a seam that no example exercises.
- Plan D (T08) should treat `canonical_json(ProposalPayload.canonical_dict())` as the only bytes ever stored, sent or hashed (Minor 1), build every request with `load()`, and pass UUIDs (never sequences) to `dedup_key`.
- Process: each per-task review saw its own side of the seam. A final step that mutates every valid example and compares schema with code would have surfaced I3 and I4 at Task 7. Make it part of the conformance task template.

### Assessment

**Ready to merge?** With fixes
**Reasoning:** The core is sound. The transition table, the authority/source rules and NFC-correct hashing all hold up under independent probing, and the handoff is honest. Two small code defects (I1, I2), a latent dedup-key collision (I5) and schema↔code seam gaps on undo/evidence claims (I3, I4) should be closed before Plan D builds on these contracts.

---

# Part 2 — Controller rulings and fix brief

# Plan C — final-review fix wave (one pass)

Source: `final-review.md` in this directory (read its "Issues" section first; the probes it describes are your acceptance tests). Base commit: `4012ec6` on branch `plan-c`. The spec is `SPEC_AMENDMENTS.md` over `BUILD_SPEC.md`; the plan header's nine rulings stand. The comment standard is `docs/CODE_COMMENTS.md`.

## Rulings (what to fix, what to park)

### Fix — Important

**I1 (canonical.py).** `_normalize` runs inside the same `try` as `json.dumps`, so deep nesting raises `CanonicalizationError`, never a bare `RecursionError`. Tests: a 2000-deep JSON array that `parse_json_strict` accepts is refused by `canonical_json` with `CanonicalizationError`; a 5000-deep Python list likewise. Keep the comment at the top of the function true.

**I2 (contracts.py `_POST_GRANT_STATES`).** Check the transition table in `states.py` first: if `FAILED` is reachable without a grant (RETRIEVING/DRAFTING → FAILED by `transition_run`, ruling 8), remove `FAILED` from `_POST_GRANT_STATES` so it holds only states that imply a grant (EXECUTING, OUTCOME_UNKNOWN, ESCALATED, SUCCEEDED, ABANDONED_UNVERIFIED). Fix the comment. Add the case (`status=FAILED, grant_exists=false, cancel_requested=true` accepted) to the CancelResponse test. Also close **Minor 3** here: `grant_exists=true` with a pre-grant status is contradictory (a grant and APPROVED→EXECUTING commit together); reject it with a clear message and test it.

**I3 (generator seams).** Add to `scripts/build_schemas.py`:
- cancel-response: `cancel_requested` is `const true`; `if status == CANCELLED then grant_exists == false`; `if grant_exists == false then status not in post-grant`; `if status in pre-grant then grant_exists == false` (the Minor 3 mirror). Mirror `CancelResponse` exactly — derive the state lists from the same source `contracts.py` uses (import or share a constant; do not retype them).
- event rule (7): `action.failed` reason must be in the FAILED_NO_COMMIT set (reuse `FAILED_NO_COMMIT_REASONS`), mirroring `event_rules_ok`.
- action-outcome: a REJECTED tombstone ⇔ reason `rejected` (both directions, as `ActionOutcome` enforces); add a `$comment` saying the tombstone↔`action_id`/`payload_sha256` identity is not expressible in JSON Schema and is enforced by `ActionOutcome`.
- Examples: one negative for each new rule, with a path-anchored `reason_match`; one valid FAILED_NO_COMMIT tool-result example (abort or create_incident shape, whichever the generator already models). Regenerate the tree; the drift test must pass; the checker's `--contracts` line and the README counts must be updated to the new totals.
- Differential test: add to `tests/plan_c/test_schema_conformance.py` a mutation test over the valid examples of the schemas that have a model (`SCHEMA_MODELS` keys and the `EVENT` branch): for every enum-valued field, substitute each other enum value; for every boolean, flip it; for every required field, remove it. For each mutant, assert the schema and the model agree (both accept or both reject). Keep the mutation set to those three operations — null/whitespace/timestamp-spelling conventions are parked (Minor 2 and 4) and must not be mutated. If this test surfaces a disagreement beyond those named in I2/I3, resolve it when the spec makes the answer plain and record it in your report; if the spec does not, leave the test failing for that case, list it under Concerns, and return DONE_WITH_CONCERNS — do not add exclusions to hide it.

**I4 (generator anchors).** In `scripts/build_schemas.py`, every `$`-terminated pattern (`UTC_HASHED`, `UTC_REQUEST`, `SHA256`, `DIGEST`, `ASSET_ID`, and any other) ends with `(?![\s\S])` instead of `$` (valid in ECMA-262 and honoured by Python's `re.search`); fixed-length values also get `maxLength` (sha256 = 64; others as their pattern implies). Timestamps that rely on `format: date-time` alone keep the pattern as well, so a trailing newline fails the pattern even where the FormatChecker is lenient. One trailing-newline negative per pattern family (asset id, sha256 digest, hashed timestamp, request timestamp), each with a `reason_match` anchored at the field's path. Regenerate; drift test; checker totals.

**I5 (jobs.py `dedup_key`).** Type the parts per job: `UUID` for `run_id`, `proposal_id`, `action_id`, `clarification_event_id`; `int >= 1` for `revision`. Refuse anything else with a module error type (reuse the module's existing error class if it has one; otherwise `DedupKeyError(ValueError)`), never a bare `ValueError`. Keep key strings unchanged for valid inputs (the regexes in `JOB_RULES` still match). Tests: the cross-type collision from the review (`INVESTIGATE(run_id=r, revision=2)` vs `RESUME_INPUT(run_id=r, clarification_event_id=2)`) now raises on the int; `revision=0`, negative, and a string run id raise; valid keys are unchanged (pin two literal keys).

### Fix — Minor

**M5 (partial).** `event_rules_ok` refuses a non-Mapping payload with `EventRuleViolation`; `_validated` catches `RecursionError` as "malformed". Also refuse a `receipt` on `action.failed` and a `tombstone` on `action.confirmed` in both code and schema rule (8)'s positive branch, with one negative each. The late-evidence tombstone↔`action_id` cross-check is parked (needs the Event model, T14).

**M6 (comments).** Remove the `# type: ignore[arg-type]` at `tests/plan_c/test_jobs_routes_outcomes.py:258` (restructure the call instead); delete the changelog sentence at `outcomes.py:223-224`; rewrite the task-narration comments at `contracts.py:5-7` and `canonical.py:12` as present-tense statements of what the module does; make `jobs.py`'s `S` alias private (`_S`) like `states.py`.

**M7 (states.py).** `require_transition` messages render reason values (`r.value`), not enum reprs. Pin one message in a test.

**M8 (handoff wording).** After the code fixes, PROJECT_HISTORY §18's claims about the canonicaliser and the anchors become true; re-read the paragraph and make sure every sentence is true of the tree (adjust the two sentences the review names). Add to the R082 row of `handoff/acceptance-matrix.json` a `note` field: `"logged" half is TODO(T09); the local evidence covers the rest`. Record the `freeze_allowed` answer-only guard in SESSION_STATE's Plan C section as a design note (one sentence: the refusal is a guard on `freeze_proposal` rather than a table row, because it depends on the proposal's content, not the run's state).

### Parked (do not touch; the controller records these in the ledger and SESSION_STATE)

- **M1** raw-payload hash vs normalised hash (Proposal vs checker): a Plan D design decision — the skeleton stores and hashes only `canonical_json(ProposalPayload.canonical_dict())`. Add one sentence to SESSION_STATE's open items naming it.
- **M2** null/whitespace conventions, **M4** timestamp edge cases: API-boundary decisions for Plan D; one sentence each in SESSION_STATE open items.
- **M9** negatives assert "some ValidationError" on the model side; tool-result examples skipped: the differential test covers the first; the second is T15's.
- **M10** `reason_match` prefix constraint and multi-rule negatives: cosmetic rigour, later.
- The 13 "declined to judge" lines: all accepted as declined for the reasons given.

## Gates

- `PYTHONUTF8=1 uv run python scripts/check.py` → `CHECK: GREEN` (record the pytest line; it will exceed 333 passed).
- `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts` → exit 0; record the PASS lines (counts change).
- Generator drift test green; README/STATUS counts of schemas/examples updated wherever they are stated (`grep -rn "68 examples\|38 invalid\|38 negative"` across the repo, excluding `.superpowers/`).
- ruff check + format clean; mypy strict is in check.py.
- UTF-8 no BOM, LF; Bash tool only (Git Bash); no PowerShell redirection.
- Commits: logical groups (code fixes; generator + regenerated schemas + tests; docs), each message free of any attribution trailer. Never push.
- Report to `final-fix-report.md` in this directory: per finding what changed and the test that proves it, all gate outputs, any disagreement the differential test surfaced and how it was resolved, concerns.

---

# Part 3 — Fix-wave report

# Plan C final-review fix wave: report

Base `4012ec6`, branch `plan-c`. Nothing was pushed. Commit messages carry no attribution trailers (checked by grepping the commit messages for attribution trailers, which prints 0).

## Status

DONE. The differential test found two disagreements beyond I2/I3. The spec settles both, so both are fixed and nothing is left failing. See "Differential-test disagreements" below.

## Commits

| Hash | Subject |
|---|---|
| 2a25585 | fix(core): close the final-review code seams (I1, I2, I5, M3, M5, M6, M7) |
| 97edd36 | fix(core): add the Event envelope model and close the evidence-pairing seams |
| 9f0dd2b | feat(schemas): mirror the contracts' cancel, event and outcome rules; end-anchor every pattern; add the differential test |
| 1b7d012 | docs: record the Plan C final-review fix wave and its open items |

## Per finding

**I1 (canonical.py).**
- Change: `_normalize` now runs inside the `try`. `CanonicalizationError` is re-raised unchanged, and `ValueError`/`RecursionError` are wrapped.
- The comment and the *Raises* section now describe this behaviour. The "Task 4 of Plan C" narration at the top is gone (M6).
- Test: `test_canonical.py::test_deep_nesting_is_a_canonicalization_error` covers a 2000-deep JSON array that `parse_json_strict` accepts and a 5000-deep Python list.
- Verified red against the old `canonical.py` and green after the fix.

**I2 + Minor 3 (CancelResponse).**
- `RETRIEVING/DRAFTING → FAILED` by `transition_run` exists, so FAILED does not imply a grant.
- `POST_GRANT_STATES` moved to `states.py` without FAILED. It now holds EXECUTING, OUTCOME_UNKNOWN, ESCALATED, SUCCEEDED and ABANDONED_UNVERIFIED, and the comment explains why FAILED is excluded.
- `CancelResponse` now also refuses `grant_exists=true` with a status in `PRE_GRANT_STATES`. The message is "status X is pre-grant, so no grant can exist".
- Tests:
  - `test_contracts.py::test_cancel_response_reports_grant_and_never_undo`: FAILED + no grant + `cancel_requested=true` is accepted, and QUEUED + grant is rejected with that message.
  - `test_states.py::test_post_grant_states_are_reached_only_through_a_grant`: every row into a post-grant state starts at APPROVED via `grant_execution` or from another post-grant state.

**I3 (generator seams).**
- cancel-response, which imports `POST_GRANT_STATES` and `PRE_GRANT_STATES` from `ops_core.states` (the same constants `contracts.py` uses):
  - `cancel_requested: const true`;
  - CANCELLED ⇒ `grant_exists` false;
  - `grant_exists` false ⇒ status not post-grant;
  - status pre-grant ⇒ `grant_exists` false.
- event:
  - rule (7): `payload.reason ∈ FAILED_REASONS` (from `FAILED_NO_COMMIT_REASONS`);
  - `OUTCOME_TYPES` is now derived from `outcomes.OUTCOME_EVENT_TYPES` instead of retyped. The bytes are unchanged.
- action-outcome:
  - REJECTED tombstone ⇒ reason `rejected`, and reason `rejected` ⇒ REJECTED tombstone. The condition uses `type: object`, so a null tombstone cannot satisfy it vacuously.
  - A `$comment` on `tombstone` says the identity check against `action_id`/`payload_sha256` is not expressible and that `ActionOutcome` enforces it.
- Examples:
  - valid: `outcome-failed-valid`, `tool-create_incident-failed-valid` (FAILED_NO_COMMIT with a REJECTED tombstone), `cancel-response-failed-before-grant-valid`, `event-failed-valid`;
  - negatives: `cancel-response-invalid-{not-requested, cancelled-after-grant, post-grant-without-grant, pre-grant-with-grant}`, `event-invalid-failed-conflict-reason`, `outcome-invalid-rejected-tombstone-other-reason`, `outcome-invalid-rejected-reason-aborted-tombstone`. Every `reason_match` is anchored at the field's path.
  - `outcome-failed-valid`, `cancel-response-failed-before-grant-valid` and `event-failed-valid` go beyond the brief's single tool-result example. Tool-result examples are not mutated, so these give the differential test a FAILED_NO_COMMIT outcome, a grant-less cancel response and an `action.failed` event to walk.
- Differential test: `test_schema_conformance.py::test_mutants_get_the_same_verdict`.
  - Mutations: every enum-valued field gets every other value of its enum (through nullable `anyOf`), every boolean is flipped, and every required key is removed.
  - Coverage: all 22 valid examples of modelled schemas (`MODELS` keys, which now include `event` via `outcomes.Event`), 326 mutants.
  - Null, whitespace and timestamp spellings are not mutated, and there are no exclusions.
  - Sanity check: with the 4012ec6 cancel-response, action-outcome and event schemas swapped back in, the test fails exactly on I3(a), I3(c) and the rule-(7) reasons.

**I4 (anchors).**
- Every pattern ends with `END = (?![\s\S])` instead of `$`, and digits are `[0-9]` (Python's `\d` matches non-ASCII digits).
- `SHA256` and `DIGEST` carry `maxLength: 64` and `ASSET_ID` carries `maxLength: 32`.
- `UTC_HASHED` and `UTC_REQUEST` keep format + pattern. Plain `DATE_TIME` fields also get an RFC 3339 pattern, because I read "keep the pattern as well" as covering them; rfc3339-validator accepts `…Z\n`.
- Negatives, each anchored at its field's path:
  - `message-invalid-asset-id-newline` (asset id);
  - `decision-invalid-sha256-newline` (sha256);
  - `proposal-invalid-hashed-timestamp-newline` (hashed timestamp);
  - `manual-proposal-invalid-request-timestamp-newline` (request timestamp);
  - `event-invalid-occurred-at-newline` (plain date-time, a fifth family).
- Side effects:
  - `model-pins-invalid-prefixed-digest` now also hits `maxLength` at the same path, so its `reason_match` alternates `(does not match|is too long)`.
  - `cancel-response-invalid-attempt-without-grant` started tripping the new post-grant rule. It is now derived from the FAILED example (`attempt_state: SENT`) so that only its own rule fires. The reason_match is unchanged.

**I5 (dedup_key).**
- `DedupKeyError(ValueError)` is new; the module had no error class.
- `run_id`, `proposal_id`, `action_id` and `clarification_event_id` must be `UUID` instances, and `revision` must be an `int >= 1` (bool refused). Every refusal raises `DedupKeyError`.
- Test `test_jobs_routes_outcomes.py::test_dedup_parts_are_typed_so_job_types_cannot_collide` covers:
  - the I5 cross-type collision (`clarification_event_id=2` now raises);
  - `revision` 0, -1, True and "2";
  - a string `run_id`;
  - an int `proposal_id`;
  - two literal keys pinned (`…0003:2`, `…0003:…0010`).
- The existing tests still pass, because `DedupKeyError` is a `ValueError`.

**M5 (partial).**
- `event_rules_ok` refuses a non-Mapping payload ("must be an object").
- `_validated` maps `ValueError` (circular reference) and `RecursionError` from `json.dumps` to "malformed".
- A receipt on `action.failed` and a tombstone on `action.confirmed` are refused in code. The schema refuses them in rule (8)'s new `then`.
- Tests: `test_event_rules_refuse_malformed_payloads_and_crossed_evidence`, plus the negatives `event-invalid-failed-with-receipt` and `event-invalid-confirmed-with-tombstone`.
- The late-evidence tombstone↔`action_id` cross-check stays parked.

**M6.**
- The `type: ignore` is gone; the call is split into explicit calls. No new one was added anywhere: `git diff 4012ec6..HEAD | grep "type: ignore"` shows only the removed line.
- Deleted: the changelog sentence in `outcomes.py`.
- Rewritten in present tense: the narration in `contracts.py` and `canonical.py`.
- `jobs.py` uses `_S`.

**M7.**
- `require_transition` renders `[v1, v2]` from `r.value`, and `got` from `reason.value`.
- Test: `test_states.py::test_reason_message_renders_values_not_enum_reprs` pins the full message.

**M8.**
- PROJECT_HISTORY §18:
  - "key patterns use full matches" now reads "the dedup-key patterns in `jobs.py` use full matches";
  - the 68/69 counts are marked as plan-end figures;
  - the canonicaliser sentence is now true;
  - a final-review Problem/Change pair is appended in the §18 style.
- R082 has `"note": "\"logged\" half is TODO(T09); the local evidence covers the rest"`.
- SESSION_STATE's Plan C section has the `freeze_allowed` design note and three open items for Plan D (M1, M2, M4).
- STATUS, tasks.json and BUILD_BACKLOG counts are updated. `schemas/README.md` states no counts.

**Parked, untouched:** M1, M2 and M4 (SESSION_STATE sentences only), M9, M10, and the declined lines.

## Differential-test disagreements found and how they were resolved

1. **Event envelope** (`event_id`, `tenant_id`, `conversation_id`, `run_id` or `sequence` removed: the schema rejects, the code accepted).
   - The spec is plain: the event contract requires the envelope.
   - Resolved with a small strict `ops_core.outcomes.Event` model (envelope plus an `event_rules_ok` after-validator, `TODO(T14)` to wire it into `append_event`).
   - The conformance test now uses it in place of the ad-hoc `_event_checks`.
   - Test: `test_event_model_requires_the_envelope_and_applies_the_authority_rules`.
2. **Malformed tombstone on `action.failed`** (tombstone sub-keys removed: the schema rejects, the code accepted).
   - The spec is plain: the payload's `tombstone` is the AM-13 tombstone shape wherever it appears.
   - `event_rules_ok` now validates a present tombstone on `action.failed`. I also closed the mirror seam the walker could not reach: late evidence carrying both proofs (the schema's rule (6) refused it; the code did not).
   - Test: `test_event_evidence_is_well_formed_and_never_paired_with_its_opposite`.
   - Commit 97edd36.

## Gates (tails)

- `PYTHONUTF8=1 uv run python scripts/check.py`: ruff check "All checks passed!"; ruff format clean; mypy `Success: no issues found in 14 source files`; **`379 passed, 30 skipped in 18.11s`**; **`CHECK: GREEN`**.
- `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts`, exit 0:
  - `PASS: package structure; 127 JSON files; 47 acyclic tasks; 131 covered requirements`
  - `PASS: 8 source hashes; 32 development scenario cards; 62 Python syntax checks; 6 SVG XML files; fixture meta.json current`
  - `PASS: synthetic proposal/decision/outcome example hashes agree`
  - **`PASS: 26 JSON Schema documents; 34 accepted examples; 52 negative examples failed for their stated reason; governed files LF-only`**
  - `PASS: 19 inherited source/test/integration files match original snapshot (remapped)`
  - `PASS: 26 delivered reference/ files byte-identical to handoff-1.0.zip; no extra or missing files; 19 remap targets under reference/`
  - `PASS: 161 delivered 1.0 snapshot checksums verified against handoff-1.0.zip`
- Generator: `schemas/: 25 schema documents (19 contracts, 6 tool inputs); 86 examples (34 valid, 52 invalid); index.json version 1.3.3`. The drift test (`test_schemas_generated.py`) is green inside check.py.
- Conformance module: `90 passed, 19 skipped` (86 example cases, 1 coverage check, 22 mutation cases).
- The skip total went from 29 to 30 because the new `tool-create_incident-failed-valid` is a tool-result example, which the conformance test skips with its stated reason.

## Concerns

- `Event` is new core code that the reviewer had "declined to judge" (T14 territory). I added it because the brief says to resolve a disagreement the spec settles. It is minimal (envelope plus existing rules, payload `dict[str, Any]`), but T14 may want to reshape it.
- `CancelResponse` and the schema still accept `grant_exists=true` with REJECTED, ANSWERED or INSUFFICIENT_EVIDENCE. These are not pre-grant per `PRE_GRANT_STATES`, but no grant can precede them either. Schema and code agree, so the differential test is silent. If it should be refused, that is a follow-up.
- Plain `date-time` fields now carry an RFC 3339 pattern, which is my reading of the brief's ambiguous sentence. pydantic accepts `…T12:00Z` (no seconds) and lowercase `t`/`z`. Only the former differs from the schema, and it is already the parked M4.
- One process slip: my first attempt at commit 97edd36 swept in the already-staged generator files. I soft-reset and recommitted before going on. The final history is the four commits above.

## Residual (coordinator ruling on concern (b))

Commit `9af6c53` fix(contracts): refuse a grant on terminal states no grant can precede.

- `states.py`: added `GRANTLESS_STATES = PRE_GRANT_STATES | {REJECTED, ANSWERED, INSUFFICIENT_EVIDENCE}`, with a why-comment. `PRE_GRANT_STATES` stays the cancel-eligible set.
- `CancelResponse` refuses `grant_exists=true` when the status is in `GRANTLESS_STATES`. The message is now "status X is never preceded by a grant, so no grant can exist". FAILED stays in neither set, because the table reaches it both before and after a grant.
- Generator: the cancel-response rule now derives its list from `GRANTLESS_STATES`, using the same import pattern as the other lists.
- New negative `cancel-response-invalid-rejected-with-grant` (REJECTED, grant true, cancel_requested true). Its reason_match is `^\$\.grant_exists: False was expected$`.
- Tests:
  - `test_cancel_response_reports_grant_and_never_undo` now rejects QUEUED, REJECTED, ANSWERED and INSUFFICIENT_EVIDENCE with a grant, and accepts FAILED with a grant.
  - The differential test passes: it mutates `status` across all 17 states on both cancel-response examples, so the new rule is exercised on both sides.
- Docs:
  - Counts are updated in STATUS, SESSION_STATE, tasks.json, BUILD_BACKLOG and PROJECT_HISTORY.
  - The PROJECT_HISTORY §18 sentence now names the grantless set.
  - SESSION_STATE has the design note that `outcomes.Event` is the minimal envelope the schema requires and that T14 owns its evolution.
- Gates:
  - `PYTHONUTF8=1 uv run python scripts/check.py`: **`380 passed, 30 skipped`**, `CHECK: GREEN`. Ruff and format are clean, and mypy reports no issues in 14 files.
  - `--reference-code --manifest --contracts`: exit 0, with **`PASS: 26 JSON Schema documents; 34 accepted examples; 53 negative examples failed for their stated reason; governed files LF-only`**.
  - Generator: `25 schema documents (19 contracts, 6 tool inputs); 87 examples (34 valid, 53 invalid)`.
  - Conformance module: `91 passed, 19 skipped`.

---

# Part 4 — Scoped re-review

# Plan C final-review fix wave: scoped re-review

Range `4012ec6..9af6c53` on `plan-c`. There are five commits: 2a25585, 97edd36, 9f0dd2b, 1b7d012 and 9af6c53. The working tree was clean before and after the review. The tree was not edited, apart from one accidental regeneration noted below, which produced no diff.

Sources:
- `final-review.md` (Issues section);
- `final-fix-brief.md` (rulings);
- `final-fix-report.md` (including its Residual section);
- the review package diff.

Every probe below was run against the tree, from scratch scripts in the session scratchpad.

## Per finding

| Finding | Verdict | Evidence |
|---|---|---|
| I1 canonical recursion | **Addressed** | `canonical.py:70-81`: `_normalize` sits inside the `try`; `CanonicalizationError` is re-raised unchanged; `ValueError`/`RecursionError` are wrapped. The comment and the *Raises* section match the behaviour. Probe: a 2000-deep array through `parse_json_strict` then `canonical_json` gives `CanonicalizationError`. Test: `test_canonical.py::test_deep_nesting_is_a_canonicalization_error` (2000-deep JSON and a 5000-deep list). |
| I2 FAILED pre-grant | **Addressed** | `POST_GRANT_STATES` (states.py:233-237) = EXECUTING, OUTCOME_UNKNOWN, ESCALATED, SUCCEEDED, ABANDONED_UNVERIFIED. Probe: FAILED with `grant_exists=False` and `cancel_requested=True` is accepted by both the model and the schema. Test `test_post_grant_states_are_reached_only_through_a_grant` derives this from `TRANSITIONS`. |
| M3 grant with a pre-grant status | **Addressed** | contracts.py:247-252. Probe: QUEUED with a grant is refused by both the model and the schema. |
| Residual ruling (GRANTLESS_STATES) | **Addressed as ruled** | `GRANTLESS_STATES = PRE_GRANT ∪ {REJECTED, ANSWERED, INSUFFICIENT_EVIDENCE}`. FAILED and CANCELLED are in neither set; CANCELLED has its own rule. Probe, model and schema agree on all of these: REJECTED/ANSWERED/INSUFFICIENT_EVIDENCE/QUEUED/CANCELLED with a grant are refused; FAILED with a grant and EXECUTING with a grant are accepted; EXECUTING without a grant is refused. Checked against the table: no row enters a grantless state from a non-grantless source. FAILED's sources are RETRIEVING, DRAFTING, EXECUTING, OUTCOME_UNKNOWN and ESCALATED, so it is correctly left out of both sets. |
| I3a cancel-response | **Addressed** | build_schemas.py:701-717: `cancel_requested` is `const true`; CANCELLED ⇒ no grant; no grant ⇒ status not in `POST_GRANT`; status in `GRANTLESS` ⇒ no grant. Both lists come from the `ops_core.states` constants that `contracts.py` imports, so nothing is retyped. Negatives: not-requested, cancelled-after-grant, post-grant-without-grant, pre-grant-with-grant and rejected-with-grant, each anchored at `^\$\.<field>`. |
| I3b event rule (7) | **Addressed** | build_schemas.py:494-499: `reason ∈ FAILED_REASONS`, taken from `FAILED_NO_COMMIT_REASONS`. Probe: `action.failed` with reason `conflict` is refused by the code (`EventRuleViolation`) and by the schema (invalid); with `expired` it is valid. |
| I3c action-outcome | **Addressed** | build_schemas.py:218-221 adds REJECTED-tombstone ⇔ `rejected` in both directions. `type: object` keeps a null tombstone from satisfying the condition vacuously. A `$comment` on `tombstone` names the identity check that JSON Schema cannot express. Valid FAILED_NO_COMMIT examples: `outcome-failed-valid` and `tool-create_incident-failed-valid`. Two negatives, both anchored. |
| I3 differential test | **Addressed, not vacuous** | `test_schema_conformance.py::test_mutants_get_the_same_verdict`. Measured: **326 mutants over 22 valid examples** (146 removals, 175 enum swaps, 5 boolean flips). The schema rejects 268 of them and the code rejects the same 268, so disabling either side makes at least 268 mutants disagree and the test fails. The `count` guard fails if the walker produces nothing. No schema uses `$ref` or `oneOf`, so the walker's `properties`/`anyOf`/`items` descent reaches every enum. Only the three mutation operations from the brief are used, with no exclusions. Limitation: enums inside `if/then` branches are not walked; this is acceptable for the brief's scope. |
| I4 end anchors | **Addressed** | `END = (?![\s\S])` (build_schemas.py:74) is used on every end-anchored pattern. 65 pattern nodes in `schemas/`, and none ends in `$`. Probe: 97 (pattern, value) pairs where the bare value is valid, and **0** accept the value with a trailing `\n`. These include `"A17\n"` through `tools/get_asset_status.input` (refused), a 64-hex `\n` and `…Z\n`. `maxLength` is 64 on sha256/digest and 32 on asset id. The five newline negatives are anchored at the field path. |
| I5 dedup_key | **Addressed** | jobs.py:129-183 adds `DedupKeyError(ValueError)` with typed parts. Probe: `RESUME_INPUT(run, clarification_event_id=2)` raises `DedupKeyError`, and so do `proposal_id=None` and `"x"`. The two pinned literals (`…0003:2` and `…0003:…0010`) are reproduced byte-for-byte. |
| M5 (partial) | **Addressed as ruled** | A non-Mapping payload (`[]`, `"x"`, `3`, `None`) raises `EventRuleViolation`, not `AttributeError` (probe). `_validated` maps `ValueError`/`RecursionError` to "malformed". The receipt on failed and tombstone on confirmed are refused in code (outcomes.py:244-255) and in the schema's rule-(8) `then`, with one negative each. The late-evidence identity cross-check stays parked, as ruled. |
| M6 comments | **Addressed** | No `type: ignore` under `core/src` or `tests/plan_c`; the one grep hit is the pre-existing explanatory comment at test_jobs_routes_outcomes.py:358. No "is gone"/"former" in outcomes.py, and no "Task N"/"Plan C" narration in canonical.py or contracts.py. `jobs.py:68` uses `_S`. |
| M7 messages | **Addressed** | states.py:261-264. `test_reason_message_renders_values_not_enum_reprs` pins the full string. |
| M8 handoff wording | **Addressed**, see Minor 2 | The §18 sentences are now true of the tree: the canonicaliser, "the dedup-key patterns in `jobs.py`", and the counts marked as plan-end figures. The R082 `note` is present. SESSION_STATE has the `freeze_allowed` design note, worded as "intent, not state", which is more accurate than the brief's "content". |
| Extra seam: `outcomes.Event` | **Faithful and minimal** | This is the envelope that `event.schema.json` already required: ids, `sequence ≥ 1`, type, `occurred_at`, source, `payload: dict` and the `event_rules_ok` after-validator. It is strict and closed, carries `TODO(T14)`, and is recorded in SESSION_STATE as T14's to evolve. It adds no rule beyond what the schema and AM-14 already state. |
| Extra seam: malformed tombstone on `action.failed`, and late evidence carrying both proofs | **Faithful and minimal** | A present tombstone on `action.failed` must be a well-formed `Tombstone`; the schema already typed `payload.tombstone` as TOMBSTONE (non-nullable). A null tombstone is refused on both sides. Late evidence with both proofs is refused on both sides, mirroring the schema's existing rule (6), which pairs SUCCEEDED with a receipt and no tombstone and the reverse otherwise. Neither change adds a rule that AM-14 or the schema did not already have. |

## New findings

Critical: none. Important: none.

Minor:
1. **`core/src/ops_core/states.py:231` is 121 columns.** It is the new `GRANTLESS_STATES` comment from 9af6c53. Ruff does not catch it because E501 is not selected (`pyproject.toml` sets only `line-length = 120`, which the formatter does not apply to comments). This breaks the ≤120 rule and CODE_COMMENTS rule 10. Fix: rewrap the comment.
2. **`docs/PROJECT_HISTORY.md:123-125` contains literal newlines.** In the new final-review Problem paragraph, `"A17\n"` and `"…Z\n"` were written with real line breaks inside the code spans. Markdown renders them as `"A17 "` and `"…Z "`, so the sentence that explains the trailing-newline defect loses its example. Fix: write the escape as text (`"A17\n"`).
3. **No test derives `GRANTLESS_STATES` from the table**, unlike `POST_GRANT_STATES` (`test_states.py:247-253`). Failure scenario: T09 adds a row into ANSWERED, REJECTED or INSUFFICIENT_EVIDENCE from a post-grant state. `CancelResponse` and the schema would then refuse a truthful `grant_exists=true` response, the same class of defect as I2, and no test would fail. Fix: add the mirror assertion. Today the set is correct: the probe found no offending rows.

Observation, not counted: `test_dedup_validates_parts` dropped its `proposal_id=None` case. The probe shows it is still refused (`DedupKeyError`, "as a UUID").

## Commands and probes (tails)

- `PYTHONUTF8=1 uv run python scripts/check.py 2>&1 | tail -4`: `380 passed, 30 skipped in 22.46s`, `CHECK: GREEN`.
- `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts; echo exit=$?`:
  - `PASS: 26 JSON Schema documents; 34 accepted examples; 53 negative examples failed for their stated reason; governed files LF-only`
  - the other six PASS lines;
  - `exit=0`.
- commit messages 4012ec6..9af6c53 grepped for attribution trailers: no output (grep exit 1).
- `pytest tests/plan_c/test_schemas_generated.py -q`: `2 passed`. Separately, I ran `scripts/build_schemas.py` by accident (with `--help`, which it ignores, so it regenerated the tree). It printed `25 schema documents (19 contracts, 6 tool inputs); 87 examples (34 valid, 53 invalid); index.json version 1.3.3`, and `git status` stayed clean afterwards. The committed tree is the generator's output.
- `pytest tests/plan_c/test_schema_conformance.py -q`: `91 passed, 19 skipped`.
- The `probes.py` scratch script printed:
  - p1: `CanonicalizationError`;
  - cancel matrix: 9/9 OK, with model = schema = expected;
  - newline: 0 of 97 accepted;
  - dedup: `DedupKeyError`, and both pinned literals True;
  - rule (7): code and schema both refuse `conflict`;
  - non-Mapping: all four refused with `EventRuleViolation`.
- The `count_mutants.py` scratch script printed `22 examples, 326 mutants {'remove': 146, 'enum': 175, 'bool': 5}` and `rejected by schema 268, by code 268`.
- M6 greps: listed above.
- `awk 'length > 120'` over the 11 changed `.py` files found `states.py:231` (121, new) and `test_states.py:1` (164, pre-existing and unchanged).
- Docs:
  - STATUS, SESSION_STATE, tasks.json and BUILD_BACKLOG counts are true of the tree: 25 schemas, 87 examples (34/53), 380/30, and conformance 110 = 87 + 1 + 22, i.e. 91 passed and 19 skipped. The added examples are 34 − 30 = 4 valid and 53 − 38 = 15 invalid.
  - M1, M2 and M4 appear as SESSION_STATE "Open items for Plan D".
  - The acceptance matrix only gains the R082 note. No vocabulary stronger than RECORDED_LOCALLY / IMPLEMENTED_LOCALLY_VERIFIED was added.
  - The remaining "68 examples"/"38 invalid" mentions are marked as historical or plan-end figures.

## Verdict

The fix round addressed every finding and the residual ruling, with no new Critical or Important breakage. There are 3 Minors: a 121-column comment, literal newlines in PROJECT_HISTORY §18, and no table-derived test for GRANTLESS_STATES.


# Plan O final review record — T23 development eval set, graders and rubric

Branch `plan-o`. The whole-branch review covered `e91b27b..ad74fcd`, from the plan review record to the close-out: four
tasks and the close-out, each building task with one task review and one fix round, recorded in
`docs/PROJECT_HISTORY.md` §32. It was also the only review of the close-out's records. No agent opened holdout case
material, connected to a database other than the test profile's `ops_test`, or called a generation model.

Outcome: ready to merge with fixes. 0 Critical, 3 Important, 8 Minor. All of them concern wording in the records and
the interfaces:
- which cause of the safety flag feeds the cross-tenant leakage gate;
- condition A's abstention debt was declared for half of the cases it covers;
- P06's lexical miss is confounded by a unit word.

The controller ruled every item fixed. The fix wave is `1abef84`: one new test, red first, and the numeric report
re-rendered from its committed JSON with every figure unchanged. The controller checked the wave's diff against the
rulings instead of running a scoped re-review, as the owner asked for a lean process.

Gates after the wave:

| Gate | Result |
|---|---|
| dev | 1539 passed, 219 skipped |
| live (`--profile test`) | 1737 passed, 21 skipped |
| `verify_handoff.py --reference-code --manifest --contracts` | exit 0 |

---

# Controller rulings on the final review

## Plan O final review — controller rulings (review: C:\Users\joeys\Desktop\MLOps\.superpowers\plano\final-review.md)

Verdict: ready to merge with fixes. 0 Critical, 3 Important, 8 Minor. One fix wave follows; the controller checks the
diff.

### Important — fix
- **I1. Name how the flag maps to the gate.** Say it in the `$comment` of `evals/quality-gates.schema.json` and in the
  `ops_core.grading` module docstring:
  - the gate `cross_tenant_leakage` counts only the flag's `cross_tenant` cause;
  - `unpermitted` (retired, draft or unknown IDs) is a citation-validity failure, not a leak.
  - Add a debt line: T25 counts each cause separately.
  - No code change.
- **I2. Widen the condition-A debt line.** Change it in SESSION_STATE, the T23 note in tasks.json and BUILD_BACKLOG.md
  to say:
  - a manual proposal fails abstention on every non-proposal case (the answer and abstain expectations alike);
  - how condition A is scored there → T25.
- **I3. State that P06 is confounded.** P06's pair also differs by "mm" against "millimetre", and corpus-1 never
  contains "mm", so the lexical miss cannot be put down to the decimal split alone.
  - Add this to `scripts/numeric_tokens.py`'s markdown (as a note on any lost pair whose control changes more than the
    number, or a fixed note for P06; the writer chooses the general form if it is cheap).
  - Re-render `reports/retrieval/t23-numeric-tokens.md` from the committed JSON, with every figure unchanged.
  - Correct the six records that repeat "decimal pair lost: P06" so they say confounded.
  - Add a debt line: an unconfounded decimal pair → the next retrieval change.

### Minor — fix (cheap)
- Mark the 2026-10-20 dates as UTC.
- §32 names the declined minors: Task 2 m6 was a report miscount, and Task 3 m11 is a JSON `$comment` that cannot
  wrap.
- "No model ran" becomes "no generation model ran" (the embedding model did run).
- The safety scan also scans dict keys, with one test.
- The "task 2 review" citation names `docs/reviews/plan-review-o-2026-10-19.md` or the commit.
- The test's `Verdict(…, "rule")` uses a real reason name.
- Fix the two wording slips in the notes.
- Make `rb._rate` public (`rate`), keeping the old name as an alias if other callers use it; or keep `_rate` and add a
  comment. The writer chooses.

### Gates after the wave
Dev, live (`git checkout -- reports/` afterwards, keeping nothing new) and verify_handoff. Update every stated count the
new test changes.

---

# The final review

## Plan O final whole-branch review (T23), e91b27b..ad74fcd

Reviewer: final whole-branch reviewer (read-only). Method: `requesting-code-review/code-reviewer.md`.
Read in passes: the diff package (records, `grading.py`, schemas and cases, rubric, numeric script, report and tests),
then the plan, the plan review record with its rulings, the controller's facts file and the SDD ledger, the task 3 and
task 5 reports, SA:640-676, AGENTS.md and docs/CODE_COMMENTS.md. The holdout was not touched: no file named
`*holdout*` or `*seal*` was opened, and every grep excluded both.

What I ran (non-live, read-only):
- `uv run python -m pytest tests/plan_o -q`: **77 passed** (64 planned + 13 from the review rounds, as recorded).
- A dependency-graph script over `handoff/tasks.json` (`scratchpad/plano/final/deps.py`).
- A case-summary script over `evals/dev/cases.jsonl` (`final/cases.py`): 60 rows, mix as ruling 2, 30 per tenant.
- A report check (`final/numrep.py`): `numeric_tokens.markdown(<committed JSON>)` equals the committed `.md`
  byte for byte, and `queries_sha256` matches the committed query file.
- A grader probe (`final/probe.py`) for condition A on answer cases and for references hidden in dict keys.
- `git merge-base --is-ancestor plan-n plan-o`: true (the stacking claim holds). The working tree stayed clean.

### Strengths

- **The grader API is what T25 needs, and it is fail-closed where it matters.** `grade(output, index)` gives per-trial
  `Grades` (so T25 can compute trial-level rates for SA:665's bootstrap) and `case_passes` implements SA:665's 2-of-3
  for B/C and the one manual trial for A, refusing mixes and wrong counts (`core/src/ops_core/grading.py:372-396`).
  `None` for a grader that does not apply keeps T25's denominators honest (schema on A per SA:660, sufficiency on
  abstain cases). `case_safe` is any-trial (SA:666). `safety_findings` refuses an index built for another instant
  (`:343-344`) and scans every string of a malformed reference list (`:348`).
- **Reasons are a closed `Literal`** (`:47-68`), and `tests/plan_o/test_grading.py` exercises every one of the 20
  reasons, including both `question_unexpected` branches (`:316-318` via `:137-138`, `:324-325` via `:132`). The
  "unit-tests every rule of every grader" claim in the records is true.
- **The labels are checked against an independent anchor.** `test_dev_cases.py:85-102` proves every required/allowed
  ref is returnable for the tenant at the cases' instant *and* that the returnable set equals the hand-written
  `RETURNABLE_AT_AS_OF`, so the oracle is not circular. The proposal-alert-in-interval test covers every proposal case.
  I re-derived the interval arithmetic for the tight cases (DV-047: B22-vibration-001 at 24.7 h sits just outside its
  24 h window, so its abstention label is right).
- **The rubric's quotes are tested word for word** and its worked drafts must pass the schema and citation graders
  (`test_rubric_and_schemas.py:57-90`). The quote-count guard (`:86`) closes the "unparsed quote escapes" gap.
- **The quality-gates schema encodes SA:673 exactly** (all three safety metrics required via `contains`, each fixed at a
  blocking point 0) and forbids schema/groundedness gates on A (SA:660); its `$comment` explains each choice rather
  than inventing rules.
- **The records are, with the exceptions below, true.** I verified: the range and commit list; 1538/219 and 1736/21
  (1538 + 219 - 21 = 1736; the plan's 1722 is one below 1525 + 219 - 21 = 1723); the numeric figures in all six places
  against the committed JSON; errata 112-113 against the code and schemas (the metric enum is exactly
  `GRADERS + groundedness_mean + the three safety metrics`, conditions A/B/C); SA:765 does assign the schema to T23;
  R073 belongs to T25; R111's seven evidence paths exist, and `IMPLEMENTED_LOCALLY_VERIFIED`/`RECORDED_LOCALLY`
  follow the matrix's own vocabulary note (core library plus tests that pass in `check.py`); the five process
  slips in PROJECT_HISTORY §32 match the facts file one for one, including the controller's two; the per-task review
  counts (6m, 6m, 11m, 0C/1I/2m) and test increments (+8, +3, +2, +0) match the ledger; the §33 renumbering left no
  stale reference (the only "section 32" citation, `SESSION_STATE.md:1014`, means the new §32; no anchor links exist).
- **The next step is right.** Against the graph: T19 (deps T07, T17, T02, T03, T44) and T41 (T03, T17) are the only
  PLANNED tasks whose dependencies are all DONE or DONE_PENDING_OWNER; T02/T03/T44 are DONE_PENDING_OWNER, so both wait
  on owner steps. T20←T19, T21←T20, T22←T21, T24←T22, T25←{T22, T41}, and every other PLANNED task depends on T22 or
  later. `current_milestone` stays M06 (ruling 12). The close-out's statement is exact.
- **Holdout custody holds.** No file in the diff reads, holds or points to holdout case material; `load_cases` is
  pinned to `DV-` ids and `split: development`, so a holdout row would be refused. No secret, token, credential or
  private address appears in the added lines (scanned).

### Issues

#### Critical (Must Fix)

None.

#### Important (Should Fix)

**I1. The safety gate `cross_tenant_leakage` has no stated relation to the flag the graders compute.**
- Files: `evals/quality-gates.schema.json:4,13,31` (the gate metric `cross_tenant_leakage`);
  `core/src/ops_core/grading.py:45,196-199,334-357,399-407` (the flag `cross_tenant_or_unpermitted`, with the causes
  `cross_tenant` and `unpermitted`, where `unpermitted` covers the tenant's own retired or draft sections and any
  unknown ID). The schema's `$comment` says only "Metric names are ops_core.grading.GRADERS plus groundedness_mean and
  the three safety metrics". No file says which grader output feeds `cross_tenant_leakage` (I grepped the whole tree).
- Failure scenario: T25 wires `case_safe` (both causes) into the blocking `cross_tenant_leakage` gate. A model that
  invents an evidence ID, or cites version 1 of a retired procedure, in one of three trials then fails a blocking
  release gate, and the published report calls it a cross-tenant leak, which is a false safety claim in a portfolio
  report. Or T25 counts only the `cross_tenant` cause, and the `unpermitted` events that ruling 4 deliberately made
  any-trial safety are measured by nothing. Both readings fit the code, and they decide a blocking gate. (The other
  two safety metrics, `unauthorized_writes` and `fabricated_success`, have no producer here either; they are run-level
  facts for T25, which is fine, but nothing says so.)
- Fix (no code change needed): one sentence in the schema's `$comment` and in `grading`'s module docstring naming the
  mapping. My suggestion: `cross_tenant_leakage` counts trials whose `safety` contains `cross_tenant`, and `unpermitted`
  is reported beside it as its own any-trial count. Alternatively, add a debt line "the mapping of
  `Grades.safety` to the SA:673 gates, and the producers of `unauthorized_writes` and `fabricated_success` -> T25".

**I2. Condition A also fails every answer-expected case by construction, and the debt list declares only the abstain half.**
- Files: `core/src/ops_core/grading.py:231-244,312-313,329-330`; the debt line in `SESSION_STATE.md` ("condition A
  cannot abstain ... `check_abstention` fails A on every abstain-expected case by construction ... → T25"), repeated
  as "condition A on abstain cases" in the T23 note in `handoff/tasks.json` and `handoff/BUILD_BACKLOG.md:148`.
- Failure scenario: `from_manual_proposal` always produces kind `proposal`. On all 29 `answer_only` cases `check_abstention`
  returns `proposal_on_answer_only`; on the 12 answer-expected ones it would be `kind_mismatch` even without the intent
  rule. Measured (`final/probe.py`): DV-009 and DV-037 (answer) give `proposal_on_answer_only`; only the 19
  proposal-expected cases can pass. So A's abstention rate is capped at 19/60 by construction, not the 31/60 the debt
  line implies. SA:698 ("nothing not on the list may be shortcut") makes this an undeclared shortcut, and T25 reading
  the debt list will scope A's denominators too wide.
- Fix: widen the debt line and the two notes to "condition A on every non-proposal case (abstain- and
  answer-expected): a manual proposal is always a proposal, so `check_abstention` fails it there by construction; how A
  is scored or scoped there → T25".

**I3. The numeric report blames P06's loss on the decimal split, but the pair also differs in a word the corpus lacks.**
- Files: `evals/retrieval/numeric-queries.jsonl:11-12` (N06 "B22 offset 0.05 mm or 0.10 mm?" against C06 "B22 offset
  five or ten hundredths of a millimetre?"); `reports/retrieval/t23-numeric-tokens.md` (the "decimal pairs lost: P06"
  finding); `scripts/numeric_tokens.py:1-11` (the premise that the pair isolates the number); and the same claim in
  SESSION_STATE, STATUS, PROJECT_HISTORY §32 "Result", and the T23 notes in tasks.json and BUILD_BACKLOG.
- Evidence: the corpus never contains `mm` (grep over `data/corpus`: no match). BETA-PUMP-ALIGN v2's tolerance
  section says "millimetres". After revision 0011's normalisation N06's words are `b22 offset 0 05 mm or 0 10 mm`,
  and only `b22` and `offset` can match the chunk. C06 also matches `millimetr`. So C06 has one more matching lexeme
  for two reasons: the split decimals, and `mm` against `millimetre`. Written as "0.05 millimetres or 0.10
  millimetres", N06 would carry the same `b22 offset millimetr` lexemes as its control. The measurement therefore
  cannot say the split cost P06's hit. The test docstring's own rule, "the pair would then measure more than the
  number" (`tests/plan_o/test_numeric_tokens.py:3-5`), is broken by P06, and in a milder way by P03 ("100 mm" against
  "hundred millimetres"), whose numeric query still hit.
- Failure scenario: the records hand the lexical question to T20 with "1 of 3 decimal pairs lost" as its evidence. A
  T20 planner reads that as a measured cost of the split and may propose the normalisation change on a confounded
  pair. The close-out decision (no change, because the loss is not total) still stands either way. The record of what
  was measured is wrong.
- Fix: add one sentence to the records' numeric finding, and to the report if it is re-rendered, saying that P06's
  numeric query also writes "mm", which corpus-1 never uses, while its control says "millimetre", so the miss cannot be
  attributed to the decimal split alone. Optionally add a debt line: a clean P06 pair in a later dev-set version. No
  re-run is needed for this branch.

#### Minor (Nice to Have)

**m1. Dates.** `SESSION_STATE.md` "Plan O executed (2026-10-20 ...)" and "**Update (2026-10-20)**", and `STATUS.md:372`
"Plan O executed (2026-10-20 ...)", are UTC dates (the task 5 report says `date -u`). Every commit in the range is
dated 2026-10-19 local, the same section dates the owner steps to 2026-10-19, and Plan L marked its UTC date as
"UTC". Fix: write "2026-10-20 UTC" or use the local date.

**m2. PROJECT_HISTORY §32 does not say which minors were declined.** The ledger has Task 2's fix round covering
"m1-5" of six and Task 3's report "Minor 11: skipped as instructed". §32 says "approved with six minors" and "eleven
minors" and then lists only fixes, which implies that all were fixed. The history standard records every round's
problems and fixes. Fix: add one clause each, naming the declined minor and the reason.

**m3. "No model ran"** (`STATUS.md` Plan O section; `SESSION_STATE.md` Plan O "Gates" line). The live numeric test ran
the pinned `nomic-embed-text` embedding model through local Ollama (`tests/e2e/test_numeric_tokens_live.py:47-50`).
Fix: "no generation model ran".

**m4. The safety scan skips dict keys.** `_strings` yields dict values only (`grading.py:247-256`). A malformed
`evidence_refs` such as `{"BETA-PUMP-ALIGN:v2:tolerance": 1}` raises no flag. With a string value
(`{"BETA-…": "why"}`, probed) it raises `unpermitted` for the value, so the cause is wrong. The schema and citation
graders still fail such a draft, so only the safety count is affected. Fix: also `yield from _strings(key)` for each
key, plus one test row.

**m5. An unfollowable citation in a comment.** `grading.py:345` cites "task 2 review, Minor 1". Task reviews are not
retained in the repository, so the reader cannot follow it (CODE_COMMENTS rule 5). Fix: cite
`docs/PROJECT_HISTORY.md` §32, or state the defect inline (the recursive scan exists because nested refs escaped the
flag).

**m6. A test builds a `Verdict` with a reason outside `Reason`.** `tests/plan_o/test_grading.py:190` builds
`Verdict(passed, "rule")`. Tests are not mypy-checked, so the gate passes. This is the one place that contradicts
"reasons are rule names". Fix: use `"valid"`.

**m7. Wording in the handoff notes.** The R111 note says "every label a returnable section of the case's tenant and asset
family", but the test also admits family-less documents (`test_dev_cases.py:98`). The T23 note says "every threshold
the owner's", but the safety thresholds are fixed at 0. Fix: "... or a family-less document"; "every quality threshold
the owner's".

**m8. A private import across modules.** `scripts/numeric_tokens.py:184-186` calls `rb._rate`. Fix: make the helper
public, or wrap it.

### Recommendations

- `case_passes` trusts its caller to pass one case's trials in one condition. T25 could pass a `(case_id, condition)`
  pair, or `Grades` could carry them, so that a grouping bug raises an error instead of silently mixing.
- Fold I1-I3 and m1-m3 into one records-only commit. None of them needs a code change. m4 is a two-line code change
  with one test.

### Declined to judge

- Whether the dev-case schema's first six fields really mirror `evals/holdout-case.schema.json`: the custody
  instruction excludes every `*holdout*` file, so I did not open it.
- The safety flag reads `evidence_refs` only, not free text such as another tenant's content pasted into `summary`.
  No deterministic grader can see that, and it is the groundedness label's job (BS:452), as the debt list says.
- That the quality-gates schema lets the owner put safety gates on condition A only, with none on B or C. The
  `$comment` says that requiring B and C would invent a rule beyond SA:673. The task 3 review accepted this, and I
  did not re-litigate it.
- Individual gold labels (for example DV-053's clarify label, although an alert falls in its window). They are
  agent-authored (BS:605), went through the round-1 disputed-label pass and Task 1's review, and only their mechanical
  rules were checked here.
- Whether an unknown or retired citation should count as a safety event at all. The controller ruled on this
  (departure 2, accepted). I1 asks only that its mapping to the gate be stated.
- `ROOT = Path(__file__).resolve().parents[3]` (`grading.py:39`) assumes an editable install. `embeddings.py` and
  `tool_contracts.py` set the precedent, and packaging is T30's debt.
- The live gate (1736/21) and `verify_handoff`: these were not re-run, because my instructions allow focused non-live
  tests only. The figures are taken from the brief, the ledger and the task 5 report, which agree with each other.
- Condition A on abstain-expected cases: declared debt. I2 covers only the undeclared answer half.

### Assessment

**Ready to merge?** With fixes.

**Reasoning:** The graders, the cases, the rubric and the schemas are correct, typed, pure, and consistent with SA:656-676
and the rulings. The tests are thorough, and every count, commit, erratum and next-step claim in the close-out checks
out. Three Important findings remain, all in records and interface wording rather than code: the unmapped
`cross_tenant_leakage` gate, condition A's answer cases missing from the debt list, and the confounded P06 attribution.
Each is a sentence or two to fix before the PR is opened.

Counts: Critical 0 / Important 3 / Minor 8.

# Plan O inputs: T23 (development eval set, gold labels and rubric) — fact sheet

Prepared 2026-10-19 on branch `plan-o` at `128258c` (= `plan-n` `df711ab` plus one records commit, `128258c`; PR #12
`plan-m` -> `main` and PR #13 `plan-n` -> `plan-m` are open and unmerged; the working tree was clean). Read-only on the
repository except this file. Facts only, no design. Citations: `SA:<line>` = `SPEC_AMENDMENTS.md`, `BS:<line>` =
`BUILD_SPEC.md` (line numbers as of `128258c`); the amendments win wherever the two conflict. Repository files are
cited as `path:line`. Nothing was run against a database, Keycloak, Ollama or any service for this sheet, no network
connection was made, and no secret, token or `.env` value was opened. Three read-only helper scripts (in the session
scratchpad, run as `uv run python -I <path> < /dev/null`) summarised the non-holdout `evals/*.jsonl` files, corpus-1
(through `ops_core.corpus.load` and `returnable`) and the committed retrieval reports; every other fact is read from
the files.

**Holdout custody.** No holdout case file, label or seal was opened, read, grepped, hashed or listed. Only
`evals/HOLDOUT.md` and `evals/holdout-case.schema.json` were read. Every repository grep excluded paths matching
`*holdout*`. `evals/holdout.sha256` does not exist in the tree (`ls evals` lists `HOLDOUT.md`, `README.md`,
`development-seeds.jsonl`, `handoff-development`, `holdout-case.schema.json`, `probe`, `retrieval`); no directory the
docs call the holdout exists in the repository.

Note on line numbers: AM-00 superseded list SA:30-55 (§20 SA:39); AM-02 demo claims SA:110-114; AM-10 state table
SA:133-143 (DRAFTING row SA:137), clarification signal SA:147; AM-16 graph router SA:377, model router SA:379; AM-20.3
`freeze_proposal` SA:453, `create_manual_proposal` SA:456; AM-31 SA:593-620 (settings SA:596, probe inputs SA:603,
identical-repeat SA:605, prompt hashes SA:607-608, 1.0 draft schema SA:610); AM-50 SA:638-678 (corpus SA:640-645,
scenario suite SA:647-650, evaluation table SA:652-662, statistics SA:664-669, quality gates SA:671-674, labelling load
SA:676, solo-owner SA:678); AM-60 SA:680-728 (T23 added in 1.2, SA:720); AM-80 SA:743-778 (checker SA:749, evals
schemas row SA:765, run manifest SA:770). BUILD_SPEC: success definition BS:42, evals directory BS:210, states BS:309,
transitions BS:315-316, `search_procedures` BS:386, §11 BS:409-431 (chunking BS:415, filtering BS:417, bundle BS:419,
fixtures BS:431), §12 prompts BS:447, validation BS:449-452, repair BS:454, abstain BS:456, budget BS:551, §19 layer 8
BS:593, §20 BS:599-613 (conditions BS:601, dataset BS:603, holdout BS:605, trial record BS:607, metrics BS:609,
blockers BS:611, gates BS:613), CI BS:662-664, release manifest BS:670, M13 BS:714, holdout review BS:751, source S21
BS:795.

---

## 1. T23 verbatim, its acceptance rows, the debts pushed to it, and its consumers

### 1.1 T23 (`handoff/tasks.json:969-986`)

- **id/milestone/title:** `T23` (`:970`), `M09` (`:971`), "Development eval set, gold labels and rubric" (`:972`).
  M09 (`tasks.json:107-117`): title "Scenario suite and model-quality evaluation", `required_for_v1: true`, task_ids
  `T23`, `T24`, `T25`, milestone `status: "PLANNED"`. The file's `current_milestone` is `"M06"` (`:3`).
- **instructions** (`:973`, verbatim): "~60 dev cases over the expanded corpus with gold labels; deterministic graders
  for schema, citations and abstention; groundedness rubric for owner labelling."
- **depends_on** (`:974-976`): `["T17"]` (T17 `DONE`, `:738`).
- **requirement_ids** (`:977-979`): `R111`.
- **status** (`:980`): `"PLANNED"`. **external_approval_required** (`:985`): `false`.
- **definition_of_done** (`:981-984`, verbatim):
  1. "evals/dev/ cases and labels committed; graders unit-tested."
  2. "Rubric with worked examples and inter-trial labelling instructions."
- **review_notes:** T23 has **no** `review_notes` key (the entry ends at `:985`).
- `handoff/BUILD_BACKLOG.md:147` repeats it unchecked: "- [ ] **T23 Development eval set, gold labels and rubric** —
  ~60 dev cases over the expanded corpus with gold labels; deterministic graders for schema, citations and abstention;
  groundedness rubric for owner labelling. Requirements: R111. Depends on: T17."
- AM-60 1.2 changes (SA:715-720): "**New tasks:** … T23 development eval set and rubric." (SA:720).
- `tasks.json:4` note: "A proposed erratum awaiting the owner's decision does not change a task's status; a task met
  'subject to' an erratum stays DONE."
- Next-step records: `SESSION_STATE.md:11-12` "Next is T23 (unblocked); T19 and T41 wait on owner steps, T20 on T19,
  T25 on T22, T23 and T41."; `SESSION_STATE.md:1457` "… write the plan for T23 (the development eval set, gold labels
  and rubric: the earliest dependency-satisfied PLANNED task in `handoff/tasks.json` after T18, which depends on T17
  only; T19 and T41 wait on owner steps, T20 on T19)."; `STATUS.md:369` "- Next: T23 (the development eval set)."
  `docs/reviews/plan-n-final-review-2026-10-19.md:246-247` confirms the scan.

### 1.2 Acceptance rows (`handoff/acceptance-matrix.json`)

- **R111 (:1937-1952)** — category `evaluation`; "Development evaluation set has gold labels and calibrated graders";
  `implementation_status: NOT_IMPLEMENTED_OR_NOT_TARGET_VERIFIED`; expected_evidence (verbatim): "~60 labelled dev
  cases; deterministic graders unit-tested; groundedness rubric documented."; `evidence_status: NOT_RUN`;
  `evidence_paths: []`; `source: SPEC_AMENDMENTS.md`; milestone `M09`; `blocking_for_v1: true`; owners `T23` only;
  suggested_test `tests/acceptance/test_r111_development_evaluation_set_has_gold_labels_and_c.py`; no note.
- R111 is **not** in `handoff/ACCEPTANCE.md` (the 1.0 snapshot, superseded per its `:3`, which says the matrix "adds
  R081–R131 from `SPEC_AMENDMENTS.md`").
- Matrix note (`acceptance-matrix.json:3`): suggested_test paths are targets; `RECORDED_LOCALLY` = the evidence-path
  tests pass in `scripts/check.py` and CI; `RECORDED_LOCALLY_LIVE` = passes against the running dev profile with
  `OPS_LIVE=1`, collected but skipped by `check.py` and CI. `tests/acceptance/` does not exist.
- Rows naming the evaluation, holdout, graders, groundedness, citations or abstention (all `NOT_RUN`,
  `NOT_IMPLEMENTED_OR_NOT_TARGET_VERIFIED` unless stated):
  - **R070 (:1201-1215)** T25, M09, "Manual RAG and orchestration baselines use comparable tasks"; expected "Same
    permitted evidence/final approval rule; report measured effort and real outcomes, no fabricated timing."
  - **R071 (:1216-1232)** T03/T41/T25, M00, "Final holdout is kept out of the tuning context"; expected "Holdout intents
    sealed (T03) and gold labels sealed (T41) with hashes recorded outside the local repo before dependent tasks;
    holdout usage logged in T25." (`ACCEPTANCE.md:77`, 1.0: "Record split grouping/reviewer custody/used status; leaked
    cases replaced before new holdout claim.")
  - **R072 (:1233-1247)** T25, "Model trials are repeated and isolated"; expected "Reset app/destination namespaces per
    trial and publish every trial/config/denominator."
  - **R073 (:1248-1262)** T25, "Semantic grading is calibrated and separate from receipts"; expected "Compare grader
    with reviewed labels; deterministic destination state decides action outcome." (SA:661 ties the ~20% re-label and
    intra-rater kappa to R073.)
  - **R074 (:1263-1277)** T25, category `release`, "Safety failures and unset quality gates block release"; expected
    "Inject unauthorized/duplicate/fabricated-success failure or missing threshold; promotion fails."
  - **R097 (:1667-1686)** T24/T27/T29/T32, M09, "30 development cards run as state-asserting tests"; expected "All
    cards except DEV-013 and DEV-032 executable; cards join as capabilities land (T24, T27, T29, T32)."
  - **R033 (:625-646)** T17, `IMPLEMENTED_LOCALLY_VERIFIED` / `RECORDED_LOCALLY_LIVE`; evidence includes
    `evals/retrieval/dev-queries.jsonl`; note: "47 agent-authored development queries labelled against corpus-1 …
    Missing sources are measured, not guaranteed … R033 is met subject to the owner's decision on erratum 102 … The
    minimum rank was chosen on these same queries, so the figures are development figures, not held-out ones."
  - **R034 (:647-670)** T18, `IMPLEMENTED_LOCALLY_VERIFIED` / `RECORDED_LOCALLY_LIVE`; note ends: "The vector threshold
    (0.68) was chosen on these same queries by a rule fixed before measuring: development figures, not held-out ones
    (the holdout is T25's) …".
  - **R036 (:686-700)** T19, "Retrieved instructions cannot grant tool authority"; expected "Inject administrator-style
    text into SOP fixture; no permission/action boundary changes."
  - **R040 (:746-760)** T19, "Invalid model schema has a bounded repair policy"; expected "Repeated malformed JSON
    exhausts one repair within remaining budget; no incident."
  - **R041 (:761-775)** T19, "No fake or hosted fallback masquerades as real output".
  - **R081 (:1368-1383)** T02, "Local model runtime profile is measured before use"; expected "Probe report with >=30
    distinct inputs … first-pass/post-repair validity with Wilson CIs, identical-repeat rate …".
  - **R114 (:1985-2000)** T20, "Read-only answers complete as ANSWERED without proposals"; expected "Answer path cites
    evidence, creates no proposal or grant, ends ANSWERED."
  - **R130 (:2270-2286)** T19/T25, "The model route is explicit, recorded and never silently substituted"; expected
    "Run manifest records model_route, digest, prompt_version, corpus_version; a missing or mismatched model fails
    closed; B and C evaluation conditions show identical routes."
  - No row names "rubric", "groundedness" or "gold" other than R111 and R071 ("gold labels sealed (T41)"); no row names
    a citation grader. The word "citation" appears in R035's expected evidence only ("… citation viewer do not re-expose
    it", `:679`).

### 1.3 Debts other tasks pushed to T23

- **From T18 (Plan N) — the numeric-token debt.** Plan N debt list (`SESSION_STATE.md:1284-1315`), `:1292-1294`
  verbatim: "numeric tokens (`4.5`, `M8x1.25`) cannot match as one lexeme (the query is normalised to `[a-z0-9]+` words
  while the chunk text is parsed raw): the development set gains numeric-token cases and measures the loss first → T23
  (Plan N ruling 10);". T18's close-out note (`tasks.json:804`) "Deferred: … numeric tokens -> T23"; `STATUS.md:366-367`
  "numeric tokens -> T23". Plan N plan review ruling 10 (`docs/reviews/plan-review-n-2026-10-19.md:143-145`):
  "**Numeric tokens (FS Q10) — re-homed to T23.** The lexical body stays byte-identical in T18 so the comparison is
  against the committed baseline. Debt line → T23: the development eval set adds numeric-token cases and measures the
  loss; a fix only with that evidence (BS:71)." Plan N plan: `docs/superpowers/plans/2026-10-19-first-slice-n-vector-retrieval.md:269`
  "10. **Numeric tokens** — re-homed to T23 (debt list)."
- **History of that debt:** Plan L debt list (`SESSION_STATE.md:1224-1225`): "the query is normalised by
  `regexp_replace('[^a-z0-9]+', ' ')` while chunk text is parsed raw, so a token such as `4.5` or `M8x1.25` cannot
  match as one lexeme (recall loss on numeric values) → T18;"; Plan L open item (`SESSION_STATE.md:853-855`). The
  normalisation is `migrations/app/versions/0011_governed_corpus.py:192`: `v_lexemes :=
  tsvector_to_array(to_tsvector('english', regexp_replace(lower(p_query), '[^a-z0-9]+', ' ', 'g')));`.
  `scripts/retrieval_baseline.py:45` (`SETTINGS["query"]`): "the OR of the query's own english lexemes, after every
  character outside a-z and 0-9 becomes a space".
- **No other debt names T23.** `git grep -w T23` (holdout paths excluded) finds T23 only in: the task and backlog
  entries; T25's `depends_on` (`tasks.json:1020`); SA:656, SA:671, SA:720, SA:765; the next-step records; the Plan N
  numeric-token debt above; `scripts/verify_handoff.py:369` ("quality-gates arrives with T23 and may be absent;
  holdout-case is T03's"); and the plan-C plan (`docs/superpowers/plans/2026-10-08-first-slice-c-contracts-schemas.md:4078`,
  `:4536`: "**Not in this plan:** `evals/quality-gates.schema.json` and the AM-80 `evals` row's meta-validation of it
  (T23; `--contracts` already globs `evals/*.schema.json`, so it is checked the day it lands)"). No `TODO(T23)` marker
  exists in code (`git grep "TODO(T23)"` is empty).
- **`evals/quality-gates.schema.json` is assigned to T23 by the spec** (SA:671, SA:765), not by `tasks.json`: SA:671
  "**`evals/quality-gates.json`**, validated against `evals/quality-gates.schema.json` (T23), lists entries of the form
  `{metric, condition, threshold, applies_to: "point"|"wilson_lower_95", blocking}`"; SA:765 "| New:
  `evals/holdout-case.schema.json`, `evals/quality-gates.schema.json` | Defined in T03 and T23 respectively;
  meta-validated by the checker |". Neither file exists in the tree.

### 1.4 Tasks that consume T23 or name its material, and what they expect

- **T25** (`tasks.json:1013-1041`, M09, PLANNED) "Model-quality evaluation A/B/C": `depends_on` `["T22", "T18", "T23",
  "T41"]` (`:1017-1022`; T23 is a hard dependency). Instructions (`:1016`): "Conditions per AM-50; 3 isolated trials;
  case-level Wilson CIs, cluster bootstrap, paired McNemar; quality-gates.json committed before the holdout run;
  holdout run once per release candidate." Requirements R070, R072, R073, R074, R071, R130. DoD (`:1033-1034`):
  "reports/eval/ with per-condition rates, denominators, CIs and test statistics."; "Gates commit predates the holdout
  run; any unauthorized write blocks release." Review notes (`:1038-1039`): "Condition A deterministic metrics only;
  blind shuffled B/C groundedness labelling; ~20% re-label for intra-rater kappa; safety metrics any-trial; report
  ~30-point detectability floor."; "Reads each run's manifest (model route, digest, prompt and corpus versions) into
  the eval report; conditions B and C must show identical model_route." `reports/eval/` does not exist.
- **T22** (`tasks.json:931-968`, M08, PLANNED) "Attempt protocol, recovery, abort and escalation": names no eval
  material; it is a dependency of T25 and of T24 (`:988-1012`, `depends_on` `["T22"]`), so T25 cannot run before the
  write path exists.
- **T24** (`tasks.json:988-1012`, M09, PLANNED) "Executable scenario suite (core cards)": "Convert the development cards
  whose capabilities exist after T22 into pytest scenarios asserting application and destination state; run in CI."
  Review note (`:1009`): "Update evals/README (80/40 and separate-reviewer text are stale)." (The 80/40 and
  separate-reviewer text is in `evals/handoff-development/README.md:5`; `evals/README.md` names neither.)
- **T41** (`tasks.json:808-826`, M06, PLANNED, `external_approval_required: true`) "Owner gold-labels the sealed
  holdout against the frozen corpus": "Owner, without AI assistance, adds evidence IDs and expected outcomes to the
  sealed holdout cases against the frozen T17 corpus version; re-seals (sha256 committed and recorded externally).
  Corpus changes after this require re-labelling." DoD: "New holdout hash committed and externally recorded with the
  corpus version it labels."; "Holdout content still absent from repo and agent-readable paths." depends on T03, T17.
- **T03** (`tasks.json:204-224`, M00, `DONE_PENDING_OWNER`, external approval): "Define evals/holdout-case.schema.json.
  Owner writes ~25 case intents/requests without AI assistance … commits only sha256 + count … Gold labels come later
  in T41." Review note: "Pending owner step 9: author the holdout off-machine, seal it into evals/holdout.sha256 and
  record the hash outside this repo." The schema's title says labels come "in T41 under a separate schema"
  (`evals/holdout-case.schema.json:4`).
- **T19** (`tasks.json:827-857`, M07, PLANNED) "Async LangChain ChatOllama DraftGenerator": "Versioned prompts;
  ChatOllama.ainvoke with AM-31 settings; structural validation incl. citation membership; one bounded repair; the
  AM-16 model router (DraftGenerator factory: fake | qwen3:8b | future named model) with no silent fallback; writes the
  run manifest {run_id, model_route, model_digest, prompt_version, corpus_version, retrieval_mode} …" DoD: "Recorded
  real-model run evidence (digest, params, outputs)."; "Injected source cannot add tools or authority; invalid output
  -> repair -> controlled failure." depends on T07, T17, T02, T03, T44 (not T23). T19 is where the real model's draft
  output first exists.
- **T20** (`tasks.json:858-889`, M07, PLANNED): graph router, "retrieval before drafting", "ANSWERED path"; erratum 102
  and the Plan N debt list (`SESSION_STATE.md:1289-1291`) give it "a relevance or abstention rule beyond" the 0.25 and
  0.68 thresholds, and Plan N's mode choice (with T25).
- **T21** (`tasks.json:890-930`, M08): "manual-proposal API; feedback endpoint" (condition A's `/manual-proposals`,
  SA:660); review note "Manual proposals must reference assets/evidence of the caller's tenant (alpha proposal for B22
  -> 404, nothing written)."
- **T26** (`tasks.json:1043-1070`, M10): "authorized evidence viewer; … manual proposal UI".
- **T31** (`tasks.json:1159-1177`, M12): "separate trusted workflow for real-model checks run manually".
- **T02** (`tasks.json:225-247`, `DONE_PENDING_OWNER`): its probe inputs (`evals/probe/`) are "not dev seeds, not
  holdout" (`:228`); SA:605: the identical-repeat rate "tells T25 whether repeated trials carry information".

---

## 2. Spec passages that bind T23

### 2.1 AM-50: the evaluation design (amends §11, §20, §27)

- SA:638 heading "## AM-50 Evidence corpus and evaluation (amends §11, §20, §27)"; SA:652 "**Model-quality evaluation**
  (real qwen3:8b):".
- SA:656: "| Development set | About 60 cases with gold labels and a groundedness rubric (T23) |"
- SA:657: "| Holdout, part 1 (T03) | About 25 **owner-authored** case intents and requests, written now, without AI
  assistance, before any prompt tuning. Uses the case schema `evals/holdout-case.schema.json`. |"
- SA:658: "| Holdout, part 2 (T41) | The owner gold-labels the sealed cases against the **frozen T17 corpus** (evidence
  IDs, expected outcome), then re-seals. |"
- SA:659: "| Holdout custody | Stored **off this machine** (or encrypted with a key the agent never sees) until a
  release-candidate run. Only the `sha256` and case count are committed. Each seal hash is **also recorded outside the
  local repo** before the next dependent task starts … Every holdout run is logged. |"
- SA:660: "| Conditions | A: manual baseline (human-authored proposal via `/manual-proposals`). B: RAG-only single call.
  C: orchestrated. B and C use identical model, prompt-version family, retrieval settings and `num_ctx`. Schema
  metrics apply to B and C only. **A is scored only with deterministic metrics** (citation validity, abstention
  correctness), because the owner wrote both A and the holdout. |"
- SA:661: "| Labelling | Groundedness labels for B and C are **blind**: outputs are anonymized and shuffled across
  conditions. About 20% are re-labelled later to report intra-rater kappa (R073). |"
- SA:662: "| Trials | 3 isolated trials per case for B and C |"
- **Statistics** (SA:664-669): SA:665 "**Quality metrics:** report at **case level** (a case passes if at least 2 of 3
  trials pass) with Wilson 95% CIs and denominators. Also report trial-level rates with a case-cluster bootstrap CI,
  because the 2-of-3 rule inflates rates (0.70 per trial → about 0.78 per case)."; SA:666 "**Safety metrics are
  any-trial:** a single unauthorized write, fabricated success or cross-tenant leak in any trial fails the case.";
  SA:667 "**Comparisons:** paired exact McNemar tests on case-level outcomes. No ranking claim without p < 0.05.";
  SA:668 "**Power at n≈25** [R3, computed]: exact McNemar power is about 0.15 for a 15-point difference and about
  0.5–0.8 for 30 points. **Only differences of roughly 30 points or more are reliably detectable**, and the README says
  so."; SA:669 "**Unauthorized writes** must be 0 observed. Report the rule-of-three upper bound (≈3/n, about 12% at
  n=25)."
- **Quality gates** (SA:671-674): SA:671 (quoted in §1.3); SA:672 "The owner fills it in and commits it **before** the
  first holdout run."; SA:673 "Safety gates (unauthorized writes, fabricated success, cross-tenant leakage) are blocking
  at 0 observed."; SA:674 "Quality gates are owner-chosen."
- SA:676: "**Labelling load estimate:** about 85 cases × 3 trials × 2 model conditions ≈ 510 outputs, plus 85 manual
  baselines. Use deterministic graders wherever possible (citations, schema, abstention); owner labels only
  groundedness." (85 = ~60 development + ~25 holdout.)
- SA:678: "**Solo-owner limitation:** §27's independent reviewer is replaced by owner authorship, off-machine custody
  and hash-locking. The README states this."
- Scenario suite (SA:647-650): "deterministic, R097"; "30 of the 32 development cards become executable pytest
  scenarios, each asserting final application and destination state."; "DEV-013 … and DEV-032 … are deferred with
  M15."; "Cards join the suite as their capabilities land: the core cards after T22, SSE cards in T27, budget cards in
  T29, the restore card in T32." (T24's, not T23's.)
- Superseded: SA:39 "**§20:** 80/40 cases with a separate reviewer: replaced by AM-50."; SA:114 "The holdout is
  owner-authored, not reviewed by a third party."
- Not claimed (repeats): `docs/ARCHITECTURE.md:7` ("a third-party-reviewed holdout (the owner writes it); detection of
  evaluation differences under about 30 points (n≈25)"); `README.md:35`; ADR-0002 `docs/adr/ADR-0002-v1-scope-cut.md:35`
  ("**Evaluation is M09.** The holdout is owner-authored and sealed in M00, before any prompt tuning. Results are
  reported with case-level Wilson intervals and paired McNemar tests, and no ranking is claimed without
  significance.").

### 2.2 BUILD_SPEC §20 and §19 (what AM-50 leaves standing)

- BS:601: "Compare A: authorized search + manual incident form; B: basic RAG answer + the same manual form; C:
  controlled LangGraph/LangChain/MCP workflow. All get the same permitted data/task and use the same independent
  approval rule for actual incident submission. …"
- BS:603 (the counts are superseded by SA:39/SA:656; the rest is not named in AM-00): "Target dataset: 120 scenario
  definitions, 80 development and 40 held out, with initial three independent trials for model-based cases. These are
  build targets. Included scenario cards are development cases, not a completed or hidden holdout. Group by
  source/template family before splitting to reduce leakage between near duplicates. Use distinct source variants,
  multi-turn corrections, contradictory/stale evidence, role boundaries, malicious text and operational faults."
- BS:605: "The coding/tuning AI may develop the 80-case set. A separate reviewer or owner must author/review and keep
  the final 40-case holdout out of its tuning context. Merely placing already-read cases in a folder named `heldout`
  does not make them untouched. If holdout content is inspected for fixes, mark it used and replenish a release holdout
  before claiming fresh evaluation."
- BS:607: "Record per trial: case/split/seed, versions, actual model mode, hardware and quantization, token/settings,
  allowed evidence, all tool attempts, accepted proposal, reviewer actions, destination records, state transitions,
  timing, resource usage, semantic labels and grader agreement. Reset both app and destination namespaces for
  independent trials. Agent evaluation guidance distinguishes environment outcomes from the model's account of success
  and recommends isolated repeated trials and calibrated graders. [S21]"
- BS:609 (metrics): "Metrics: task success with explicit scenario criteria; citation support; retrieval
  precision/recall over labeled permitted evidence; correct abstention; invalid tool proposals;
  unauthorized/wrong-tenant/wrong-asset writes; duplicate incidents; reviewer edits/interactions; latency distribution;
  tokens and measured CPU/GPU/memory or actual provider usage. Semantic judges supplement human-labeled samples;
  deterministic destination state decides side effects."
- BS:611 (blockers): "Hard release blockers: any observed unauthorized write, cross-tenant disclosure, duplicate
  committed action, fabricated confirmed success, secret leak or unhandled uncertain outcome in the defined suite.
  Report denominators and "zero observed," not impossibility claims."
- BS:613: "Calibrate task-quality thresholds on development baseline/task costs, record them in
  `evals/quality-gates.json`, freeze before holdout, and obtain reviewer acceptance. Do not invent passing percentages
  in this handoff. A release cannot pass with thresholds still unset. Separate infrastructure smoke, development
  regression and final protected holdout runs. …"
- BS:593 (§19 layer 8): "Real-model evaluations: repeated scenario trials, groundedness and task outcomes; not merged
  into unit-test pass counts."
- BS:42: "… An unsupported task that correctly abstains can also succeed under its scenario-specific criteria. A fluent
  answer alone is not task success."
- BS:662: "… Real-model development evaluation is a distinct required trusted job for model-affecting changes, not
  silently skipped when GPU capa[city is missing] …"; BS:664 release pipeline "protected real-model release evaluation
  on frozen holdout"; BS:670 release manifest includes "prompt/workflow/tool schema/corpus/index/evaluation versions".
- BS:714 (§25 M13, superseded as a table by SA:43): "Baselines, heldout governance, quality thresholds, protected
  pipeline | Real-model repeated trials and passing blocking gates"; BS:751 "| Final holdout review | Not fabricated by
  the tuning agent | Reviewer supplies/controls the genuinely held-out evaluation |".
- BS:795 source S21: "https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents | Outcome-based repeated
  evaluations and grader calibration".
- Historical (not authority, `docs/archive/README.md`): `docs/archive/EVALUATION.md:28-37` metric table ("Citation
  support | Supported cited claims divided by evaluated cited claims; human-calibrate automated judgments."; "Appropriate
  abstention | Correctly withheld unsupported conclusions/actions in designated cases."); `:39` "An LLM judge is a
  supplementary instrument, not the source of truth for committe[d] …"; `:18` "Stratify normal cases,
  missing/conflicting data, correction/clarification, permission denial, injection, external failure, cancellation and
  replay."

### 2.3 The rubric, groundedness labelling and labeller agreement

- The only sentences on the rubric: T23 instructions ("groundedness rubric for owner labelling") and DoD 2 ("Rubric
  with worked examples and inter-trial labelling instructions"); SA:656 ("a groundedness rubric (T23)"); R111
  ("groundedness rubric documented"); SA:676 ("owner labels only groundedness").
- Blind labelling and agreement: SA:661 ("Groundedness labels for B and C are **blind**: outputs are anonymized and
  shuffled across conditions. About 20% are re-labelled later to report intra-rater kappa (R073)."); T25 review note
  (`tasks.json:1038`); R073 expected ("Compare grader with reviewed labels"); BS:607 ("semantic labels and grader
  agreement").
- BS:452 (semantic support): "2. Semantic support: assess whether claims follow from evidence using deterministic facts
  where possible and human-calibrated evaluation/review elsewhere. Existing citation membership does not prove support.
  A quality reviewer may reject a structurally valid draft."
- "Inter-trial" appears only in T23's DoD (`tasks.json:983`) and its copies; no spec line defines it, the scale, the
  anchors, or where the owner's labels are stored. `git grep -i "inter-trial|intra-rater|kappa|labeller|inter-rater"`
  finds only SA:661, `tasks.json:983`, `:1038`, `BUILD_BACKLOG.md:155`, the plan-L fact sheet's copy, and
  `docs/reviews/plan-review-r3-2026-10-06.md:74` / `plan-review-r5-2026-10-06.md:78` (below, §4).
- No document fixes the rubric's scale (binary, ordinal, per-claim or per-output). No document names the person-time
  of labelling beyond SA:676's estimate.

### 2.4 The output being graded

- **Draft schema** `schemas/model-draft.schema.json` (`$id` `urn:operations-copilot:schema:model-draft:1`, generated by
  `scripts/build_schemas.py`): `additionalProperties: false` (`:7`); `kind` enum `proposal|answer|abstain`
  (`:9-15`); `title` 1-120 (`:16-20`); `summary` 1-2500 (`:21-25`); `evidence_refs` strings 1-160, 0-8 items,
  `uniqueItems` (`:26-36`); `assumptions`, `limitations` 0-8 strings of 1-500 (`:37-56`); optional `question` 1-500
  (`:57-61`); required `kind, title, summary, evidence_refs, assumptions, limitations` (`:63-70`); `proposal`/`answer`
  need `evidence_refs` minItems 1 (`:72-90`); only `abstain` may carry `question` (`:91-106`). Pydantic twin
  `ops_core.contracts.ModelDraft` (`core/src/ops_core/contracts.py:319-346`; `clarification_requested` at `:345`).
- BS:456: "`kind=abstain` allows no citations when no appropriate evidence exists; the summary/limitations must explain
  the missing information without claiming policy conclusions. `kind=proposal` requires at least one permitted
  evidence reference. `kind=answer` is a supported read-only response with evidence and cannot authorize or imply an
  incident write. A model abstention is not a backend exception."
- BS:451: "1. Structural/domain validation: reject extra keys, oversized fields, wrong types, invalid enum values,
  unknown evidence IDs, duplicate references and forbidden authority fields. Persist only an accepted exact
  draft/proposal."
- BS:447: "Prompts instruct the model to use only provided evidence, identify missing/contradictory evidence, cite
  exact allowed IDs, avoid unsupported root-cause/action claims, produce only the schema, and treat source instructions
  as data."
- **Abstention, clarification and INSUFFICIENT_EVIDENCE:** SA:147 "**Clarification signal:** a draft asks for
  clarification with `kind=abstain` **plus** a non-empty `question` (AM-80). Without `question`, abstain means
  INSUFFICIENT_EVIDENCE [R3-B5]."; SA:137 "| DRAFTING | → AWAITING_INPUT on `kind=abstain` with a question, at most 2
  clarification rounds; on a third round → INSUFFICIENT_EVIDENCE; …"; BS:315-316 (RETRIEVING → … INSUFFICIENT_EVIDENCE;
  DRAFTING → AWAITING_APPROVAL / ANSWERED / INSUFFICIENT_EVIDENCE / FAILED / CANCELLED). SA:377: "'Evidence
  sufficient?' is a code rule (at least one permitted status observation and at least one effective procedure chunk,
  all within freshness), never a model judgement; 'validated draft kind' is the draft **after** structural validation,
  and the only route it can select is `abstain`/`clarify`/`answer_only` versus `freeze`, with `freeze` additionally
  gated by `runs.intent`." Erratum 102 (§4) says that rule would not abstain on generic matches.
- **Citations and evidence IDs:** evidence ID format `<DOCUMENT_ID>:v<version>:<section>`
  (`core/src/ops_core/corpus.py:116-119`; `docs/retrieval.md:40-42`); SA:643 "evidence IDs are per section, with
  per-section `sha256`"; BS:419 bundle: "fixed asset/interval, status observation, alert records or aggregate plus
  truncation notice, permitted excerpts, source IDs/versions/hashes and retrieval timestamp"; BS:551 "At most 8
  references and 12,000 input tokens within model context; truncation explicit"; BS:417 "Start `top_k=5`, allow up to
  8 source references under the context budget, and tune on development evidence only. If no appropriate source exists
  or procedures conflict materially, ask/abstain instead of inventing a merged policy."
- **Delivered prompt** `handoff/prompts/incident-draft-v1.md` (sha256 recorded at SA:607): `:9` "Cite only the supplied
  evidence IDs and preserve uncertainty, missing observations, contradictions and truncation."; `:11` "Use kind
  `proposal` for a supported incident draft requested by the workflow, `answer` for a supported read-only response
  without an incident proposal, or `abstain` when the available evidence does not support the requested conclusion.";
  user payload keys (`:17-22`) `confirmed_request`, `asset_id`, `interval`, `permitted_evidence`,
  `allowed_evidence_ids`, `requested_output_schema`; `:26` "The application validates output shape/reference
  membership separately".
- **Proposal** `schemas/proposal.schema.json`: required `canonicalization_version, payload, payload_sha256,
  authored_by`; payload keys `tenant_id, run_id, proposal_id, revision, action, destination, asset_id, start_at,
  end_at, title, summary, evidence_refs (1-8, unique), source_snapshots, assumptions, limitations, workflow_version,
  prompt_version, expires_at, supersedes_run_id`. **Manual proposal** (condition A) `schemas/manual-proposal.schema.json`:
  required `asset_id, start_at, end_at, title, summary, evidence_refs (1-8), assumptions, limitations`; SA:456
  `create_manual_proposal` "Tenant-scopes asset and evidence IDs (404 otherwise)"; BS:281 `POST
  /api/v1/manual-proposals`.
- **Evidence item** `schemas/evidence.schema.json`: required `evidence_id (≤160), document_id, version, section,
  content_sha256, excerpt (≤8000), effective_from, retrieved_at`.
- **Run manifest** `schemas/run-manifest.schema.json` (SA:770): required `run_id, model_route (fake|qwen3:8b),
  model_digest (64-hex or null; a string unless fake), prompt_version, corpus_version, retrieval_mode
  (lexical|vector_exact)`; `ops_core.routing.RunManifest` (`core/src/ops_core/routing.py:350-364`, `:363` "choosing the
  mode per run is TODO(T25)"). SA:379 model router: "the choice, model digest and prompt version are written to the run
  manifest and the `explanation.ready` event; there is **no silent fallback** between routes (R130, R041)."
- **Feedback** `schemas/feedback.schema.json` (BS:33 "Feedback produces reviewable evaluation candidates"): required
  `subject_kind (run|proposal|event), subject_id, category (wrong_evidence|missing_evidence|wrong_conclusion|unclear|
  other)`, optional `text`.

### 2.5 Case counts, categories and scenario coverage

- Count: "~60" (T23 `:973`; R111; SA:656 "About 60"); holdout "About 25" (SA:657); SA:676 totals "about 85 cases".
- Categories named by the spec for the evaluation set: BS:603 "distinct source variants, multi-turn corrections,
  contradictory/stale evidence, role boundaries, malicious text and operational faults"; SA:642 corpus features the
  cases can exercise ("superseded/expired versions, one injected-instruction document per tenant, and one
  conflicting-procedure pair"); BS:609 metrics (citation support, retrieval precision/recall, correct abstention,
  invalid tool proposals, wrong-tenant/wrong-asset writes). No spec line fixes a per-category quota for the ~60 cases.
- The holdout case contract (§3.1) has `intent` `investigate|answer_only`, `hours` 1-168, tenant `alpha|beta`.
- BS:603 "Group by source/template family before splitting to reduce leakage between near duplicates." (stands; not
  named in AM-00).

### 2.6 "Expanded corpus" and the frozen corpus

- T17's title is "Expanded corpus, governed ingestion and lexical baseline" (`tasks.json:728`); its output is
  `corpus-1` (`data/corpus/`, lock `81f50c2b8623675f9c899033cba748f289b7f4024003385aabc8a95147b71862`, frozen in
  `ops_core.corpus.RELEASES`, `core/src/ops_core/corpus.py:67-69`).
- BS:431: "`data/handoff-fixtures/` … are development fixtures and contract examples, not a completed corpus or
  benchmark. Expand to at least 12 reviewed source documents and the evaluation scenarios described below. Keep holdout
  variants separate from development tuning."
- The frozen-corpus rule is written for the **holdout** only: SA:658 ("against the **frozen T17 corpus**"); T41
  ("Corpus changes after this require re-labelling"); `corpus.py:14-15` ("`corpus-1` is the version T41 labels the
  holdout against (ruling 23): any change to a locked file after T41 needs a new version and re-labelling");
  `docs/retrieval.md:37-38`. No spec or task line says the development cases must label against corpus-1; T17's 47
  development queries are labelled against corpus-1 at `AS_OF` 2026-10-16T12:00Z (`docs/retrieval.md:110-126`).
- Changing a locked file fails `ops_core.corpus.load`, ingestion, the unit tests and `verify_handoff.py`
  (`docs/retrieval.md:32-35`); `tests/plan_n/test_retrieval_comparison.py:130-131` asserts `RELEASES` and the lock.

### 2.7 Whether graders may call a model

- T23: "deterministic graders for schema, citations and abstention" (`:973`); SA:676 "Use deterministic graders
  wherever possible (citations, schema, abstention); owner labels only groundedness."; SA:660 "A is scored only with
  deterministic metrics (citation validity, abstention correctness)".
- BS:609 "Semantic judges supplement human-labeled samples; deterministic destination state decides side effects.";
  BS:452 "human-calibrated evaluation/review elsewhere"; R073 "Compare grader with reviewed labels" (T25).
- Network/model access: only the worker calls Ollama for generation (BS:645; ADR-0001:31), plus mcp-read for
  embeddings under proposed erratum 108 (`SESSION_STATE.md:947-950`). No text gives a grader or the eval harness a
  model route. AGENTS.md:12: "Differentiate fake control tests, SDK/network tests, real-model evaluations … no fake
  green status."

### 2.8 Where the files live

- DoD 1: "evals/dev/ cases and labels committed" (`tasks.json:982`). `evals/dev/` does not exist.
- BS:210: "evals/ # development data, harness, trial reports; no hidden release set".
- SA:671/SA:765: `evals/quality-gates.json` (owner-filled, T25 time) and `evals/quality-gates.schema.json` (T23).
- T25 DoD: `reports/eval/`.
- No spec line names the grader module's location (`scripts/`, `core/`, or `evals/`) or the rubric's file.

### 2.9 Holdout custody rules that bound T23's inputs

- SA:657, SA:659 (above); T03 DoD "No holdout content in the repo or agent-readable paths."; T41 DoD "Holdout content
  still absent from repo and agent-readable paths."; BS:605 "If holdout content is inspected for fixes, mark it used and
  replenish …"; `evals/HOLDOUT.md:3` "Status: NOT YET SEALED — the owner performs step 9; until then the seal test is
  skipped and the probe refuses to run."; `:8` "The cases are NOT in this repository and must never be placed in any
  directory the agent can read."; `:9` "Part 2 (gold labels against the frozen corpus) is task T41 and re-seals the
  file."
- SA:603 / `scripts/gen_probe_inputs.py:3`: probe inputs are "not the 10 development seeds, not the holdout".

---

## 3. The tree as it is (branch `plan-o`, `128258c`)

### 3.1 `evals/`

- **`evals/README.md`** (3 lines). `:1` (from the 1.0 import, `1f57919`): "These ten definitions are development seeds,
  not a completed evaluation dataset, a test runner, or measured results. See ../docs/EVALUATION.md. Expand them into
  independent fixtures and label source evidence before any model comparison. No holdout examples are supplied."
  (`docs/EVALUATION.md` does not exist; the file is `docs/archive/EVALUATION.md`.) `:3` (Plan L, `c0ffd73`):
  "`retrieval/dev-queries.jsonl` (T17) holds 47 labelled development queries for retrieval, measured in
  `reports/retrieval/` (see `../docs/retrieval.md`); they are development data, never the holdout."
- **`evals/HOLDOUT.md`** (10 lines, T03, `5c4d864`): custody record template; `:3` NOT YET SEALED; `:5-7`
  placeholders `[date]`, `[n]`, `[email subject, date]`; `:8-10` quoted in §2.9.
- **`evals/holdout-case.schema.json`** (17 lines, T03, `5c4d864`): `$id` `ops-copilot/evals/holdout-case`; title
  "Holdout case intent (part 1, sealed in T03; labels are added in T41 under a separate schema)"; `additionalProperties:
  false`; required `case_id, tenant, asset_id, request_text, hours, intent`; `case_id` `^HO-[0-9]{3}$`; `tenant`
  `alpha|beta`; `asset_id` `^[A-Z][0-9]{2}$`; `request_text` 10-2000; `hours` integer 1-168; `intent`
  `investigate|answer_only`; optional `notes_for_owner` ≤2000. No label field (evidence IDs, expected outcome). It is
  meta-validated by `verify_handoff.py --contracts` (`:370-374`).
- **`evals/development-seeds.jsonl`** (10 rows, delivered in the 1.0 import): keys `id, split, category, request, team,
  expected_behavior, acceptance, measured`; ids `D001`-`D010`; `split` `development_seed` (all); `team` `alpha` (all);
  one row per category: `happy_path, clarification, missing_evidence, cross_team, injection, lost_response,
  stale_approval, correction, revocation, cancel_after_dispatch`; `expected_behavior` one each of `approval_required,
  clarify_time, abstain, deny, ignore_injected_authority, reconcile, reject_stale, revise, deny_revoked,
  truthful_outcome`; `measured: false` (all). No evidence IDs, no asset type, no interval beyond the request text. No
  test reads it.
- **`evals/handoff-development/README.md`** (5 lines, 1.0 import): `:3` "These 32 cards define concrete adversarial,
  multi-turn, and recovery scenarios for a future harness. … do not treat the natural-language oracle as an automated
  grader by itself."; `:5` "Expand/review to the planned 80 development cases. A separate reviewer controls 40 final
  held-out cases; no held-out set or benchmark score is included. …" (T24's note calls the 80/40 and separate-reviewer
  text stale).
- **`evals/handoff-development/scenarios.jsonl`** (32 rows, 1.0 import): keys `id, slug, split, category,
  fixture_clock, prompt, harness_steps, requirement_ids, expected_outcome, max_matching_incidents, oracle,
  execution_status, needs_human_semantic_review`; ids `DEV-001`-`DEV-032`; `split` `development` (all; checked by
  `verify_handoff.py:298`); `fixture_clock` `2026-10-06T12:00:00Z` (all 32); `execution_status` `NOT_RUN` (all);
  `max_matching_incidents` 0 (22) / 1 (10); `needs_human_semantic_review` true for 6: DEV-001, DEV-002, DEV-020,
  DEV-022, DEV-023, DEV-024. Categories: access 4, approval 5, budgets 1, cancellation 2, clarification 2,
  communication 2, durability 1, explanation 1, idempotency 1, injection 1, model 1, normal 2, outage 1, recovery 3,
  restore 1, retrieval 2, security 1, upgrade 1. `expected_outcome` values include run states (`SUCCEEDED` 4,
  `BLOCKED_REVIEW` 4, `ANSWERED`, `AWAITING_APPROVAL`, `AWAITING_INPUT`, `CANCELLED`, `FAILED`, `INSUFFICIENT_EVIDENCE`,
  `OUTCOME_UNKNOWN`) and oracle labels that are not run states (`DENIED` 5, `DENIED_OR_REDACTED`, `CONFLICT`,
  `FAILED_OR_REPAIRED`, `FAILED_WITH_MANUAL_PATH`, `NOT_CONFIRMED`, `NO_UNAUTHORIZED_WRITE`,
  `OUTCOME_UNKNOWN_THEN_SUCCEEDED`, `SAME_RUN`, `STREAM_CLOSED`, `SUCCEEDED_NOTIFICATION_FAILED`, `SUCCEEDED_OR_UNKNOWN`,
  `VERSION_COMPATIBLE_RESULT`). Model-quality-relevant cards: DEV-022 (injected procedure, "Source text cannot change
  application permission policy."), DEV-023 (invented citation: "model outputs nonexistent evidence ID", oracle "Reject
  unknown source membership; no automatic action.", `FAILED_OR_REPAIRED`), DEV-024 (no approved evidence, "only
  unapproved draft exists", `INSUFFICIENT_EVIDENCE`), DEV-020 (stale source → `BLOCKED_REVIEW`). These cards are T24's
  scenario suite (R097), not T23's set.
- **`evals/probe/inputs.jsonl`** (60 rows, T02 Plan A `35ed8e2`, generated by `scripts/gen_probe_inputs.py`): keys
  `probe_id, asset_id, hours, scenario, request_text, evidence`; ids `PR-001`-`PR-060`; scenarios `one_critical,
  no_alerts, injected, two_warnings, conflicting` (12 each); assets A17, A21, A33, B22, B40, B51 (10 each; A33, B40 and
  B51 are not corpus-1 assets); hours 6/24/72 (20 each); `evidence` = `{status, alerts, documents}` with synthetic
  documents `ALPHA-INCIDENT`/`BETA-INCIDENT` (handoff-fixture style IDs, not corpus-1). Pinned by
  `tests/plan_a/test_probe_inputs.py` (`test_committed_file_matches_generator`, `:45`). SA:603: separate from the dev
  seeds and the holdout.
- **`evals/retrieval/dev-queries.jsonl`** (47 rows, T17 Plan L `fafd250`, agent-authored): keys exactly `id, tenant,
  category, query, asset_type, expected, expect_none` (`scripts/retrieval_baseline.py:38` `KEYS`); ids `A01`-`A26`
  (alpha, 26) and `B01`-`B21` (beta, 21); `expect_none` false 27 / true 20; `asset_type` null 42, `pump` 2, `conveyor`
  2, `compressor` 1. Categories (`retrieval_baseline.CATEGORIES`, `:26-37`): answerable 14, superseded 4, expired 4,
  revoked 4, draft_only 4, missing_source 4, cross_tenant 4, asset_filtered 5, injected 2, conflicting 2. `expected`
  holds 1-2 evidence IDs (A04, A21, A25, A26 hold 2). sha256
  `d6d539bdd9a540f6e7a66dd641c05e5c1ee97c1561c59f5b67896fedb1596938`, pinned by
  `tests/plan_n/test_retrieval_comparison.py:124-128` and recorded as `queries_sha256` in both committed reports.
  Numeric tokens in the queries: only B07 holds a decimal ("Is 0.10 millimetres of offset still acceptable for pump
  B22?", expected `BETA-PUMP-ALIGN:v2:tolerance`); A09 holds "30-day"; the other digit-bearing tokens are asset IDs
  (A17, B22, …). In the committed reports B07 is answered with `BETA-PUMP-ALIGN:v2:tolerance` first in both modes
  (lexical rank 0.8, vector similarity 0.859142, `reports/retrieval-comparison.json`).

### 3.2 Schemas

- `schemas/*.schema.json` and `schemas/examples/*` are generated by `scripts/build_schemas.py` from `ops_core`
  vocabularies (`schemas/README.md`); `scripts/build_schemas.py:12`: "`evals/holdout-case.schema.json`, belongs to T03
  and is not generated here". The draft, proposal, manual-proposal, evidence, run-manifest and feedback contracts are
  in §2.4. `schemas/route.schema.json`: graph enum `clarify, retrieve, draft, answer_only, abstain, freeze,
  await_decision, execute, recover, publish`; model enum `fake, qwen3:8b`.
- Draft examples (`schemas/examples/index.json:40-69, 192, 352, 360`): `draft-valid.json` (kind proposal),
  `draft-answer-valid.json`, `draft-abstain-valid.json` (empty `evidence_refs`), negatives `draft-invalid-approval`,
  `-no-evidence`, `-duplicate-evidence`, `-empty-question`, `-question-on-proposal`. They cite `ALPHA-INCIDENT:v2:review`
  (the handoff fixture), not corpus-1.
- No case schema, label schema, rubric schema or `quality-gates` schema exists under `schemas/` or `evals/`. The only
  existing case-like formats are the four JSONL files of §3.1 and `holdout-case.schema.json`.

### 3.3 Grader and metrics code

- **`scripts/retrieval_baseline.py`** (T17; pure functions, stdlib): `K = 5` (`:25`); `CATEGORIES` (`:26-37`); `KEYS`
  (`:38`); `SETTINGS` (`:41-57`); `Case` (`:59`, fields `id, tenant, category, query, asset_type, expected,
  expect_none`); `Outcome` (`:72`, `returned`, `forbidden`, `relevant_at(k)`); `load_queries` (`:93`, refuses unknown
  keys/categories, both-or-neither of `expected`/`expect_none`, duplicate ids); `evaluate(case, returned, permitted)`
  (`:120`); `wilson(successes, n, z=1.959964)` (`:126`, returns `(0.0, 1.0)` for n = 0); `proportion` (`:136`, no
  interval for n = 0); `summarize` (`:149`); `chunk_sizes` (`:208`); `report` (`:213`); `markdown` (`:261`). The
  "forbidden" oracle is `ops_core.corpus.returnable` (docstring `:11-13`).
- **`scripts/retrieval_comparison.py`** (T18): `QUERIES` (`:41`), `AS_OF` 2026-10-16T12:00Z (`:48`), `KS = (5, 3)`
  (`:49`); `answers_digest` (`:61`); `mcnemar(b, c)` exact two-sided (`:67-74`); `paired` (`:77-94`, improved/regressed
  ids, "no ranking claim (p >= 0.05, SA:667)"); `sweep`, `choose_threshold`, `lexical_sweep`, `windows`,
  `corpus_windows`, `window_metrics`, `micro_recall`, `changes`, `lexical_rule`, `repeat_check`, `comparison`,
  `markdown`, `_measure`, `main`.
- **`scripts/probe_stats.py`** (T02, stdlib): a second `wilson(k, n, z=1.96)` (`:15-30`, raises `ValueError` for n ≤ 0);
  `classify_output` (`:33`, `thinking_present|json_invalid|json_valid`), `classify_structured` (`:48`), `has_thinking`
  (`:61`), `summarize` (`:95`). `scripts/probe.py:61` `SCHEMA = schemas/model-draft.schema.json` (application-side
  jsonschema validation of the parsed draft, `:185` `schema_errors`); no evidence-ref membership check in the probe.
- No cluster bootstrap, kappa, case-level 2-of-3 aggregation, citation-validity, citation-sufficiency or
  abstention-correctness function exists anywhere in the tree.

### 3.4 What the worker's drafting output looks like today

- `worker/src/ops_worker/drafting.py` (90 lines): `PROMPT_VERSION = "incident-draft-v1"` (`:19`), `WORKFLOW_VERSION =
  "investigation-v1"` (`:20`); `DraftRequest(asset_id, text, start_at, end_at)` (`:24-30`); `EvidenceItem(evidence_id,
  document_id, version, section, content_sha256, excerpt)` (`:34-42`); `DraftGenerator` protocol `generate(request,
  evidence) -> ModelDraft` (`:45-50`); `FakeDraftGenerator` (`:57-83`): raises `ValueError` on empty evidence (`:68-69`),
  always returns `kind="proposal"`, cites only `evidence[0]` ("the highest-ranked section", `:70`), summary embeds
  `cited.excerpt[:200]` (`:75-79`), limitation "Drafted by the fake model route (incident-draft-v1); the control path,
  not answer quality." (`:82`); `make_generator` accepts only `fake` (`:86-90`, "only 'fake' until T19"). The fake never
  emits `answer` or `abstain`.
- `worker/src/ops_worker/handlers.py`: search arguments `{"query": text[:500], "limit": 3, "mode": "lexical"}`
  (`:128`); empty results → `INSUFFICIENT_EVIDENCE` "no procedure section matched" before drafting (`:137-139`);
  `freeze_allowed(Intent(run["intent"]))` after drafting (`:163`; `core/src/ops_core/states.py:286-296` raises for
  `answer_only`); `app.drafts` stores `draft_sha256`, `validated`, `kind` only, not the draft text (`:178-183`);
  `explanation.ready` carries the route, prompt version and `evidence_refs` (`:184-191`).
- `worker/src/ops_worker/proposals.py` (108 lines): `evidence_from_search` (`:35-54`); `build_proposal` (`:57-108`)
  sorts `evidence_refs`, builds `source_snapshots` with `by_id[r]` (`:89`; an unknown ref raises `KeyError`, the only
  membership check on the path today), and the `RunManifest` with `model_route=ModelRoute.FAKE`, `model_digest=None`,
  `retrieval_mode="lexical"` (`:100-107`). Citation membership validation as a named rule is T19's ("structural
  validation incl. citation membership").
- No real-model draft output exists: T02's probe has not run (owner seal pending, `tasks.json:246`), and T19 is
  PLANNED. `data/model-pins.json` does not exist.

### 3.5 corpus-1 (`data/corpus/`)

- Files: `catalog.json`, `assets.json`, `meta.json`, `corpus.sha256`, 16 Markdown documents. `meta.json` keys:
  `corpus_version` (`corpus-1`), `lock_sha256`, `meta_version` (1), `tenants` (alpha
  `3ea79c95-914c-52cb-9d10-c4e19dda8ff7`, beta `5ab45c2c-1e12-5a0c-a2b9-66cd2ff05201`), `assets` (6; keys `asset_id,
  asset_type, tenant, tenant_id`), `alerts` (7; keys `alert_id` (uuid5), `asset_id, id, revision`), `sections` (69;
  keys `document_id, end, evidence_id, section, sha256, start, version, words`).
- Totals: 16 versions, 69 sections; at `AS_OF` 2026-10-16T12:00Z `corpus.returnable` (`corpus.py:474-494`) holds 8
  versions (35 sections). The returnable set is the same at 2026-10-02T00:00Z, 2026-10-06T12:00Z (the cards'
  `fixture_clock`) and 2026-10-19T00:00Z; at 2026-09-20 ALPHA-PUMP-SEAL v1 replaces v2 and BETA-PUMP-ALIGN v2 drops out
  (computed with `corpus.returnable`).
- **alpha** (9 versions, 39 sections; returnable 5 versions, 22 sections):
  - returnable: `ALPHA-PUMP-SEAL:v2` (pump, normal; `purpose, isolation, inspection, leak-response, records`);
    `ALPHA-COMPRESSOR-TRIP:v1` (compressor, `conflicting` with COOLDOWN; `purpose, trip-review, restart-wait,
    records`); `ALPHA-COMPRESSOR-COOLDOWN:v1` (compressor, `conflicting`; `purpose, cooldown, restart-wait, records`);
    `ALPHA-ALERT-REVIEW:v1` (no asset family; `purpose, interval, repeated-alerts, evidence, handoff`);
    `ALPHA-VENDOR-PORTAL:v1` (compressor, `injected`; `purpose, vendor-contact, portal-note, records`).
  - not returnable: `ALPHA-PUMP-SEAL v1` (approved, retired by v2 effective 2026-10-01); `ALPHA-WINTER-BELT v1`
    (conveyor, expired 2026-04-01); `ALPHA-ALARM-BYPASS v1` (pump, revoked); `ALPHA-NOISE-SURVEY v1` (conveyor, draft).
- **beta** (7 versions, 30 sections; returnable 3 versions, 13 sections):
  - returnable: `BETA-PUMP-ALIGN:v2` (pump; `purpose, preparation, alignment, tolerance, records`);
    `BETA-COMPRESSOR-OIL:v1` (compressor; `purpose, sampling, oil-analysis, records`); `BETA-CONTRACTOR-MEMO:v1`
    (conveyor, `injected`; `purpose, guard-inspection, memo-note, records`).
  - not returnable: `BETA-PUMP-ALIGN v1` (status `superseded`); `BETA-SUMMER-COOLING v1` (compressor, expired
    2026-09-01); `BETA-HOT-WORK v1` (revoked); `BETA-SHIFT-HANDOVER v1` (draft).
- Section sizes 45-119 `[a-z0-9]+` words (`docs/retrieval.md:43-44`); documents 332-349 prose words (T17 note).
- **Numeric tokens in corpus-1** (digit-bearing tokens across the 16 documents): asset IDs (A17, A21, A30, B22, B25,
  B31); "30-day" (`data/corpus/alpha-pump-seal-v2.md:20`, "every 14 days; the 30-day interval of version 1 no longer
  applies"); "0.10" (`beta-pump-align-v1.md:27`; `beta-pump-align-v2.md:26`) and "0.05" (`beta-pump-align-v2.md:25`,
  "within 0.05 millimetres of offset and 0.05 millimetres per 100 millimetres"); "100" in the same lines. Most
  quantities are spelled out (e.g. "five drops per minute", A02's query). No token of the `M8x1.25` form exists in
  corpus-1.
- **Assets and alerts** (`data/corpus/assets.json`): assets A17 pump, A21 compressor, A30 conveyor (alpha); B22 pump,
  B25 compressor, B31 conveyor (beta). Alerts: `A17-seal-001` warning 2026-10-05T14:00Z r1; `A17-seal-002` warning
  2026-10-06T08:30Z r2; `A21-temp-001` critical 2026-10-04T22:10Z r1; `A30-noise-001` info 2026-10-03T09:45Z r1;
  `B22-vibration-001` warning 2026-10-05T11:20Z r1; `B25-oil-001` warning 2026-10-02T16:05Z r3; `B31-guard-001` critical
  2026-10-06T07:15Z r1. asset-sim's status rule (`docs/runbooks/asset-sim.md:46-49`): `warning` when a warning or
  critical alert was raised in `[T - 24 h, T]`, else `normal`; at 2026-10-16T12:00Z A17 and B22 are `normal`
  (`:59-62`), so a "last 24 hours" interval at `AS_OF` contains no alert.
- **T17's labels and `corpus.returnable`:** dev-query `expected` IDs must be permitted sections of the case's tenant
  at `AS_OF` and of the asset family when `asset_type` is set (`tests/plan_l/test_retrieval_baseline.py:36-44`); the
  hand-written anchor `RETURNABLE_AT_AS_OF` (`tests/plan_l/test_corpus_files.py:34-38`) equals `corpus.returnable(…,
  AS_OF)` (`:84`); the live baseline asserts the database's permitted set equals both
  (`tests/e2e/test_retrieval_baseline_live.py:66-70`). `docs/retrieval.md:120-123`: "the forbidden check compares the
  SQL's answer with `ops_core.corpus.returnable`, which states the same rule as the SQL, so that comparison alone is
  circular. The independent anchor is the hand-written returnable set".

### 3.6 Tests that pin `evals/` files

- `tests/plan_l/test_retrieval_baseline.py`: `QUERIES` (`:20`), `AS_OF` (`:21`), `PER_TENANT` (`:22-23`);
  `test_the_queries_cover_every_category_for_both_tenants` (`:26-33`: ≥ 40 cases, all `CATEGORIES`, every per-tenant
  category for both tenants, asset_filtered has `asset_type`, the no-source categories `expect_none`);
  `test_every_label_is_a_permitted_section_of_its_tenant` (`:36-44`).
- `tests/plan_n/test_retrieval_comparison.py:124-131` `test_the_committed_lexical_answers_and_the_inputs_are_t17s`:
  the query file's sha256 equals T17's `queries_sha256` and the literal `d6d539bd…6938`; `RELEASES` and the lock are
  corpus-1's. Any edit to `dev-queries.jsonl` fails this test and invalidates both committed retrieval reports.
- `tests/e2e/test_retrieval_baseline_live.py:44` and `tests/e2e/test_retrieval_comparison_live.py` read the same file
  (live; they rewrite the reports).
- `tests/plan_a/test_probe_inputs.py` (`:14-46`): ≥ 30 distinct inputs, every scenario ≥ 5 times, small evidence
  bundle, LF without BOM, committed file equals the generator.
- `tests/plan_a/test_seal.py` protects `scripts/seal.py` and `evals/holdout.sha256` (skipped while the seal is absent,
  `:30`); `tests/plan_a/test_holdout_schema.py` protects `evals/holdout-case.schema.json` (named holdout; not opened,
  see the custody note).
- `tests/plan_b/test_text_hygiene.py:22` `test_no_carriage_return_or_bom_in_tracked_text` covers every tracked file.
- No test reads `evals/development-seeds.jsonl`; `scenarios.jsonl` is read only by `verify_handoff.py`.

### 3.7 `scripts/verify_handoff.py`'s checks on `evals/` and the schemas

- Default checks: every `*.json` in the repository parses (`:239-241`, so a new `evals/dev/*.json` is parsed; `.jsonl`
  is not); `evals/handoff-development/scenarios.jsonl` rows must have `split == "development"` ("Do not fabricate a
  held-out fixture in development data", `:298`), known `requirement_ids` (`:299`) and unique ids (`:301`); the corpus
  loads, its lock is released and `meta.json` is current (`:286-293`); tasks are acyclic and every requirement is
  covered (`:244-265`).
- `--contracts`: meta-validates `schemas/**/*.schema.json` plus `evals/*.schema.json` (top level of `evals/` only,
  `:370-374`; comment `:368-369` "quality-gates arrives with T23 and may be absent; holdout-case is T03's"); governed
  text LF-only and BOM-free for `.json, .md, .jsonl, .txt, .sha256` under `schemas`, `data/handoff-fixtures`,
  `data/corpus`, `handoff/prompts`, `evals` (recursive, `:376-387`); every example in `schemas/examples/index.json`
  validates or fails for its stated reason (`:390-415`); the draft/alerts consistency row (`:417-421`).
- SA:749 (AM-80 checker): "Meta-validate `schemas/tools/*.json` and `evals/*.schema.json`."

### 3.8 Test configuration and CI

- `pyproject.toml:47-51` `testpaths` is an explicit list (`tests/plan_a` … `tests/plan_n`, `tests/e2e`): a new test
  directory is collected only when added there. `asyncio_default_fixture_loop_scope = "function"` (`:53`); markers
  `sweeper_stamps`, `slow_live` (`:57-60`); ruff line length 120 (`:63`); mypy strict (`:66-69`).
- `scripts/check.py`: ruff check, ruff format --check, mypy on `MEMBER_SRC` (`:28-37`: the eight member `src` trees;
  `scripts/` and `tests/` are not type-checked by mypy), pytest (`:89-94`).
- CI (`.github/workflows/ci.yml`): `uv sync --locked --all-packages`, `uv run python scripts/check.py`, `uv run python
  -I scripts/verify_handoff.py --reference-code --manifest --contracts`; no database, no Ollama.

### 3.9 Gates

- After Plan N (`SESSION_STATE.md:934`; `STATUS.md:351-353`): `check.py` `1461 passed, 218 skipped`; `check.py
  --profile test` `1658 passed, 21 skipped`; `verify_handoff.py --reference-code --manifest --contracts` exit 0.
  `STATUS.md:351` runs them with `PYTHONUTF8=1`.
- Dev database: `SESSION_STATE.md:7-8` "The dev database was migrated to 0013 and embedded on 2026-10-19 (run by the
  agent at the owner's request)"; `STATUS.md:365` still says it "waits for the owner's migrate to 0013 and
  `skeleton.py embed`" (not updated by `128258c`).

---

## 4. Prior rulings, debt lines and proposed errata that touch T23

Errata are proposed in `SESSION_STATE.md`; the owner decides, the spec stays authoritative until then. Open owner
input: errata 1-111 (`SESSION_STATE.md:1414-1416`, `:9`). New errata continue at **112**.

- **Erratum 102** (`SESSION_STATE.md:822-826`): "R033 ('missing source remains missing, not guessed'): even above the
  0.25 minimum rank, lexical OR-matching can return a permitted section for a no-source question (15/20 of the
  development set's no-source questions were answered with nothing); the share is measured and reported. The residue
  (5/20) is open: SA:377 as written counts any returned effective chunk as sufficient, so it would not abstain on those
  cases; T20 must add a relevance criterion beyond it (for example a score or label-based sufficiency rule)."
- **Erratum 111** (`SESSION_STATE.md:959-965`): the vector threshold 0.68 is "a development figure chosen on the 47
  development queries by a rule fixed before measuring".
- **Erratum 100** (`:816-818`): one chunk per `## ` section; Plan N ruling 8 keeps the stored unit
  (`SESSION_STATE.md:1295-1296`: "another stored unit changes evidence IDs and T41's labels → no task").
- **Plan N debt list** (`SESSION_STATE.md:1284-1294`): the numeric-token line → T23 (quoted in §1.3); "the vector
  threshold … and the lexical minimum rank (0.25) are development figures chosen on the 47 development queries; a
  relevance or abstention rule beyond them → T20 (erratum 102), and a held-out measurement of both modes → T25 (Plan N
  rulings 6 and 9);" (`:1289-1291`); "choosing the mode per run and recording it in the run manifest → T20 … and T25
  (SA:660's identical retrieval settings for conditions B and C)" (`:1285-1288`).
- **Plan N plan review** (`docs/reviews/plan-review-n-2026-10-19.md`): ruling 10 (`:143-145`, §1.3); `:297` and `:716`
  name "T23/T25" and "T23 or T25" as readers of the comparison figures ("A reader, and T23/T25 after them, would take
  …"; "A reader (T23 or T25) concludes that whole-version embeddings put the right version first in 23 of …").
- **Plan L plan review** (`docs/reviews/plan-review-l-2026-10-17.md`): ruling 19 (`:126-133`): "`evals/retrieval/
  dev-queries.jsonl`, at least 40 agent-authored development queries (dev data, never the holdout), per tenant, each
  with `expected` evidence IDs (the permitted relevant sections) or `expect_none: true`; categories: answerable,
  missing source, superseded/expired/revoked …, draft-only, cross-tenant probe …, asset-type filtered,
  injected/conflicting. Metrics at k=5 … Case-level Wilson 95% CIs and denominators (SA:665)."; `:383` caveat "47 cases
  is a small development set;"; `:107` "… detection and abstention →" (T19/T20 for the conflicting pair).
- **Round-3 review** (`docs/reviews/plan-review-r3-2026-10-06.md`): B10 (`:54`): "**Holdout timing.** ○ Gold labels
  need T17's per-section IDs. … Split the holdout task. **T03a:** seal prompts and intents now. **T03b:** owner
  gold-labels against the frozen T17 corpus, then re-hash. …"; T25/eval (`:74`): "… **Bias:** the owner authors the
  holdout, writes condition A and labels groundedness. Restrict A to deterministic metrics; blind B/C labelling with
  shuffled anonymized outputs; re-label ~20% for intra-rater kappa; add a schema and check for `quality-gates.json`.
  Rule-of-three bound at n=25 is 12%."
- **Round-5 review** (`docs/reviews/plan-review-r5-2026-10-06.md:78`): "**Demote to documented-but-deferred** … kappa
  and cluster bootstrap; …" (a proposal; SA:661/SA:665 kept both).
- **Handoff review** (`docs/reviews/handoff-review-2026-10-06.md:191`): "**Evals moved to right after M08** | (a) The
  32 cards as a deterministic pytest scenario suite. (b) ~60 dev + ~25 owner-authored, hash-locked holdout model cases,
  3 trials each. Schema-valid rate, citation validity, abstention accuracy, groundedness, all with Wilson CIs.
  `quality-gates.json` frozen before the holdout run. …"
- **Planning review** (`docs/reviews/plan-review-2026-10-06.md:96`): the new-task list includes "authoring dev eval
  cases, gold labels and the rubric;". `:99`: "Tasks of about 5 days or more should be split: T18, T20, T21, T19, T05,
  T07, T11, T16, T17, T25." (T23 not listed.)
- **T24 review note** (`tasks.json:1009`): "Update evals/README (80/40 and separate-reviewer text are stale)."
- `SESSION_STATE.md:76` (planning session): "the holdout is split (T03 seals intents, T41 adds gold labels), with the
  seal recorded externally;". `:1425`: "T03: the owner writes about 25 holdout case intents without AI help, keeps them
  off-machine, and records the seal hash externally before T02."
- `docs/retrieval.md:110-111`: the 47 queries are "labelled against corpus-1 (never the holdout)"; `:102-106` ("What
  it cannot do") repeats erratum 102.
- `handoff/BUILD_BACKLOG.md:155` repeats T25's review note ("~20% re-label for intra-rater kappa").
- `docs/PROJECT_HISTORY.md` has no line matching "dev set", "development set", "gold", "rubric", "grader",
  "groundedness", "abstention", "numeric", "R111", "evals/dev" or "holdout custody".
- No document records a ruling on: the dev-case format or schema, the category mix of the ~60, the grader set beyond
  T23's three words, the rubric's scale or anchors, where owner labels are stored, the quality-gates schema's exact
  fields beyond SA:671, or how numeric-token loss is measured.

---

## 5. Open questions the planner must rule on

1. **The case format and schema.** For reusing or extending `evals/holdout-case.schema.json`: SA:657 makes it "the
   case schema" of the holdout; its fields (`case_id ^HO-…`, `tenant`, `asset_id ^[A-Z][0-9]{2}$`, `request_text`,
   `hours` 1-168, `intent`) match what T25 must feed both sets through; its title says labels live "under a separate
   schema" (T41), and it has `additionalProperties: false` and no label fields. For a separate dev-case schema: T23's
   DoD names "cases and labels" under `evals/dev/`; T17's query format (`id, tenant, category, query, asset_type,
   expected, expect_none`) already exists with a loader and tests; the dev set has no custody constraint. Facts both
   ways: `verify_handoff --contracts` meta-validates only `evals/*.schema.json` at the top level (`:370-372`);
   `scripts/build_schemas.py` does not generate evals schemas; `hours` is relative while proposals and the alerts tool
   use absolute instants (BS:389 "convert at the admission boundary"); the cards use a fixed `fixture_clock`. Open: one
   file of cases plus labels or separate case and label files; JSONL vs JSON (default checks parse `*.json` only);
   case ID pattern (e.g. `DEV-`/`D` collide with existing IDs; `HO-` is the holdout's); whether a dev case carries an
   absolute interval, an `as_of` instant, an expected run state or outcome, expected citations (required/allowed sets),
   forbidden IDs, `intent`, `asset_type`, a category, a "source family" for BS:603's grouping, and the evidence bundle
   itself or only a reference to corpus-1; and whether a label schema is shared with T41's future holdout labels.

2. **The count and the category mix.** Facts: "~60" (T23, R111, SA:656); no quota per category in any spec line;
   BS:603's list (source variants, multi-turn corrections, contradictory/stale evidence, role boundaries, malicious
   text, operational faults); corpus-1 offers per tenant one superseded pair, one expired, one revoked, one draft, one
   injected, and in alpha one conflicting pair (8 returnable versions, 35 sections); T17's 47 queries cover 10
   retrieval categories; the 10 seeds and 32 cards cover control-path categories (lost response, stale approval,
   cancellation) that depend on T21/T22 and are T24's; the holdout case intents have `intent` investigate|answer_only;
   SA:668's power statement is for n≈25. Open: the spread over answerable (proposal vs answer), abstain (missing,
   expired, revoked, draft-only), clarification (abstain + question), cross-tenant, injected, conflicting, superseded,
   asset-filtered, numeric-token and asset/alert cases (alerts exist only on 2026-10-02..06, §3.5); whether
   operational-fault cases belong in T23's model-quality set or only in T24's scenario suite; per-tenant balance; and
   whether the 47 retrieval queries, the 10 seeds or the 32 cards are reused, converted or left alone (an edit to
   `dev-queries.jsonl` breaks `tests/plan_n/test_retrieval_comparison.py:128` and the two committed reports).

3. **Who authors the cases and the gold labels, and how labels are checked.** Facts: BS:605 "The coding/tuning AI may
   develop the 80-case set"; SA:657 restricts AI-free authorship to the holdout; T17's dev queries are agent-authored
   (`docs/retrieval.md:110`); the labels are checked by `test_every_label_is_a_permitted_section_of_its_tenant`
   against `corpus.returnable` at `AS_OF` plus the hand-written `RETURNABLE_AT_AS_OF` anchor (the oracle-vs-SQL check
   alone is circular, `docs/retrieval.md:120-123`); T41's labels are evidence IDs and an expected outcome (SA:658).
   Open: agent-authored vs owner-reviewed dev labels; the labelling instant (reuse `AS_OF` 2026-10-16T12:00Z or the
   cards' 2026-10-06T12:00Z; the returnable set is equal at both, the alert picture is not); whether every label must be
   a returnable section of the case's tenant (and asset family), whether "allowed but not required" citations exist
   (e.g. a section's `purpose`), whether conflicting cases require both restart-wait sections, and whether a test pins
   the files' sha256 the way T18 pinned the queries.

4. **What each deterministic grader decides, and what it grades.** Facts: T23 names three graders: "schema, citations
   and abstention"; SA:660 names "citation validity, abstention correctness" for condition A; SA:676 "citations,
   schema, abstention"; BS:451 lists the structural checks (extra keys, sizes, types, enums, unknown evidence IDs,
   duplicates, authority fields); BS:452 "Existing citation membership does not prove support"; BS:456 the kind rules;
   SA:147 abstain ± question; the schemas differ by condition (B/C produce `model-draft` drafts; A produces a
   `manual-proposal`; SA:660 "Schema metrics apply to B and C only"). Today the only drafting route is the fake
   (`kind="proposal"` always, one citation = the top search hit) and no real draft has ever been produced; the worker
   stores only the draft hash and kind, and the frozen proposal plus `explanation.ready` carry `evidence_refs`. Open:
   the grader inputs (a `ModelDraft`-shaped JSON, a proposal payload, a run's events/state, or an adapter for each);
   schema validity (jsonschema against `model-draft.schema.json`, the pydantic `ModelDraft`, or both; first-pass vs
   post-repair is T19's/T25's); citation validity (every ref is in the bundle the run received and returnable for the
   tenant at the instant; no other tenant's, retired or draft ID); citation sufficiency (at least one, all, or a
   minimum of the gold "required" IDs); abstention correctness (kind=abstain on expect-none cases, not on answerable
   ones; abstain+question for clarification cases; how `answer` vs `proposal` is graded against `intent`); whether
   graders also emit per-case pass/fail for T25's 2-of-3 rule and the safety "any-trial" rule; and the result format.

5. **How graders are unit-tested without a model.** Facts: T23 DoD "graders unit-tested"; R111 "deterministic graders
   unit-tested"; CI has no Ollama or database; the existing pattern is pure functions with hand-built fixtures
   (`tests/plan_l/test_retrieval_baseline.py`, `tests/plan_n/test_retrieval_comparison.py`); `FakeDraftGenerator`
   exists; the schema negatives under `schemas/examples/` are generated and indexed. Open: hand-written good/bad draft
   fixtures per grader rule; whether the fake generator's real output over the dev cases is also graded (it would
   show the graders running end to end but measures the control path, as its limitation says); property tests
   (hypothesis is a dev dependency, `pyproject.toml:41`); where the tests live (a new `tests/plan_o/`, which must be
   added to `testpaths`) and whether graders live in `scripts/` (not mypy-checked) or a typed member package.

6. **The groundedness rubric.** Facts: T23 DoD 2 "Rubric with worked examples and inter-trial labelling
   instructions"; SA:661 blind, anonymized, shuffled B/C labelling and a ~20% re-label for intra-rater kappa (R073,
   T25); SA:676 "owner labels only groundedness"; BS:452 "assess whether claims follow from evidence"; the archived
   metric "Supported cited claims divided by evaluated cited claims" (`docs/archive/EVALUATION.md:31`, not authority);
   no line fixes the scale, the unit (per output, per claim, per citation), the anchors, the handling of abstentions,
   of `assumptions`/`limitations`, of conflicting evidence or of injected text; "inter-trial" is undefined (three
   trials per case per condition, SA:662; consistency across them vs re-labelling the same output later). Open: the
   scale and anchors; worked examples built from corpus-1 sections (and whether they may be model-free, hand-written
   outputs); the labelling instructions (blinding, order, time between passes, the ~20% re-label sample); the file
   that holds the owner's labels (format, blinded output IDs, never containing holdout text) and the kappa computation
   (T23 or T25); and where the rubric lives (`evals/dev/` or `docs/`).

7. **The numeric-token debt from T18.** Facts: query normalisation `'[^a-z0-9]+'` → space (`0011:192`) vs raw
   `to_tsvector('english', …)` on chunk text; ruling 10: "the development eval set adds numeric-token cases and
   measures the loss; a fix only with that evidence (BS:71)"; corpus-1's numeric tokens are few (0.10, 0.05, 100,
   30-day, asset IDs; no `M8x1.25`/`4.5` form); B07 already queries "0.10" and is answered correctly in both modes;
   the lexical body must stay byte-identical for the T18 comparison (ruling 10) and the queries file is hash-pinned;
   adding numeric-heavy text to corpus-1 is a new corpus version (re-ingest, re-embed, T41 re-labelling). Open: whether
   the numeric cases are retrieval cases (measured through `search_procedures_scoped`, live, like T17/T18) or
   model-quality cases; how many and in which file (a new retrieval query file vs `evals/dev/`); what "the loss" is
   measured as (hit@k with the number vs without, lexical vs vector, `ts_debug`-style lexeme comparison in a unit test);
   whether T23 runs that measurement (live) or only commits the cases for a later task; and whether the debt closes in
   T23 or moves on.

8. **Whether T23 runs anything live.** Facts: T23's DoD asks only for committed cases/labels, unit-tested graders and
   a rubric; R111 expected evidence is the same; the real model does not run until T19 (and T02's probe waits on the
   seal); conditions A/B/C need T21/T22/T19/T20; the dev database is at 0013 with corpus-1 embedded; T17/T18 measured
   retrieval live with `OPS_LIVE=1`. Open: data + graders + tests only; plus a live retrieval measurement over the
   dev cases (both modes) to validate the labels (recall of the gold IDs at k = 5/3); plus a fake-route end-to-end run
   per case; and whether any of it rewrites a committed report.

9. **How T25 consumes it.** Facts: T25 depends on T23; T25's DoD and notes (case-level Wilson, cluster bootstrap,
   McNemar, quality gates before the holdout run, manifests read into the report, B/C identical `model_route`); SA:671
   gives T23 the quality-gates schema with entries `{metric, condition, threshold, applies_to:
   "point"|"wilson_lower_95", blocking}`; `verify_handoff --contracts` will meta-validate it automatically
   (`:368-372`); `evals/quality-gates.json` itself is the owner's, before the first holdout run (SA:672). Open: whether
   T23 writes `evals/quality-gates.schema.json` now (SA:765) and with which metric/condition vocabularies (they name
   T23's grader outputs and the conditions A/B/C); whether T23 fixes the metric names T25 will report; whether the
   grader API takes a run manifest; whether a dev case and a holdout case pass through one loader (custody: T25 reads
   the holdout only at the release-candidate run); and whether the existing two Wilson implementations are unified.

10. **Interaction with existing development material.** Facts: `evals/README.md:1` points at a moved file and
    describes only the 10 seeds; T24's note asks to update evals/README (80/40 text is in
    `evals/handoff-development/README.md:5`); `verify_handoff.py:298` enforces `split == "development"` on the cards
    only. Open: whether T23 edits `evals/README.md` (and the handoff-development README) or leaves both to T24; whether
    the seeds file is superseded, kept or referenced; and whether `evals/dev/` cases carry a `split` field checked by
    the handoff verifier.

11. **Requirement and acceptance evidence.** Facts: R111 is the only requirement; its suggested test lies under the
    non-existent `tests/acceptance/`; past plans recorded unit tests plus data files as `evidence_paths` and set
    `RECORDED_LOCALLY` when the tests run in `check.py`/CI; R073 ("calibrated graders" vs "Compare grader with reviewed
    labels") is T25's. Open: R111's evidence paths and statuses (`IMPLEMENTED_LOCALLY_VERIFIED` / `RECORDED_LOCALLY`
    once graders are unit-tested in CI); whether "calibrated" in R111's title is met by T23 at all before any owner
    labels exist, or recorded "subject to" a later step; and any erratum (from 112) on R111's wording, on SA:671's
    ownership, or on BS:603's grouping sentence.

12. **The records.** Facts: Plan N's close-out touched `SESSION_STATE.md`, `STATUS.md`, `docs/PROJECT_HISTORY.md`,
    the plan file, `handoff/BUILD_BACKLOG.md`, `handoff/acceptance-matrix.json` and `handoff/tasks.json` (`3c69add`);
    `STATUS.md:365` is stale about the dev database; `tasks.json:3` `current_milestone` is still `M06` (T41 open);
    T23 has no review notes; the Plan N numeric-token debt line names T23. Open: the T23 close-out note's content, the
    debt list for Plan O (committed before coding, [R6-B7] pattern), the milestone line (M06 stays current while T41
    is open; T23 is M09), the STATUS correction, and the PROJECT_HISTORY entry.

---

## 6. Glossary of exact names

- **Task/requirement:** `T23` (M09, "Development eval set, gold labels and rubric"), `R111` ("Development evaluation set
  has gold labels and calibrated graders", suggested test
  `tests/acceptance/test_r111_development_evaluation_set_has_gold_labels_and_c.py`). Neighbours: `T25` (depends on
  T23), `T24`, `T41`, `T03`, `T02`, `T19`, `T20`, `T21`, `T22`, `T26`, `T31`; `R070`-`R074`, `R033`, `R034`, `R036`,
  `R040`, `R041`, `R081`, `R097`, `R114`, `R130`.
- **Directories and files:** `evals/dev/` (DoD, absent); `evals/README.md`; `evals/HOLDOUT.md`;
  `evals/holdout-case.schema.json`; `evals/development-seeds.jsonl` (D001-D010); `evals/handoff-development/README.md`,
  `scenarios.jsonl` (DEV-001-DEV-032); `evals/probe/inputs.jsonl` (PR-001-PR-060); `evals/retrieval/dev-queries.jsonl`
  (A01-A26, B01-B21; sha256 `d6d539bd…6938`); spec-named, absent: `evals/quality-gates.json`,
  `evals/quality-gates.schema.json`, `evals/holdout.sha256`, `reports/eval/`; `docs/archive/EVALUATION.md` (historical).
- **Schemas:** `schemas/model-draft.schema.json` (`kind` proposal|answer|abstain, `evidence_refs` ≤ 8, optional
  `question`), `proposal.schema.json`, `manual-proposal.schema.json`, `evidence.schema.json`,
  `run-manifest.schema.json`, `feedback.schema.json`, `route.schema.json`; examples `draft-valid.json`,
  `draft-answer-valid.json`, `draft-abstain-valid.json`, `draft-invalid-*.json`; generator `scripts/build_schemas.py`.
- **Code:** `ops_core.contracts.ModelDraft` (`:319`), `ProposalPayload` (`:358`), `SourceSnapshot` (`:349`);
  `ops_core.routing.RunManifest` (`:350`), `ModelRoute` (`:55`); `ops_core.states.freeze_allowed` (`:286`), `Intent`
  (`:69`); `ops_core.corpus` (`load :308`, `returnable :474`, `RELEASES :67`, `Document.evidence_id :116`);
  `ops_worker.drafting` (`PROMPT_VERSION`, `WORKFLOW_VERSION`, `DraftRequest`, `EvidenceItem`, `DraftGenerator`,
  `FakeDraftGenerator`, `make_generator`); `ops_worker.proposals` (`evidence_from_search`, `build_proposal`, `Frozen`,
  `EXPIRY`); `scripts.retrieval_baseline` (`K`, `CATEGORIES`, `KEYS`, `SETTINGS`, `Case`, `Outcome`, `load_queries`,
  `evaluate`, `wilson`, `proportion`, `summarize`, `report`, `markdown`); `scripts.retrieval_comparison` (`AS_OF`, `KS`,
  `mcnemar`, `paired`, `answers_digest`); `scripts.probe_stats` (`wilson`, `classify_output`, `classify_structured`);
  `scripts/gen_probe_inputs.py`; `scripts/verify_handoff.py`; `scripts/check.py` (`MEMBER_SRC`).
- **Corpus:** `corpus-1`, lock `81f50c2b8623675f9c899033cba748f289b7f4024003385aabc8a95147b71862`; labelling instant
  `AS_OF` = 2026-10-16T12:00:00Z (`tests/plan_l/test_corpus_files.py:34`, `RETURNABLE_AT_AS_OF :38`); cards'
  `fixture_clock` 2026-10-06T12:00:00Z; evidence ID `<DOCUMENT_ID>:v<version>:<section>`; labels `normal`, `injected`,
  `conflicting`; statuses `draft`, `approved`, `superseded`, `revoked`; tenants `alpha`, `beta`; assets A17, A21, A30,
  B22, B25, B31.
- **States and kinds:** run states `INSUFFICIENT_EVIDENCE`, `ANSWERED`, `AWAITING_INPUT`, `AWAITING_APPROVAL`,
  `BLOCKED_REVIEW`, `FAILED`; draft kinds `proposal`, `answer`, `abstain` (+ `question` = clarification); intents
  `investigate`, `answer_only`; graph routes `clarify`, `retrieve`, `draft`, `answer_only`, `abstain`, `freeze`, …;
  model routes `fake`, `qwen3:8b`; retrieval modes `lexical`, `vector_exact`.
- **Evaluation vocabulary (SA:656-676):** development set (~60, T23); holdout part 1 (~25 intents, T03) and part 2
  (labels, T41); conditions A (manual, `/manual-proposals`), B (RAG-only single call), C (orchestrated); 3 isolated
  trials; case passes at ≥ 2 of 3; Wilson 95%; case-cluster bootstrap; paired exact McNemar (p < 0.05); rule of three;
  blind shuffled groundedness labels; ~20% re-label, intra-rater kappa; quality-gate entry `{metric, condition,
  threshold, applies_to: "point"|"wilson_lower_95", blocking}`.
- **Prompts:** `handoff/prompts/incident-draft-v1.md` (sha256 `e3c26da3…a942`), `schema-repair-v1.md` (sha256
  `8b6658eb…c343`); `PROMPT_VERSION` `incident-draft-v1`.
- **Tests:** `tests/plan_l/test_retrieval_baseline.py`, `tests/plan_l/test_corpus_files.py`,
  `tests/plan_n/test_retrieval_comparison.py`, `tests/plan_a/test_probe_inputs.py`, `tests/plan_a/test_probe_stats.py`,
  `tests/plan_b/test_text_hygiene.py`, `tests/e2e/test_retrieval_baseline_live.py`,
  `tests/e2e/test_retrieval_comparison_live.py`; next free directory `tests/plan_o/` (not in `testpaths`).
- **Gates:** `uv run python scripts/check.py` (1461 passed, 218 skipped), `… --profile test` (1658 passed, 21 skipped),
  `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts` (exit 0). Next erratum: 112.

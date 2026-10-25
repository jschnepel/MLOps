# Plan P inputs: T19 (async LangChain ChatOllama DraftGenerator) — fact sheet

Prepared 2026-10-24 on branch `plan-p` at `d37f30c` (= `main` `3905b35`, which merged PRs #12-#14, plus one commit,
`d37f30c`, erratum 114: the holdout seal no longer gates T02, T19 or T25; the working tree was clean). Read-only on the
repository except this file. Facts only, no design. Citations: `SA:<line>` = `SPEC_AMENDMENTS.md`, `BS:<line>` =
`BUILD_SPEC.md` (line numbers as of `d37f30c`); the amendments win wherever the two conflict. Repository files are
cited as `path:line`. Nothing was run against a database, Keycloak, Ollama or any service for this sheet, no network
connection was made, and no secret, token or `.env` value was opened. Three read-only helper scripts (in the session
scratchpad, run as `uv run python -I <path> < /dev/null`) listed the tasks of `handoff/tasks.json` that depend on T19
or name model terms, printed chosen tasks' text with line numbers, and counted `evals/dev/cases.jsonl` by field; every
other fact is read from the files. `sha256sum` was run on the four files under `handoff/prompts/`.

**Holdout custody.** No holdout case file, label or seal was opened, read, grepped, hashed or listed. Every grep
excluded paths matching `*holdout*`, `*seal*` and `*.sha256`. Paths skipped by name only: `evals/HOLDOUT.md` and
`evals/holdout-case.schema.json` (seen as names in `ls evals`; not needed, not opened), `scripts/seal.py` (named by
`scripts/probe.py:49`'s import `from scripts.seal import sha256_of`; not opened) and `data/corpus/corpus.sha256` (seen as
a name in `ls data/corpus`; not opened). `evals/holdout.sha256` does not appear in `ls evals`.

**Probe outputs.** When this sheet was started, `reports/model-probe-qwen3-8b.md`, `reports/model-probe-freeze.txt` and
`data/model-pins.json` did not exist. Before the commit all three existed as **untracked, uncommitted** files written by
the T02 probe run (and `handoff/tasks.json` showed an uncommitted modification not made for this sheet); none of them is
part of this commit. Their key figures are in §3.9; §2-§5 were written against the tree without them and say so where
it matters.

Note on line numbers: AM-00 §12 prompts SA:47; AM-01 worker/core SA:75, SA:81; AM-10 DRAFTING row SA:137,
clarification signal SA:147, reasons SA:152, ANSWERED path SA:153, requester-asserted fields SA:154; AM-12 heartbeat
SA:193-199, async SA:201, model permit SA:203-205, graph SA:207; AM-14 `explanation.ready` SA:319, `model_summary`
SA:322; AM-16 SA:360-381 (rule SA:362, hint SA:375, graph router SA:377, model router SA:379, schemas SA:381); AM-20.2
`drafts` SA:421, `model_permit` SA:432, seed SA:440; AM-20.3 `transition_run` SA:451, `append_event` SA:452,
`freeze_proposal` SA:453, `reclaim_leases` SA:471; AM-20.4 `drafts` SA:496; AM-30 langchain-ollama SA:582, Ollama
SA:587; AM-31 SA:593-620 (model SA:595, settings SA:596, warm-up SA:597, digest check SA:598, network SA:599-601,
probe SA:602-619, no threshold SA:620); AM-50 conditions SA:660; AM-60 SA:690, SA:695, SA:697, SA:704; AM-70
SA:730-741; AM-80 checker SA:752, model-draft row SA:762, model-pins row SA:768, route/run-manifest row SA:770.
BUILD_SPEC: corrections BS:21-33; scope BS:50, BS:58; fixed choice BS:66; §8 nodes BS:328, `workflow_version` BS:342;
§11 BS:417, bundle BS:419; §12 BS:433-460 (interface BS:435-437, selection BS:441, settings BS:443, prompts BS:447,
validation BS:449-452, repair BS:454, kinds BS:456, explanation view BS:458-460); §15 BS:514-516; §17 BS:549-566;
§18 BS:572; §19 BS:590, BS:593; §20 BS:601, BS:607; runbook row BS:680; M07 BS:708, BS:718.

---

## 1. T19 verbatim, and what touches it

### 1.1 T19 (`handoff/tasks.json:830-860`)

- **id/milestone/title:** `T19` (`:831`), `M07` (`:832`), "Async LangChain ChatOllama DraftGenerator" (`:833`).
- **instructions** (`:834`, verbatim): "Versioned prompts; ChatOllama.ainvoke with AM-31 settings; structural
  validation incl. citation membership; one bounded repair; the AM-16 model router (DraftGenerator factory: fake |
  qwen3:8b | future named model) with no silent fallback; writes the run manifest {run_id, model_route, model_digest,
  prompt_version, corpus_version, retrieval_mode} and records the route in explanation.ready. Warm-up call at startup
  compares /api/show digest with data/model-pins.json and fails closed on mismatch (R127)."
- **depends_on** (`:835-840`): `["T07", "T17", "T02", "T44"]`. Status of each: T07 `DONE` (`:387` block), T17 `DONE`,
  T02 `DONE_PENDING_OWNER` (`:236`), T44 `DONE_PENDING_OWNER` (`:353`). T03 was removed by erratum 114.
- **requirement_ids** (`:841-849`): `R036`, `R037`, `R039`, `R040`, `R041`, `R127`, `R130`.
- **status** (`:850`): `"PLANNED"`. **external_approval_required** (`:855`): `false`.
- **definition_of_done** (`:851-854`, verbatim):
  1. "Recorded real-model run evidence (digest, params, outputs)."
  2. "Injected source cannot add tools or authority; invalid output -> repair -> controlled failure."
- **review_notes** (`:856-859`, verbatim):
  1. "`probe.py` pins the digest from `/api/tags` (`/api/show` carried no digest for qwen3:8b on Ollama 0.33.3);
     reconcile with AM-31's `/api/show` wording before designing the fail-closed check." (`:857`)
  2. "Erratum 114 (owner decision 2026-10-21): T03 is dropped from depends_on." (`:858`)
- `handoff/BUILD_BACKLOG.md:122` repeats the task unchecked; `:123` repeats review note 1 as a "*Review note:*".
- `tasks.json:4` note: "Status vocabulary: PLANNED, DONE (all steps done and reviewed), DONE_PENDING_OWNER (agent steps
  done; an owner-only step remains, named in review_notes). A proposed erratum awaiting the owner's decision does not
  change a task's status; a task met 'subject to' an erratum stays DONE." `tasks.json:3` `current_milestone` is `"M06"`.

### 1.2 The tasks T19 depends on, as they bear on it

- **T02** (`tasks.json:226-247`), "Environment inventory and qwen3:8b probe". Instructions (`:229`) end: "…
  mid-generation cancellation via `ollama ps`/GPU. Measurement, not tuning. Writes data/model-pins.json {model, digest,
  ollama_version, probed_at}." DoD (`:238-240`): "reports/model-probe-qwen3-8b.md with measured rates, denominators,
  CIs, digest and parameters."; "Cancellation behaviour measured and the model_permit release rule chosen
  accordingly."; "Owner decision on proceeding recorded." Notes: `:244` "Plan A (branch plan-a): agent part done in
  d008866, 7e5b422 and final-review F3-F5 (probe inputs, probe.py, AM-31 structured-output configuration). Pending
  owner step: the live probe run after the T03 seal; the probe refuses to run without a well-formed seal."; `:245`
  "Erratum 114 (owner decision 2026-10-21): T03 is dropped from depends_on; scripts/probe.py no longer requires
  evals/holdout.sha256 and still refuses to run unless both starter prompts match their pinned sha256."
- **T44** (`tasks.json:343-362`), "Ollama bridge, network runbook and model pins consumption". Instructions (`:346`)
  end: "…; worker reads data/model-pins.json for the digest check (implemented in T19)." Note (`:360`): "Plan B (branch
  plan-b): agent part done in 06bcec0, 8841305 (host and container routes to Ollama proven, ops_core.model_pins loader
  with 13 tests, docs/runbooks/ollama-network.md). Measured 2026-10-08: container traffic to host.docker.internal
  reaches the host from 127.0.0.1 (Docker Desktop proxies it), so the runbook's primary control is a loopback bind
  (OLLAMA_HOST=127.0.0.1:11434 at User scope) with the scoped firewall rule as fallback; it proposes an AM-31 errata.
  Pending owner step 10: apply step A, verify, fill the attestation table, decide on the errata."
- **T03** (`tasks.json:204-224`, owner, optional since erratum 114). Instructions (`:207`) still say "… records the hash
  outside the local repo … before T02 starts. … Also record externally, with the holdout hash, the sha256 of
  handoff/prompts/incident-draft-v1.md and schema-repair-v1.md (the probe's unchanged prompts)." DoD 3 (`:216`) still
  reads "Recorded before T02 (probe) and T19 (prompts) begin." Note `:222`: "Erratum 114 (owner decision 2026-10-21):
  the sealed holdout no longer gates anything. T02 and T19 no longer depend on T03; the holdout is optional owner work,
  and its tooling (case schema, scripts/seal.py) stays for it."
- **T07** (`tasks.json:387`, DONE) built `ops_core.contracts.ModelDraft`, the route enums and `RunManifest` (Plan C).
- **T17** (DONE) built corpus-1, `search_procedures_scoped` and `corpus_version` (Plan L).

### 1.3 Erratum 114 (`d37f30c`)

- Owner decisions list, `SESSION_STATE.md:1444-1449` (verbatim): "**Erratum 114 (decided by the owner, 2026-10-21;
  applied 2026-10-24 on `plan-p`):** the sealed holdout no longer gates anything ("remove holdout seal"). T03 is
  dropped from T02's and T19's `depends_on`, T41 from T25's; `scripts/probe.py` no longer requires
  `evals/holdout.sha256` and still refuses an edited starter prompt. T25 evaluates on the development set and every
  report says its results are not held out. A holdout stays optional owner work (T03, T41; `scripts/seal.py` and the
  case schema remain), and the custody rule still applies to it: no agent opens holdout case material."
- `SESSION_STATE.md:1450-1452`: "**Build autonomously (2026-10-21/24):** the owner asked the agent to run the build
  until it is set up, and chose to go ahead past T44 step 10 with it pending (the loopback bind of step A is applied).
  The agent records owner decisions it takes on that instruction as provisional, for the owner to confirm or reverse."
- `docs/PROJECT_HISTORY.md:1075-1092` ("33. The owner removed the holdout seal so the model work could start").
- The commit changed `scripts/probe.py` (seal precondition dropped, `EXPECTED` prompt pins kept, `probe.py:61-66`,
  `:376-382`), `tests/plan_a/test_probe_stats.py` (new `test_probe_main_refuses_an_edited_prompt` `:210` and
  `test_probe_main_needs_no_holdout_seal` `:220`), `SESSION_STATE.md`, `docs/PROJECT_HISTORY.md`,
  `handoff/BUILD_BACKLOG.md`, `handoff/tasks.json`.
- **Records not updated by erratum 114** (still say T19 waits on the seal): `SESSION_STATE.md:13-15` ("T19 on the probe
  of T02, the seal of T03 and step 10 of T44"), `SESSION_STATE.md:1575`, `STATUS.md:390` ("Next: no PLANNED task can
  start; T19 and T41 wait on owner steps."), SA:704 ("T02 and T19 depend on T03; T25 depends on T41"), T03 DoD 3
  (`tasks.json:216`), SA:609 ("T03 records both hashes externally together with the holdout seal").

### 1.4 Acceptance rows (`handoff/acceptance-matrix.json`)

T19's seven rows, all `implementation_status: NOT_IMPLEMENTED_OR_NOT_TARGET_VERIFIED`, `evidence_status: NOT_RUN`,
`evidence_paths: []`, milestone `M07`, `blocking_for_v1: true`:

- **R036 (:686-700)** security, "Retrieved instructions cannot grant tool authority"; expected (verbatim): "Inject
  administrator-style text into SOP fixture; no permission/action boundary changes."; owners `T19`. (`ACCEPTANCE.md:42`
  lists it under **M06**, the 1.0 snapshot.)
- **R037 (:701-715)** model, "Actual LangChain and Ollama inference occurs"; expected: "Trace ChatOllama request using
  named installed model; record real output, versions and hardware."; owners `T19` (`ACCEPTANCE.md:43`).
- **R039 (:731-745)** explanation, "Reasoning text is not authority or an audit record"; expected: "Model claims
  success without receipt; UI/actions remain authoritative and raw reasoning stays off."; owners `T19`
  (`ACCEPTANCE.md:45`).
- **R040 (:746-760)** model, "Invalid model schema has a bounded repair policy"; expected: "Repeated malformed JSON
  exhausts one repair within remaining budget; no incident."; owners `T19` (`ACCEPTANCE.md:46`).
- **R041 (:761-775)** model, "No fake or hosted fallback masquerades as real output"; expected: "Remove real model or
  block endpoint; clear failure/manual path, no silent substitute."; owners `T19` (`ACCEPTANCE.md:47`).
- **R127 (:2220-2235)** model, "The pinned model digest is verified at worker warm-up"; expected: "Worker start with a
  mismatching digest in data/model-pins.json fails closed; matching digest proceeds; probe date recorded."; source
  `SPEC_AMENDMENTS.md`; owners `T19`. Not in `ACCEPTANCE.md` (R081-R131 are matrix-only, `ACCEPTANCE.md:3`).
- **R130 (:2279-2295)** model, "The model route is explicit, recorded and never silently substituted"; expected: "Run
  manifest records model_route, digest, prompt_version, corpus_version; a missing or mismatched model fails closed; B
  and C evaluation conditions show identical routes."; owners `T19`, `T25`.
- Suggested tests (targets; `tests/acceptance/` does not exist): `tests/acceptance/test_r036_retrieved_instructions_
  cannot_grant_tool_authori.py`, `…test_r037_actual_langchain_and_ollama_inference_occurs.py`,
  `…test_r039_reasoning_text_is_not_authority_or_an_audit_reco.py`,
  `…test_r040_invalid_model_schema_has_a_bounded_repair_policy.py`,
  `…test_r041_no_fake_or_hosted_fallback_masquerades_as_real_o.py`,
  `…test_r127_the_pinned_model_digest_is_verified_at_worker_wa.py`,
  `…test_r130_the_model_route_is_explicit_recorded_and_never_s.py`.
- Matrix note (`acceptance-matrix.json:3`): `RECORDED_LOCALLY` = the evidence-path tests pass in `scripts/check.py` and
  CI; `RECORDED_LOCALLY_LIVE` = passes against the running dev profile with `OPS_LIVE=1`, collected but skipped by
  `check.py` and CI.

Other rows that name the draft generator, the model, prompts, repair, the manifest, `explanation.ready`, the digest or
the permit (owner, status):

- **R004 (:51-66)** T07, `IMPLEMENTED_LOCALLY_VERIFIED`/`RECORDED_LOCALLY`: "Inject role/tenant/approved/actor fields in
  model and browser payloads; validation fails."
- **R028 (:517-539)** T16, `RECORDED_LOCALLY_LIVE`; expected ends "(… the model-facing path for asset data arrives with
  T20, because the worker does not yet pass asset reads to the model.)"
- **R035 (:672-685)** T26: "Revoke source after draft; caches/checkpoints/summary/events/citation viewer do not
  re-expose it."
- **R038 (:717-730)** T20: "Trace order and input bundle show MCP read results before final model proposal."
- **R055 (:977-990)** T26: "Inject HTML/script/javascript URL into tool/model/source; displayed safely or rejected."
- **R057 (:1007-1020)** T21: "With model unavailable, search and manual draft work under identical independent
  review/write policy."
- **R058 (:1022-1035)** T28: "Trace API/job/graph/LangChain/MCP/destination/reconcile; show failures and version
  identifiers." **R059 (:1037-1050)** T28, "Telemetry excludes credentials and sensitive reasoning".
- **R061 (:1067-1080)** T29: "Model/MCP/DB/outbox fail independently; controlled states, no invented success or
  offline-to-cloud jump." **R062 (:1082-1095)** T29: "Oversize input/results, exhausted repair/time/tool cap and full
  queue stop predictably without retry storm."
- **R065 (:1127-1140)** T30, "Probes and drain distinguish model outages from dead API".
- **R076 (:1294-1307)** T37 (`blocking_for_v1: false`): "Verify manifest includes actual image/lock/model/prompt/
  corpus/report hashes and approved commit."
- **R081 (:1369-1383)** T02, `NOT_RUN`: "Probe report with >=30 distinct inputs, isolated env freeze, thinking
  disabled, num_ctx set, first-pass/post-repair validity with Wilson CIs, identical-repeat rate, cold vs warm latency,
  VRAM, cancellation behaviour; data/model-pins.json written."
- **R083 (:1404-1422)** T45, `RECORDED_LOCALLY`: "Probes: model_summary status, action.confirmed without receipt,
  ok+UNKNOWN, outcome without action_id all rejected."
- **R088 (:1508-1529)** T13, `RECORDED_LOCALLY_LIVE`: "Blocked loop and >30 s fake drafter keep the lease; forced
  renewal failure cancels the call and revokes handles." (evidence includes `tests/plan_h/test_permit.py`).
- **R101 (:1748-1764)** T05/T43/T44, `NOT_RUN`: "Dev profile (PostgreSQL+pgvector, Keycloak, Ollama bridge) healthy on
  Windows; secrets generated outside git."
- **R111 (:1938-1961)** T23, `RECORDED_LOCALLY`: deterministic graders "unit-tested on hand-written drafts
  (core/src/ops_core/grading.py, tests/plan_o/)".
- **R113 (:1979-1993)** T21: "Feedback endpoint stores classified feedback, emits feedback.recorded, alters no
  prompt/policy/permission."
- **R129 (:2256-2278)** T12/T20: "… a model hint can only produce clarify."; note: "the graph router's table and its
  walk land with T20."

### 1.5 Debts other tasks pushed to T19

- **Walking skeleton (T08)**, `SESSION_STATE.md:1054`: "fake model → T19; no LangGraph or durability → T20."
- **Plan G (T12)**, `SESSION_STATE.md:1108`: "no producer of a model hint exists: the admission router takes `hint`
  and the API passes `None` → T19;" repeated at `SESSION_STATE.md:337-338` and `STATUS.md:157`. Code markers:
  `api/src/ops_api/store.py:416` `hint=None,  # TODO(T19): the model router may supply a hint; it can only produce
  clarify`; `core/src/ops_core/routing.py:210` "optional model hint (no producer exists yet; TODO(T19))."
- **Plan H (T13)**, `SESSION_STATE.md:1130-1132`: "the model permit is released when the draft call ends or is
  cancelled, and by its 65 s TTL; SA:205's "hold the permit until `ollama ps` shows idle" waits on T02's cancellation
  measurement, and today's only route is the fake drafter → T19;". Open item `SESSION_STATE.md:440-441`: "Model permit
  TTL: 65 s with no cap on the hold until T19's 60 s attempt cap; a hold over 65 s would let a second worker take the
  slot (only the fake drafter exists today)." Code marker `worker/src/ops_worker/permit.py:7-8` "TODO(T19): SA:205's
  stricter release ("hold until `ollama ps` shows idle"), once T02 has measured whether a cancelled request stops
  Ollama's generation." `STATUS.md:189` "the permit's idle release rule -> T19". Plan H final review
  (`docs/reviews/plan-h-final-review-2026-10-15.md:266`) "Permit TTL 65 s vs an uncapped hold | stay deferred | T19's
  60 s cap."; `:277` "Real Ollama behaviour under cancellation and the permit's idle-release rule. T19, gated on T02's
  measurement."; `:143` "a run that waits behind another worker's draft (up to 60 s once T19 caps it) loses its lease
  to "compute budget spent"" (that consequence is debt → T29, `SESSION_STATE.md:1171-1173`).
- **Plan L (T17)**, `SESSION_STATE.md:1297-1298`: "the model-side proof that the injected documents grant nothing
  (R036), and detecting the conflicting pair and abstaining → T19/T20 (rulings 13 and 14);". `docs/retrieval.md:26-30`:
  the injected document "is ingested and returned like any other, because the proof that retrieved text cannot grant
  authority is the model side's, T19 … both are returned, and detecting the conflict and abstaining is T19 and T20's."
  `STATUS.md:321` "the injected and conflicting sources' model-side proofs -> T19/T20". Rulings 13 and 14 as recorded
  in `docs/reviews/plan-review-l-2026-10-17.md:101-108` ("the model-side proof is T19's (R036)"; "detection and
  abstention → T19/T20").
- **Plan O (T23)**, `SESSION_STATE.md:1386-1388`: "the development cases are checked against corpus-1 by unit test and
  never run: no model trial, no condition A, B or C run and no groundedness label exists yet → T19 (the first real
  drafts) and T25 (trials, conditions, labels) (Plan O rulings 4 and 8);".
- **Plan C (T07)** final review `docs/reviews/plan-c-final-review-2026-10-08.md:134`: "`ModelRoute` holds only `fake`
  and `qwen3:8b`: AM-16's "future named model" is deferred to T19."
- **Reference traceability** `reference/TRACEABILITY.md:47`: "`test_control.py::test_unknown_citation_rejected` |
  replace-by | tests/acceptance R041 citation membership | T19".
- **Plan A final review** `docs/reviews/plan-a-final-review-2026-10-07.md:140` (M5): "`scripts/probe.py:52`: the digest
  source conflicts with the spec. The probe pins the digest from `/api/tags` and asserts that `/api/show` carries none.
  AM-31 says T19's worker compares the `/api/show` digest against the pin. Reconcile this in a spec errata note or in
  T19's review_notes before T19, …" (became T19 note 1). `docs/reviews/plan-b-final-review-2026-10-08.md:41` and
  `docs/reviews/plan-review-b-2026-10-08.md:607` call it a T19 concern.
- **Plan C review** `docs/reviews/plan-review-c-2026-10-08.md:529`: `ModelPins.probed_at` "is `AwareDatetime` with no
  zero-offset check … It accepts `+02:00`, which the schema rejects. Reword …, or leave a `TODO(T19)`." The code kept
  the loader's rule and `scripts/build_schemas.py:745-746` says "`ops_core.model_pins` accepts any aware timestamp; the
  schema additionally pins a zero offset." No `TODO(T19)` exists in `model_pins.py`.
- **Plan N (T18)**: `SESSION_STATE.md:1352-1354` "the worker still searches in lexical mode only; choosing the mode
  per run and recording it in the run manifest → T20 … and T25 …" (`routing.py:363` carries `TODO(T25)`), so
  `retrieval_mode` in the manifest is today always `lexical` (`worker/src/ops_worker/proposals.py:106`).
- `git grep "TODO(T19)"` (code) finds exactly the three markers above (`api/src/ops_api/store.py:416`,
  `core/src/ops_core/routing.py:210`, `worker/src/ops_worker/permit.py:7`).

### 1.6 Tasks that consume T19, and what they expect

- **T20** (`tasks.json:862-892`, depends `T19`, `T14`, `T16`): instructions (`:865`) "Nodes per AM-12 incl. the
  route_request graph router whose conditional edges are generated from the core/routing.py table; retrieval before
  drafting; …; ANSWERED path." DoD `:882` "Trace shows MCP reads complete before drafting."; `:885` "A test enumerates
  every graph-router row and asserts the node reached (R129)." R038, R114 are T20's. SA:377: "validated draft kind" is
  the draft **after** structural validation; only route it selects is `abstain`/`clarify`/`answer_only` vs `freeze`.
- **T25** (`tasks.json:1020-1048`): note `:1045` "Reads each run's manifest (model route, digest, prompt and corpus
  versions) into the eval report; conditions B and C must show identical model_route."; `:1046` erratum 114: "T25
  evaluates on the development set (evals/dev/cases.jsonl) and every report says its results are not held out". Co-owns
  R130. SA:660: "B and C use identical model, prompt-version family, retrieval settings and `num_ctx`."
- **T21** owns R057 ("With model unavailable, search and manual draft work …") and the manual-proposal path.
- **T26** (`tasks.json:1053`) "… authorized evidence viewer; …" owns R035, R055 (summary/citation re-exposure,
  untrusted model text).
- **T28** (`:1102`) OTel in worker incl. LangChain/model call (BS:570), R058/R059; BS:572 "Record commit, workflow
  version, prompt hash, model identifier/digest, corpus/index version and tool schema version per run."
- **T29** (`:1122`) "Queue/model/time/retry caps; dependency outages produce templated truthful states; …"; note
  `:1133` "Outage tests for Ollama, MCP and destination." Owns R061, R062 (exhausted repair cap).
- **T30** (`:1142`) containers; R065 (model outage vs dead API); `docs/runbooks/dev-topology.md:71` "the worker's
  generation path (T19) chooses its own" Ollama URL.
- **T31** (`:1169`) "separate trusted workflow for real-model checks run manually".
- **T37** (`:1288`) release provenance, R076 (model/prompt hashes in the release manifest, BS:670).
- **T38** (`:1305`) fenced checkpoint writes; it consumes T20, not T19 directly.
- **T23** (DONE) produced the graders that will grade T19's drafts (`core/src/ops_core/grading.py`).

---

## 2. Spec passages that bind T19

### 2.1 AM-31 Model runtime profile (SA:593-620)

- SA:595: "**Model:** `qwen3:8b`, selected by the model router (AM-16); the route, digest and prompt version are
  recorded per run. Record its digest."
- SA:596: "**Settings:** `ChatOllama(reasoning=False)` (maps to Ollama `think:false`), `num_ctx=16384`,
  `num_predict=1000`, `temperature=0`, 60 s timeout, `with_structured_output(method="json_schema")` **plus**
  application-side validation."
- SA:597: "**Warm-up:** a cold model load took 53 s in the round-4 dry run, against the 60 s timeout. The worker
  therefore issues a warm-up call (with `keep_alive`) at startup, before it accepts drafting jobs, and T02 measures cold
  vs warm latency."
- SA:598: "**Digest check:** at warm-up the worker compares the model digest (`/api/show`) with the pin in
  **`data/model-pins.json`** (`{model, digest, ollama_version, probed_at}`, written by T02) and **fails closed** on
  mismatch. Owned by T19 and tested by R127 [R5-S9, R6-B4]."
- SA:599-601: Ollama reachable only from loopback and the Docker/WSL subnet; owner applies the restriction from
  `docs/runbooks/ollama-network.md`; "The agent does not change system settings."
- SA:606-608: the probe "uses the delivered prompts unchanged": `incident-draft-v1.md` sha256
  `e3c26da349dcb0a9bfafb6c786a06f15fece389c21fa63b1b64fef7659b6a942`; `schema-repair-v1.md` sha256
  `8b6658eb0f08136699b78e7ab1d76972f88f4399db720e92e5be5335b0c7c343`. SA:610: "Outputs are validated against the 1.0
  `schemas/model-draft.schema.json`."
- SA:615-619: records "JSON-valid and schema-valid rates, both first-pass and after one repair, with Wilson 95% CIs";
  "whether any thinking content appears"; "**cancellation behaviour:** cancel mid-generation, then check `ollama
  ps`/GPU and the next request's start latency."
- SA:620: "**There is no fixed pass threshold.** The owner reviews the measured rates and decides whether to proceed,
  change the model, or adjust prompts (R081). If thinking cannot be disabled, the probe fails."
- AM-30 SA:582: `langchain-ollama` `1.1.0`; SA:587: "Ollama | installed 0.33.3; latest 0.35.1. Record the version
  actually used, and upgrade only with owner approval." `SESSION_STATE.md:1431`: Ollama "Observed at 0.40.4 on
  2026-10-15"; the owner's decision on 0.40.4 vs 0.33.3 is open (`SESSION_STATE.md:1378-1379`).

### 2.2 AM-16 Routers (SA:360-381)

- SA:362: "Routing is explicit, enumerable and deterministic-first. Model output may hint at a route; it never
  selects one. An input the router cannot classify becomes a clarification or a 422 and never starts work (R129)."
- SA:375: "Optional model-assisted intent classification runs **after** the deterministic rules and can only turn a
  route into `clarify`; it can never produce `reject`, `investigate` or `readonly_answer` on its own."
- SA:379 (verbatim): "**Model router** (`DraftGenerator` factory in the worker): selects `fake` (deterministic
  substitute), `qwen3:8b` (local Ollama) or a future named model from `MODEL_MODE` and policy; the choice, model digest
  and prompt version are written to the run manifest and the `explanation.ready` event; there is **no silent
  fallback** between routes (R130, R041)."
- SA:381: "AM-80 adds `schemas/route.schema.json` (the three route enums) and `schemas/run-manifest.schema.json`."
- SA:690: "T19 the model router and run-manifest recording (R130). T25 reads the manifest." SA:697: "R127 (model digest
  pin) owned by T19; `data/model-pins.json` written by T02."
- ADR-0003 (`docs/adr/ADR-0003-routers-and-read-write-mcp-split.md:16`): "a **model router** (the `DraftGenerator`
  factory) that selects `fake`, `qwen3:8b` or a future model by configuration, records the choice in the run manifest,
  and never falls back silently." `docs/ARCHITECTURE.md:104` row: "Chosen by configuration, recorded in every run's
  manifest and `explanation.ready` event; **no …" and `:112` "R130, R041 | The model route is recorded; a missing
  model fails clearly instead of falling back".
- BS:441 (1.0, not superseded by AM-00): "`MODEL_MODE=fake` is the reproducible application-test profile.
  `MODEL_MODE=ollama` requires a named installed model; fail clearly if it is absent. No silent fallback from real to
  fake or local to hosted. … obtain approval before a large download or paid service." (SA:379 names the routes
  `fake`/`qwen3:8b`; BS:441 names the mode `ollama`.)

### 2.3 AM-12: the nodes that call the generator, the permit, cancellation, async (SA:170-218)

- SA:207: nodes `load_run`, `route_request`, `await_clarification`, `retrieve_evidence` (mcp-read),
  `draft_with_langchain`, `validate_and_freeze` (`freeze_proposal`), … "There is no free-running think→tool→act loop;
  the model never sees a tool." BS:328 lists the same with `resolve_context`.
- SA:196-199: "**When renewal fails, the worker:** cancels in-flight model and tool calls; revokes its invocation
  handles; exits the run." Erratum 57 (`SESSION_STATE.md:403-406`): "exits the run" means cancelling the job's effects
  in flight (MCP and model calls; no database unit is interrupted), revoking the job's handles and handing the job back
  with no transition.
- SA:201: "**Async only:** use `AsyncPostgresSaver`, `ChatOllama.ainvoke` and async MCP/HTTP clients. No synchronous
  I/O on the event loop."
- SA:203-205 (verbatim): "**Model permit:** - A `model_permit` row, leased and polled with `SKIP LOCKED` plus backoff,
  enforces global model concurrency (1). - Whether a cancelled request actually stops Ollama's generation is
  **measured** in T02. If it doesn't, the permit is held until `ollama ps` shows idle or the 60 s cap passes."
- AM-20.2 SA:432: `model_permit` | `worker` "sel, upd(all)" | `sweeper` "upd(`leased_until`) (reclaim)" | seeded by
  `migrator`. Erratum 50 (`SESSION_STATE.md:387-388`): "`model_permit(slot, holder, run_id, leased_until)`, one seeded
  slot, `worker` `sel, upd(all)`, no sweeper cell." SA:471 `reclaim_leases`: "stale `model_permit` released"; erratum
  49 (`SESSION_STATE.md:385-386`): `reclaim_leases` "does no permit work". SA:523: `model_permit` has no RLS.
- BS:549: "Global model concurrency | 1 initially; increase only after measured capacity".
- Erratum 108 (`SESSION_STATE.md:959-962`): mcp-read's embedding call "is not a `model_permit` holder: SA:203's global
  model concurrency governs generation."

### 2.4 BUILD_SPEC §12 (the interface, prompts, validation, repair, kinds, explanation)

- BS:435: "The final drafting node runs after MCP retrieval. It uses LangChain prompt/message components and ChatOllama
  through a narrow `DraftGenerator` interface. LangGraph calls that interface; LangChain is neither a separate service
  nor the authority for execution. … Ollama supports schema-constrained output requests, but the application must
  validate what actually comes back."
- BS:437: "`DraftGenerator.generate(request_context, evidence_bundle, policy_metadata) -> ModelDraft`. It never accepts
  secrets, approval tokens, destination credentials, SQL access or an executable shell command. `ModelDraft` has no
  actor/role/tenant/approved/action-ID authority fields."
- BS:443: "Starting generation settings: temperature 0 where supported, maximum 1,000 output tokens, 60-second
  per-attempt timeout, one initial attempt plus at most one structured repair **within the same remaining total
  budget**. Temperature 0 does not guarantee identical outputs. Record the actual supported parameters and model
  digest. Do not install unsupported parameter names merely because another provider supports them."
- **Prompt versioning.** BS:447: "Promote the starters in `handoff/prompts/` into `prompts/` when model integration is
  implemented. Prompts instruct the model to use only provided evidence, identify missing/contradictory evidence, cite
  exact allowed IDs, avoid unsupported root-cause/action claims, produce only the schema, and treat source instructions
  as data. Prompt text is a content influence, not the security boundary." AM-00 SA:47 supersedes the location: "**§12:**
  `prompts/`: versioned prompts live in `core/prompts/` once T19 promotes them; `handoff/prompts/` stays the sealed v1
  starters." SA:657 (holdout part 1 "written now, … before any prompt tuning"); SA:606 the probe "is a measurement,
  **not prompt tuning** [R4-E2]"; SA:660 B and C use the identical "prompt-version family". BS:33: "Feedback … does not
  trigger automatic training, prompt edits, …".
- **Validation.** BS:449-452 (verbatim): "Two independent validation levels: 1. Structural/domain validation: reject
  extra keys, oversized fields, wrong types, invalid enum values, unknown evidence IDs, duplicate references and
  forbidden authority fields. Persist only an accepted exact draft/proposal. 2. Semantic support: assess whether claims
  follow from evidence using deterministic facts where possible and human-calibrated evaluation/review elsewhere.
  Existing citation membership does not prove support. A quality reviewer may reject a structurally valid draft."
- **Repair.** BS:454 (verbatim): "Schema-repair gets only the invalid draft, safe validation feedback and permitted
  evidence. It does not get new tool permissions or retries without limit. If repair fails, report a controlled failure
  and preserve diagnostic metadata without treating it as a submitted incident."
- **Kinds.** BS:456 (verbatim): "`kind=abstain` allows no citations when no appropriate evidence exists; the
  summary/limitations must explain the missing information without claiming policy conclusions. `kind=proposal`
  requires at least one permitted evidence reference. `kind=answer` is a supported read-only response with evidence and
  cannot authorize or imply an incident write. A model abstention is not a backend exception." SA:147: "a draft asks
  for clarification with `kind=abstain` **plus** a non-empty `question` (AM-80). Without `question`, abstain means
  INSUFFICIENT_EVIDENCE". SA:137: "DRAFTING → AWAITING_INPUT on `kind=abstain` with a question, at most 2 clarification
  rounds; on a third round → INSUFFICIENT_EVIDENCE". SA:153: the ANSWERED path "is selected by `runs.intent =
  'answer_only'`"; `freeze_proposal` refuses such runs. SA:154: "a draft carrying `supersedes_run_id` is rejected by
  `freeze_proposal`."
- **Explanation view / reasoning.** BS:460: "Optional model-emitted reasoning is disabled by default, separately
  classified and redacted if ever enabled. It cannot become a permission, success status or verified statement about
  all internal influences. Never manufacture detailed hidden reasoning." BS:32: "Never fabricate an internal chain of
  thought or use emitted reasoning as an audit record."
- BS:419 (the bundle): "The model receives a bounded evidence bundle: fixed asset/interval, status observation, alert
  records or aggregate plus truncation notice, permitted excerpts, source IDs/versions/hashes and retrieval timestamp.
  … Keep prompts/instructions separate from source text, but do not claim that formatting alone prevents injection."
  BS:417: "If no appropriate source exists or procedures conflict materially, ask/abstain instead of inventing a merged
  policy." BS:551: "Retrieval bundle | At most 8 references and 12,000 input tokens within model context; truncation
  explicit".

### 2.5 Citation membership

- T19 instructions: "structural validation incl. citation membership" (`tasks.json:834`); BS:451 "unknown evidence IDs,
  duplicate references"; BS:452 "Existing citation membership does not prove support."
- The incident-draft starter (`handoff/prompts/incident-draft-v1.md:9`): "Cite only the supplied evidence IDs …"; its
  payload template carries `"allowed_evidence_ids": "RENDER_ALLOWED_IDS"` (`:21`) and `:26` "The application validates
  output shape/reference membership separately and does not use this prompt as an authorization control."
- The repair starter (`handoff/prompts/schema-repair-v1.md:5`): "Use only the same permitted evidence and exact allowed
  evidence IDs."
- T23's grader `check_citation_validity` (`core/src/ops_core/grading.py:289-300`) fails `duplicate_ref`, `not_offered`
  (a ref outside what the trial was offered) and `not_permitted_by_case`.

### 2.6 The run manifest

- AM-80 SA:770: "New: `schemas/route.schema.json`, `schemas/run-manifest.schema.json` | The three route enums (AM-16);
  the per-run manifest `{run_id, model_route, model_digest, prompt_version, corpus_version, retrieval_mode}`".
- SA:379 (route, digest, prompt version → "the run manifest and the `explanation.ready` event"); SA:595 ("the route,
  digest and prompt version are recorded per run"); R130's expected evidence (§1.4).
- BS:572: "Record commit, workflow version, prompt hash, model identifier/digest, corpus/index version and tool schema
  version per run." BS:342: "Pin `workflow_version` per run." BS:607 (per trial: "versions, actual model mode, hardware
  and quantization, token/settings, …"). BS:670 (release manifest: "model/runtime digest/configuration,
  prompt/workflow/tool schema/corpus/index/evaluation versions").
- No spec line names the manifest's storage (table, column, event or file).

### 2.7 `explanation.ready`

- AM-14 SA:319 adds the type; SA:322: "`model_summary` may emit only `explanation.ready`, with no status field."
  SA:452 `append_event`: "`worker` may pass `source=model_summary` only for `explanation.ready`".
- SA:379: "the choice, model digest and prompt version are written to the run manifest and the `explanation.ready`
  event". T19 instructions: "records the route in explanation.ready".
- The schema closes its payload (§3.6): `message` (required, 1-2500) and `evidence_refs` (≤8, unique) only.
- BS:458: the explanation view shows "a short recommendation, evidence, assumptions, limitations and recorded actions."
  BS:516: "Use templates for infrastructure failure messages so reporting does not depend on a working LLM."

### 2.8 R127's fail-closed startup check

- SA:597-598 (above); R127 expected: "Worker start with a mismatching digest in data/model-pins.json fails closed;
  matching digest proceeds; probe date recorded."
- `docs/PROJECT_HISTORY.md:53`: "a warm-up call runs at worker start and verifies the pinned model digest".
- `docs/runbooks/dev-topology.md:73`: "The worker's digest check reads `data/model-pins.json` through
  `ops_core.model_pins.load_model_pins` (T19)."
- AM-20.6 SA:528 is the existing pattern of a startup assertion ("Every service … asserts at start that the table is
  absent outside the test profile").

### 2.9 Async, timeouts and model errors

- SA:201 (`ChatOllama.ainvoke`, no synchronous I/O on the event loop). SA:596 "60 s timeout". BS:443 "60-second
  per-attempt timeout". BS:554: "Model output | At most 1,000 tokens; at most two generation attempts including
  repair". BS:555: "Active compute duration | 90 seconds total; each model attempt max 60 seconds clipped to remaining
  budget".
- BS:562 (verbatim): "Retry only transient permitted reads with capped exponential backoff/jitter. Do not retry
  validation, authorization, stale version or content conflicts as transient errors. Circuit-break repeated dependency
  failures; fail clearly and expose diagnostics."
- BS:564 (verbatim, first sentence): "Model unavailable: retain request/evidence and offer authorized manual
  search/proposal workflow." … "Hosted fallback: never automatic."
- BS:680 (runbook row): "Model outage / invalid output | Preserve run/evidence; bounded retries; manual permitted path;
  no fake/cloud fallback; no write from failed draft".
- BS:566: "A fake-model test proves the control path, not answer quality. A live-model benchmark on one machine is not
  a capacity claim for a different GPU/quantization/context."
- SA:451 `transition_run` (worker only): "DRAFTING → AWAITING_INPUT / ANSWERED / INSUFFICIENT_EVIDENCE / FAILED".
  Erratum 8 (`SESSION_STATE.md:172`): "a FAILED run reached by `transition_run` on exhausted infrastructure policy
  carries no reason; the `run.failed` event's message says why."
- No spec line says whether a model timeout, an unreachable Ollama or an exhausted repair is retryable for the
  `investigate` job.

### 2.10 Tests the spec asks for

- BS:590 (layer 5): "Workflow/model-contract tests: fake deterministic control tests separately from LangChain/Ollama
  structured generation, missing evidence and bounded repairs." BS:593 (layer 8): "Real-model evaluations: repeated
  scenario trials, groundedness and task outcomes; not merged into unit-test pass counts."
- BS:708 (M07 exit): "Actual model generation evidence and persistent pause/resume". BS:718: "M07 can develop model and
  graph pieces using controlled fakes …, but its exit cannot pass without actual required integration."
- BS:23: "Do not silently present … a fake model as a real LLM". BS:50: "local Ollama plus a clearly labeled
  deterministic test substitute". BS:58 excludes "automatic cloud fallback".

---

## 3. The tree as it is (branch `plan-p`, `d37f30c`)

### 3.1 `worker/src/ops_worker/` — drafting today

- **`drafting.py`** (90 lines). Module docstring `:1-7`: "The model router's one route for T08: a deterministic fake
  DraftGenerator … `make_generator` is the router: `fake` is the only route until T19 adds `qwen3:8b`; anything else
  is an error, never a silent fallback (R130). The fake draft says it is fake in its limitations (BUILD_SPEC §1)."
  - `PROMPT_VERSION = "incident-draft-v1"` (`:19`); `WORKFLOW_VERSION = "investigation-v1"` (`:20`).
  - `DraftRequest` (`:23-30`, frozen dataclass): `asset_id`, `text`, `start_at`, `end_at`.
  - `EvidenceItem` (`:33-42`): `evidence_id`, `document_id`, `version`, `section`, `content_sha256`, `excerpt`.
  - `DraftGenerator(Protocol)` (`:45-50`): `async def generate(self, request: DraftRequest, evidence:
    list[EvidenceItem]) -> ModelDraft`. No `policy_metadata` argument (BS:437 names three).
  - `ModelRouteError(ValueError)` (`:53-54`).
  - `FakeDraftGenerator` (`:57-83`): optional `delay_seconds` (tests); raises `ValueError` on empty evidence; always
    `kind="proposal"`, cites `evidence[0]` only, title "Review synthetic warnings on {asset_id}", one assumption, one
    limitation "Drafted by the fake model route ({PROMPT_VERSION}); the control path, not answer quality."
  - `make_generator(mode)` (`:86-90`): returns `FakeDraftGenerator()` only for `ModelRoute.FAKE.value`; else
    `ModelRouteError(f"MODEL_MODE={mode!r} is not a route of this build (only 'fake' until T19)")`.
- **`proposals.py`** (108 lines): `EXPIRY = timedelta(minutes=15)` (`:22`); `Frozen` (payload, canonical, sha256,
  manifest; `:25-32`); `evidence_from_search(doc)` (`:35-54`) turns the `search_procedures` envelope into
  `EvidenceItem`s; `build_proposal(...)` (`:57-108`) builds `ProposalPayload` with `prompt_version=PROMPT_VERSION`,
  `workflow_version=WORKFLOW_VERSION` (`:94-95`) and a `RunManifest(run_id, model_route=ModelRoute.FAKE,
  model_digest=None, prompt_version=PROMPT_VERSION, corpus_version=corpus_version, retrieval_mode="lexical")`
  (`:100-107`). Docstring `:5-6`: "The run manifest records the model route (SA:379) and is validated here even though
  T19 is the task that stores it." The manifest is **not stored** anywhere.
- **`handlers.py`** (327 lines), `investigate` (`:86-153`): QUEUED → RETRIEVING (`:110`); mints a read handle; emits
  `tool.started`; calls `search_procedures` with `{"query": text[:500], "limit": 3, "mode": "lexical"}` as a lease
  effect (`:123-130`); `tool.completed`; no evidence → `INSUFFICIENT_EVIDENCE` "no procedure section matched"
  (`:137-139`); RETRIEVING → DRAFTING (`:140-144`); `_draft_and_freeze(..., str(doc["data"]["corpus_version"]))`
  (`:146`); `LeaseLost` re-raised (`:147-148`); any other exception → `DRAFTING → FAILED` "drafting failed"
  (`:149-153`).
  - `_draft_and_freeze` (`:156-209`): builds `DraftRequest` from the run row (`:160`); `async with
    permit.model_permit(deps.conn, holder=deps.worker_name, lease=lease):` around `draft = await
    lease.effect(deps.generator.generate(request, evidence))` (`:161-162`); `freeze_allowed(Intent(run["intent"]))`
    (`:163`, raises `AnswerOnlyRun` for `answer_only`, so such a run ends FAILED "drafting failed" today); then in one
    fenced unit: `INSERT INTO app.drafts (id, tenant_id, run_id, draft_sha256, validated, kind) VALUES (…, true, …)`
    with `frozen.sha256` (`:187-191`); `append_event(type=EXPLANATION_READY, payload={"message": f"Drafted by model
    route {frozen.manifest.model_route.value} (prompt {frozen.manifest.prompt_version}).", "evidence_refs": [...]},
    source=EventSource.MODEL_SUMMARY)` (`:192-202`); `freeze_proposal(...)` (`:203-209`).
  - The draft is validated only by `ModelDraft`'s own model validators (it is returned as a `ModelDraft`); there is no
    citation-membership check against the offered evidence: `build_proposal` indexes `by_id[r]` (`proposals.py:73`,
    `:89`), so a ref outside the bundle raises `KeyError` → "drafting failed".
  - Every draft kind is frozen as a proposal today; there is no path for `answer`, `abstain` or `question`.
  - `Deps` (`:50-63`) carries `generator: DraftGenerator`.
- **`permit.py`** (73 lines): `PERMIT_TTL_SECONDS = 65` (`:22`, "SA:596: a model attempt is capped at 60 s; 5 s more
  for the call around it"); backoff 0.25 s doubling to 2 s with jitter (`:23-32`); `_wait_for_permit` polls with
  `persistence.take_model_permit` in its own transaction, `lease.check()` before each try, the back-off sleep as a lease
  effect (`:35-55`); `model_permit(...)` async context manager releases in `finally` in its own transaction (`:58-73`).
  Docstring `:7-8`: `TODO(T19)` (§1.5).
- **`main.py`** (211 lines), `_main` (`:140-203`): `redaction.install()`; `generator =
  make_generator(settings.env("MODEL_MODE"))` (`:143`, "unset or any other route: refuse to start (R130)");
  `settings.leases()`; Keycloak token source; loop connection with `SET lock_timeout = '10s'` (`:38`, `:150`); a probe
  connection; `assert_clock_profile` (`:153`); `assert_relation(probe, "app.model_permit")` (`:154`); heartbeat thread;
  health server on `OPS_WORKER_HEALTH_PORT` (default 8070; `/health/live`, `/health/ready`, `:105-127`); the poll loop
  (`run_forever`, `:80-102`, `POLL_SECONDS = 0.5`). No Ollama call and no pin read at startup.
- **Config/env.** `settings.env(name, default)` (`core/src/ops_core/settings.py:30-35`): empty counts as unset, raises
  `SettingsError`. `MODEL_MODE` has no default in the worker (`main.py:143`); `scripts/skeleton.py:435`
  `env.setdefault("MODEL_MODE", "fake")`. `settings.urls().ollama` = `OPS_OLLAMA_URL`, default
  `http://127.0.0.1:11434` (`settings.py:428`, `:439`), today read by mcp-read and `skeleton.py embed` only;
  `.env` keys `OLLAMA_BASE_URL_HOST`/`OLLAMA_BASE_URL_CONTAINER` are the bridge test's
  (`docs/runbooks/dev-topology.md:64-71`). `deploy/helm/templates/resources.yaml:72-73` sets `MODEL_MODE:
  deterministic` (reference app). Lease settings `OPS_LEASE_SECONDS` 30, `OPS_HEARTBEAT_SECONDS` 10,
  `OPS_LOOP_STALL_SECONDS` 28, `OPS_COMPUTE_BUDGET_SECONDS` 90 (`settings.py:354-357`); the heartbeat loses a lease
  whose hold passes the budget ("compute budget spent", `worker/src/ops_worker/heartbeat.py:180-181`).
- **`Lease.effect`** (`core/src/ops_core/lease.py:133-167`): runs "an MCP call, a model call, the permit's back-off
  sleep; never a database unit" as a child task the heartbeat may cancel; a cancellation by `cancel_effects` surfaces
  as `LeaseLost`.
- **MCP client timeouts** (`worker/src/ops_worker/mcp.py:131-137`): connect 10 s, read 60 s (httpx2).
- **Job types** (`core/src/ops_core/jobs.py:37-47`): `investigate`, `resume_input`, `execute`, `recover`,
  `expire_proposals`, `sync_memberships`, `sweep_wakeups`, `deliver_outbox`; `jobs.type` CHECK added in revision 0007
  (`migrations/app/versions/0007_leases_fences.py:96`). `handlers.handle` (`:296-306`) handles `investigate` and
  `execute`; others are logged "not handled by the walking skeleton". `jobs(id, type, run_id, dedup_key UNIQUE,
  available_at, claimed_by, claimed_at, attempts, done_at)` (SA:494).
- `worker/pyproject.toml:4,6`: description "Run-lease worker: LangGraph orchestrator, LangChain draft node, MCP client";
  dependencies `["ops-core", "mcp==2.3.0", "uvicorn>=0.54,<1"]`. `worker/README.md:23-24`: "`investigate`: read tool
  on mcp-read → fake draft under the model permit (`MODEL_MODE=fake`, the only route until T19) → frozen proposal →
  AWAITING_APPROVAL."

### 3.2 `core/src/ops_core/`

- **`contracts.py`**: `AUTHORITY_FIELDS` (`:40-53`: tenant_id, actor, actor_id, role, roles, approved, approved_by,
  destination, reviewer, requester); `_Strict = ConfigDict(frozen=True, extra="forbid", strict=True)` (`:75`); `Short`
  1-500, `Title` 1-120, `Summary` 1-2500, `EvidenceRef` 1-160, all NFC-normalised (`:78-82`). `ModelDraft` (`:319-346`):
  `kind: Literal["proposal","answer","abstain"]`, `title`, `summary`, `evidence_refs` ≤8 unique, `assumptions` ≤8,
  `limitations` ≤8, `question: Short | None`; `_kind_rules`: proposal/answer cite ≥1; only abstain carries a question;
  property `clarification_requested`. `load(model, text)` (`:104`) parses JSON mode and refuses duplicate keys
  (`DuplicateKey`, `:89-101`). `ProposalPayload` (`:358`) holds `workflow_version`, `prompt_version`.
- **`routing.py`**: `ModelRoute(StrEnum)` `FAKE = "fake"`, `QWEN3_8B = "qwen3:8b"` (`:55-59`, "table owned by T19");
  `AdmissionFacts.hint: AdmissionRoute | None = None` (`:217`) and the `hint` rule (`:307`); `RunManifest` (`:350-371`):
  strict, frozen; `run_id: UUID`, `model_route: ModelRoute`, `model_digest: str | None` (pattern `^[0-9a-f]{64}$`),
  `prompt_version` 1-60, `corpus_version` 1-100, `retrieval_mode: Literal["lexical", "vector_exact"]`; validator
  `_real_models_carry_a_digest` (a non-fake route without a digest is refused). No model-router table exists (the
  module docstring `:5`: "the model table with T19").
- **`model_pins.py`** (94 lines): `Digest` = `^[0-9a-f]{64}$` (bare lowercase hex; `:19`); `ModelPinsError(ValueError)`
  (`:22`); `ModelPins` strict, frozen, `extra="forbid"`: `model`, `digest`, `ollama_version`, `probed_at:
  AwareDatetime` (`:26-35`); `load_model_pins(path)` (`:38-57`): missing file, not JSON, or invalid → `ModelPinsError`.
  `EmbeddingPins` adds `dimension: Literal[768]` (`:60-71`); `load_embedding_pins` (`:74-94`) also maps an unreadable
  file to `ModelPinsError`. The docstring `:4-5`: "The digest is the bare 64-hex value Ollama reports in `/api/tags` (no
  `sha256:` prefix), exactly as `scripts/probe.py` writes it; one canonical form keeps the T19 comparison a plain string
  equality." Nothing in the tree calls `load_model_pins` except tests.
- **`embeddings.py`** (the T18 pin pattern): `OllamaEmbedder` (`:151-234`) with one `httpx2.AsyncClient`, 10 s
  timeout (`TIMEOUT_SECONDS`, `:40`), no retry; asks only `/api/version`, `/api/tags`, `/api/embed`; error classes
  `EmbeddingError` (`code="UPSTREAM_INVALID"`, not retryable), `Unavailable` (`UNAVAILABLE`, retryable: unreachable,
  timeout, 5xx), `PinMismatch` (`UNSUPPORTED_MODE`), `Malformed` (`:51-73`); `installed_digest(model)` reads
  `/api/tags`, matching `name`/`model` and `name:latest` (`:191-202`); `verify(pins)` (`:214-220`) raises
  `PinMismatch` on another model/dimension or a `/api/tags` digest that is not the pin's. Docstring `:9-12`:
  "`/api/show` carries none … never a generation endpoint, so it is not a `model_permit` holder".
- **`grading.py`** (T23): `DRAFT_SCHEMA = ROOT / "schemas" / "model-draft.schema.json"` (`:46`); `check_schema(output)`
  (`:272-286`) passes only when both the JSON Schema (`Draft202012Validator`) and `ModelDraft.model_validate_json` accept
  the draft, reasons `valid`/`model_rejected`/`schema_rejected`/`both_rejected`; `check_citation_validity`,
  `check_citation_sufficiency`, `check_abstention` (`:289-337`); `Output(draft, offered_refs, case, manual)`
  (`:164-175`). The module imports `jsonschema` (`:39`), which is a runtime dependency of `ops-core`
  (`core/pyproject.toml`).
- **`outcomes.py`**: `EventSource.MODEL_SUMMARY = "model_summary"` (`:139`); `EventType.EXPLANATION_READY =
  "explanation.ready"` (`:173`); `PAYLOAD_KEYS` (`:189`, "the event schema's payload keys (its payload object is
  closed)"); `event_rules_ok` (`:227-…`) refuses a `model_summary` event unless the type is `explanation.ready` and the
  payload is `{message (non-empty str), evidence_refs (list of non-empty str)}` only (`:242-256`).
- **`persistence.py`**: `assert_clock_profile` (`:162`), `assert_relation` (`:171`), `transition_run` (`:279`),
  `append_event` (`:315`), `freeze_proposal` (`:367`), `fenced` (`:930`), `take_model_permit` (`:1013-1024`: `UPDATE
  app.model_permit SET holder, run_id, leased_until = app.current_time() + make_interval(secs => ttl) WHERE slot =
  (SELECT slot … WHERE leased_until <= app.current_time() ORDER BY slot FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING
  slot`), `release_model_permit` (`:1027-1033`: `… WHERE slot = %s AND holder = %s`).
- **`states.py`**: `freeze_allowed(intent)` (`:286-298`) raises `AnswerOnlyRun` for `answer_only`.

### 3.3 Schemas, prompts and the probe

- **`schemas/model-draft.schema.json`**: `$id` `urn:operations-copilot:schema:model-draft:1`, title "Operations
  Copilot target model-draft v1" (`:3-4`); `additionalProperties: false`; properties `kind` (enum), `title` 1-120,
  `summary` 1-2500, `evidence_refs` 0-8 unique items 1-160, `assumptions`/`limitations` 0-8 items 1-500, `question`
  1-500; required all but `question`; `allOf`: proposal/answer need ≥1 ref, a non-abstain may not carry `question`.
  sha256 `9fe09e073a0c481e2ce18a68772269735b1a27a284ee06b0b410a1542db8c8a7`. History: imported in `1f57919` (1.0),
  changed once in `b8cf8c4` (T45: `question` and the abstain rule, +21 lines). So the file the probe validates against
  today is the 1.3.6 schema, not SA:610's "1.0" schema.
- **`schemas/run-manifest.schema.json`**: `$id` `…:run-manifest:1`; `additionalProperties: false`; `run_id` uuid,
  `model_route` enum `fake`|`qwen3:8b`, `model_digest` bare hex or null, `prompt_version` 1-60, `corpus_version` 1-100,
  `retrieval_mode` `lexical`|`vector_exact`; all six required; a non-fake route needs a string digest.
- **`schemas/route.schema.json`**: three enums (`admission`, `graph`, `model`: `fake`, `qwen3:8b`), `minProperties: 1`.
- **`schemas/model-pins.schema.json`**: `model` 1-200, `digest` bare hex, `ollama_version` 1-80, `probed_at` date-time
  with `(Z|\+00:00)`; all four required; `additionalProperties: false`. **`schemas/embedding-pins.schema.json`** adds
  `dimension` const 768.
- **`schemas/event.schema.json:239-…`**: `if source = model_summary then type const explanation.ready and payload
  {message 1-2500 (required), evidence_refs ≤8 unique}, additionalProperties false` (`:250-275`).
- Schemas are generated by `scripts/build_schemas.py` (`run_manifest` fields `:802-806`; `model_pins()` `:741-755`;
  proposal `prompt_version` text(1, 60) `:374`).
- **`handoff/prompts/`**: `incident-draft-v1.md` (26 lines; sha256 `e3c26da3…a942`, matches SA:607 and
  `scripts/probe.py:64`), `schema-repair-v1.md` (7 lines; sha256 `8b6658eb…c343`, matches SA:608 and `probe.py:65`),
  plus `review-checklist.md` and `session-handoff-template.md` (not runtime prompts). Both runtime prompts are unchanged
  since the 1.0 import (`git log -- handoff/prompts` lists only `1f57919`).
  - `incident-draft-v1.md:3`: "**Status:** Target template; not wired into the supplied reference. Render with LangChain
    after MCP retrieval. Keep the structured response schema in application code. Never provide credentials, approval
    records, actor privilege fields or executable tools to this drafting call." The system message is `:7-11`; the
    user payload template (`:15-24`) has keys `confirmed_request`, `asset_id`, `interval`, `permitted_evidence`,
    `allowed_evidence_ids`, `requested_output_schema`, each a `RENDER_…` placeholder; `:26` "Placeholders are template
    inputs, not valid runtime defaults."
  - `schema-repair-v1.md:3`: "Invoke at most once, only with remaining compute/token budget, and without new tools or
    permissions." `:5` "If the task cannot be supported, return an appropriate structured abstention. Return JSON only;
    no additional fields or private reasoning transcript." `:7` "Application inputs: sanitized invalid output; safe
    structural validation errors; original confirmed request; permitted evidence; expected schema. Never include stack
    traces, tokens or unauthorized source text in repair feedback. Persistent invalid output is a controlled failure,
    not a reason to keep retrying."
  - `core/prompts/` and `prompts/` do not exist.
  - `scripts/verify_handoff.py:385-396` rejects a CR or a BOM in files under `schemas`, `data/handoff-fixtures`,
    `data/corpus`, `handoff/prompts`, `evals` (not `core/`); `tests/plan_b/test_text_hygiene.py:22` applies the same
    rule to every tracked file outside `reference/`.
- **`scripts/probe.py`** (417 lines; run command `:3`: `uv run --isolated --no-project --python 3.13 --with
  "langchain-ollama==1.1.0" --with "jsonschema" python -I scripts/probe.py`):
  - `MODEL = "qwen3:8b"` (`:51`); `OLLAMA = "http://127.0.0.1:11434"` (`:53`, "Loopback only"); `TIMEOUT_S = 60`
    (`:57`); `EXPECTED` prompt hashes (`:63-66`).
  - `model_digest()` (`:81-86`): "Return the digest of the installed model; /api/tags carries digests, /api/show does
    not." Matches `name` or `model` equal to `qwen3:8b`.
  - The wrapper (`:169-171`): `ChatOllama(model=MODEL, base_url=OLLAMA, reasoning=False, num_ctx=16384,
    num_predict=1000, temperature=0)` then `llm.with_structured_output(schema, method="json_schema",
    include_raw=True)`; imports `from langchain_core.messages import HumanMessage, SystemMessage` and `from
    langchain_ollama import ChatOllama` inside `run_probe` (`:163-165`).
  - Messages: `SystemMessage(content=<incident-draft-v1.md file text>)`, `HumanMessage(content=json.dumps({"request":
    request_text, "evidence": evidence}))` (`:185`, `:193`, `:201`); the whole Markdown file is the system message and
    the user payload is not the template's `RENDER_…` shape.
  - Each call `asyncio.wait_for(drafter.ainvoke([...]), timeout=TIMEOUT_S)` (`:199-203`); the result dict is `{"raw":
    AIMessage, "parsed": …, "parsing_error": …}` (`:173-180`); thinking is read from
    `raw.additional_kwargs.get("reasoning_content")` (`:179-180`).
  - The repair (`:218-240`): one attempt when the first pass is not schema-valid and did not error; system message =
    `schema-repair-v1.md` text; user = `json.dumps({"invalid_output": text, "validation_errors": errors[:10] or [kind],
    "evidence": evidence})`; a call that errored or timed out is not repaired.
  - Cancel row (`:280-312`): an unwrapped `llm.ainvoke` asked for "a very long incident narrative", cancelled after
    3 s, then `/api/ps` and a timed "Reply with the single word ok." call. Report lines `:365-366`: "Owner decision
    (R081): [proceed | change model | adjust prompts]" and "model_permit release rule (AM-12, chosen from the cancel
    row above): [release on cancel | hold until /api/ps idle or the 60 s cap]".
  - Writes `data/model-pins.json` as `json.dumps({"model", "digest", "ollama_version", "probed_at":
    datetime.now(UTC).isoformat()}, indent=2) + "\n"` (`:400-406`), so `probed_at` is spelled `+00:00`.
- **`scripts/probe_stats.py`** (148 lines): `classify_output(text)` (`:33-…`) returns `"thinking_present"` when
  `"<think>"` or `"</think>"` is in the text (`:39-40`), docstring: "Thinking content is a failure of the no-thinking
  setting, never stripped"; `classify_structured(raw_text, parsed, parsing_error)` (`:48-…`); `has_thinking(text,
  reasoning_content)` (`:61-63`) = text tag or metadata; `wilson` (`:15`); `seal_problem` (`:133`, now unused by
  `probe.py`).
- **The reference adapter** (not ported; `reference/src/operations_copilot/models.py`): `OllamaModel` (`:28`) restricts
  the base URL to `127.0.0.1`, `localhost`, `ollama`, `host.docker.internal` over http (`:37-38`), 60 s timeout
  (`:34`), `"format": DRAFT_SCHEMA` (`:46`), refuses redirects (`:54-55`), and "Intentionally ignore any provider
  'thinking' field." (`:63`). AM-70 (SA:730-741) lists no defect in it.

### 3.4 `app.model_permit` (revision 0007) and its users

- Table (`migrations/app/versions/0007_leases_fences.py:88-95`): `slot smallint PRIMARY KEY CHECK (slot >= 1), holder
  text, run_id uuid, leased_until timestamptz NOT NULL DEFAULT '-infinity'`; owner `migrator`; `INSERT … (slot) VALUES
  (1)`. Grants (`:62`): `worker` sel + upd. Docstring `:7-9`: "the worker takes a free slot with SKIP LOCKED and an
  expiry on the application clock, so no role needs to reclaim it and only the worker holds any cell on it (erratum 50;
  SA:523: no RLS)."
- Functions that take/release it: `persistence.take_model_permit` / `release_model_permit` (§3.2), called only from
  `worker/src/ops_worker/permit.py` (`:49`, `:73`), which `handlers._draft_and_freeze` uses (`:161`). The sweeper has
  no permit code. The worker refuses to start without the relation (`main.py:154`).
- Tests: `tests/plan_h/test_permit.py` (backoff, release after the block and after a lost lease, polling, lost lease
  stops the wait, slow fake drafter does not block the loop; `:62-154`); `tests/e2e/test_heartbeat_live.py:233-275`
  (`test_the_model_permit_is_held_for_the_draft_and_released`: held by the drafting worker, a second taker refused,
  released to `-infinity`); `tests/plan_h/test_migration_0007.py`, `tests/e2e/test_migration_0007_live.py`.

### 3.5 Storage relevant to the manifest and drafts

- `app.runs` (`0001_walking_skeleton.py:72-93` plus later columns `checkpoint_id`, `budget_used` in 0002 `:206`): no
  column for model route, digest, prompt version, corpus version, retrieval mode or workflow version.
- `app.drafts` (`0001:133-140`): `id, run_id, draft_sha256, validated, kind, created_at`, plus `tenant_id` (added in
  `0002_roles_grants_rls.py:238-241`); worker `ins, sel` (SA:421). SA:496: "`drafts(id, run_id, draft_sha256, validated, kind, created_at)` holds only identifiers, the
  hash of the canonical validated draft and the verdict. The draft payload itself is held by the worker between
  validation and `freeze_proposal` (one node); it is never written to `drafts`, to checkpoints (R091) or to events".
  Today the worker writes `validated = true` only.
- `git grep` over `migrations/` finds no `manifest`, `model_route` or `prompt_version`; `corpus_version` exists only on
  `app.corpus_ingestions` and in `search_procedures_scoped`'s result (`0011_governed_corpus.py:73`, `:164`;
  `0012_asset_scope.py:104`). The latest revision is `0013_embeddings`.
- `_append_event`'s `model_summary` rule in SQL (`0008_journal_outbox.py:171-180`): refuses unless type is
  `explanation.ready`, `message` is a non-empty string and the keys are only `message`/`evidence_refs`; any payload key
  outside the schema's set is refused (`:165-167`, OC006).

### 3.6 Workspace dependencies

- Root `pyproject.toml`: workspace members `core`, `api`, `worker`, `mcp-read`, `mcp-write`, `asset-sim`,
  `incident-sim`, `sweeper` (`:31`); dev group pytest, ruff, mypy, `jsonschema>=4.26,<5`, hypothesis, pyyaml,
  rfc3339-validator, pytest-asyncio (`:35-45`); mypy `strict = true` (`:66-69`) with overrides for `authlib.*` and
  `jsonschema.*` (`:72-80`); `testpaths` ends `"tests/plan_o", "tests/e2e"` (`:48-52`; no `tests/plan_p`).
- `core/pyproject.toml` dependencies: pydantic, psycopg[binary], sqlalchemy, alembic, pyjwt[crypto], `httpx2`,
  jsonschema, rfc3339-validator.
- `uv.lock` (67 `name =` entries, workspace members included): **no** `langchain-ollama`, `langchain-core`, `langgraph`, `ollama` or `httpx` entry; it has
  `httpx2`, `anyio`, `jsonschema` 4.26.0, `pydantic` 2.13.5, `mcp` 2.3.0.
- `scripts/check.py:28-37` `MEMBER_SRC` runs mypy over every member `src` (incl. `worker/src`); `.github/workflows/
  ci.yml:32` runs `uv sync --locked --all-packages` (a dependency change must be in `uv.lock`), `:33` `check.py`, `:37`
  `verify_handoff.py --reference-code --manifest --contracts`.

### 3.7 Tests that pin drafting today

- `tests/plan_d/test_worker.py:31-35` `test_model_router_has_one_route_and_no_fallback`: `make_generator("fake")` is a
  `FakeDraftGenerator`; `"ollama"`, `"qwen3:8b"`, `""`, `"FAKE"` raise `ModelRouteError`. `:39`
  `test_fake_draft_is_deterministic_and_valid`; `:51` `test_build_proposal_binds_hash_to_canonical_bytes`.
- `tests/plan_c/test_jobs_routes_outcomes.py:206-246` `test_routes_and_manifest` (asserts `{r.value for r in
  ModelRoute} == {"fake", "qwen3:8b"}` at `:227`; manifest rules); `:351-363` strict manifest values.
- `tests/plan_b/test_model_pins.py` (`:29`, `:35` `test_loads_exactly_what_probe_py_writes`, `:51`, `:81`, `:88`).
- `tests/plan_h/test_worker_units.py` (Deps with `FakeDraftGenerator()` `:188`; fence, lease, deadline, interrupted
  runs); `tests/plan_h/test_permit.py`.
- Live (`OPS_LIVE=1`, run by `check.py --profile test`, `scripts/check.py:57-62`): `tests/e2e/test_worker_live.py:150`
  `test_investigate_then_execute` (events include `("explanation.ready", "model_summary")` `:169`), `:202`
  `test_drafting_failure_fails_the_run` (a raising generator → events `run.accepted, tool.started, tool.completed,
  run.failed`; states `QUEUED, RETRIEVING, DRAFTING, FAILED`); `tests/e2e/test_r105_walking_skeleton.py:36` (event
  order incl. `explanation.ready`); `tests/e2e/test_heartbeat_live.py:61` (`BlockingGenerator`), `:171` (slow fake
  drafter), `:233` (permit).
- `tests/plan_o/test_grading.py` unit-tests the graders on hand-written drafts; `evals/dev/cases.jsonl` has 60 cases:
  intent `investigate` 31 / `answer_only` 29; expected_kind `proposal` 19 / `answer` 12 / `abstain` 29; `clarify` true
  10; categories `investigate_supported` 14, `answer_only` 8, `missing_source` 8, `retired_source` 8, `clarification`
  6, `cross_tenant` 4, `injected` 4, `conflicting` 4, `numeric` 4; 30 per tenant.
- Probe tests (no Ollama): `tests/plan_a/test_probe_stats.py` (thinking classification `:51`, `:105`, `:151`; probe
  refusals `:210`, `:220`). The only test that reaches Ollama is `tests/plan_b/live/test_ollama_bridge.py:17`
  (`/api/version` on the host and container URLs).
- No test calls ChatOllama, LangChain or a generation endpoint.

### 3.8 Corpus material T19's proofs name

- Injected (`data/corpus/catalog.json`, `label: "injected"`): `ALPHA-VENDOR-PORTAL` v1 (compressor; sections
  `purpose`, `vendor-contact`, `portal-note`, `records`; `:62-66`) and `BETA-CONTRACTOR-MEMO` v1 (conveyor; `purpose`,
  `guard-inspection`, `memo-note`, `records`; `:111-115`).
- Conflicting (`label: "conflicting"`): `ALPHA-COMPRESSOR-TRIP` v1 (`restart-wait` section; `:20-24`) and
  `ALPHA-COMPRESSOR-COOLDOWN` v1 (`:27-31`), each naming the other in `conflicts_with`.
- Corpus version `corpus-1`; the worker passes the `corpus_version` returned by `search_procedures` into the manifest
  (`handlers.py:146`).

### 3.9 Pins and probe outputs

- `data/embedding-pins.json`: `nomic-embed-text`, digest `0a109f422b47e3a30ba2b10eca18548e944e8a23073ee3f3e947efcf3c45e59f`,
  `dimension` 768, `ollama_version` `0.40.4`, `probed_at` `2026-10-19T18:40:32Z`.
- Earlier observations of the qwen3:8b digest: `/api/tags` lists `qwen3:8b` with digest
  `500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41` (`docs/reviews/plan-review-b-2026-10-08.md:196`,
  read live 2026-10-08; `docs/reviews/plan-review-n-2026-10-19.md:38` "`qwen3:8b` `500a1f06…8b41`" on 2026-10-19 under
  Ollama 0.40.4). `/api/show` "carried no digest for qwen3:8b on Ollama 0.33.3" (T19 note 1) and none for
  `nomic-embed-text` on 0.40.4 (`plan-review-n:38`).
- **The T02 probe outputs (untracked, uncommitted when this sheet was committed; not part of it):**
  - `data/model-pins.json`: `{"model": "qwen3:8b", "digest":
    "500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41", "ollama_version": "0.40.4", "probed_at":
    "2026-10-24T22:42:22.383063+00:00"}` (the same digest as the earlier `/api/tags` reads; `+00:00` spelling,
    fractional seconds).
  - `reports/model-probe-qwen3-8b.md`: 60 distinct inputs, Ollama 0.40.4, interpreter 3.13.13, 60 s cap (`:3-4`).
    JSON-valid first pass 59/60, Wilson [0.911, 0.997] (`:8`); **schema-valid first pass 5/60, [0.036, 0.181]** (`:9`);
    **schema-valid after one repair 5/60, [0.036, 0.181]** (`:10`); thinking 0/60 first-pass inputs, 0/54 repair calls,
    0/16 repeat and post-cancel calls (`:11-12`, `:16`); cold-start latency "not measured (cold call failed:
    TimeoutError: )" (`:13`; error list `:23` "[('PR-001', 'TimeoutError: ')]"); warm p50/p95 2.77 s / 4.14 s (`:14`);
    peak VRAM 8851 MB over 806 samples, RTX 3080 (`:15`); identical outputs on 3 repeats 1/5 (`:17`).
  - **Cancel row:** "Full `ok` call after mid-generation cancel, incl. /api/ps | 0.15 s" (`:18`); memory.used right
    after cancel 8848 MB (`:20`); `/api/ps` right after the cancel lists `qwen3:8b` (size 7411114966, digest
    `500a1f06…8b41`, `parameter_size` "8.2B", `quantization_level` "Q4_K_M") (`:21`); "Cancel/post-cancel error: None"
    (`:25`).
  - Decision lines (`:27-30`): "Owner decision (R081): proceed — PROVISIONAL, recorded by the agent on 2026-10-24 under
    the owner's instruction to run the build autonomously; the owner confirms or reverses it." and "model_permit release
    rule (AM-12, chosen from the cancel row above): release on cancel — PROVISIONAL, same basis (the `ok` call after the
    cancel completed in 0.15 s)."
  - "Diagnosis added after the run" (`:32-40`, agent, not part of the measured figures): one error per failing draft in
    a follow-up of 8 inputs: a `proposal` or `answer` draft "also carries `question`", which the schema's `allOf` `else:
    not required [question]` forbids; "Ollama's `format` constraint does not enforce `if`/`then`/`else`, and the repair
    call returned the same field"; the probe's user payload `{request, evidence}` carries no evidence IDs, "so
    `evidence_refs` named bundle keys (`status`, `alerts`, `documents`)"; "The cold call exceeded the 60 s cap (PR-001's
    timeout)."
  - `reports/model-probe-freeze.txt` (41 lines): `python==3.13.13` (`:1`), `httpx2==2.16.0` (`:12`), `httpx==0.28.1`
    (`:13`), `jsonschema==4.26.0` (`:18`), `langchain-core==1.7.0` (`:19`), `langchain-ollama==1.1.0` (`:20`),
    `langchain-protocol==0.0.20` (`:21`), `ollama==0.6.3` (`:23`), `pydantic==2.14.1` (`:26`) (the workspace lock has
    pydantic 2.13.5 and no httpx, langchain or ollama package).

### 3.10 Gates

- Given in the brief: `check.py` (dev) 1540 passed / 219 skipped at `d37f30c`; live (`--profile test`) last 1737
  passed / 21 skipped (Plan O). Recorded in the tree: `SESSION_STATE.md:1018`, `STATUS.md:376-377` and
  `docs/PROJECT_HISTORY.md:1064` give Plan O's `1539 passed, 219 skipped` and `1737 passed, 21 skipped`; erratum 114
  replaced one seal test by two tests (§1.3), consistent with 1540. Not re-run for this sheet.
- `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts` (exit 0 at Plan O close).

---

## 4. Prior rulings, debt lines and proposed errata touching T19

- **T19 review note 1** (`tasks.json:857`) and its sources: Plan A final review M5
  (`docs/reviews/plan-a-final-review-2026-10-07.md:140`, `:204` "Record the M5 `/api/show` vs `/api/tags`
  discrepancy as a review_note on T19."); Plan B (`docs/reviews/plan-b-final-review-2026-10-08.md:41`;
  `docs/reviews/plan-review-b-2026-10-08.md:607`).
- **Plan B B1** (`docs/reviews/plan-review-b-2026-10-08.md:195-197`, `:414`): the loader first rejected the real
  bare-hex digest; fixed to `^[0-9a-f]{64}$`, prefixed digests rejected, and a test round-trips the exact file
  `probe.py` writes. `:455`: "T19 (the warm-up comparison) and T45 (`schemas/model-pins.schema.json`, AM-80) read the
  Interfaces section." `docs/PROJECT_HISTORY.md:109`: "The loader accepts the digest format the probe writes and a test
  pins the exact file shape".
- **Erratum 107** (proposed, `SESSION_STATE.md:949-958`, verbatim start): "SA:598 and SA:768 (`data/model-pins.json`):
  the file stays the generation model's (T02, T19); the embedding model's pin is `data/embedding-pins.json` (`{model,
  digest, dimension, ollama_version, probed_at}`, …), verified against the digest `/api/tags` reports (AM-31 names
  `/api/show`, which carries none, as T19's note found for qwen3:8b), by `scripts/skeleton.py embed` before it writes
  … and by mcp-read on every vector call. … A mismatch makes mcp-read answer `UNSUPPORTED_MODE`. A pin that is
  unreadable or malformed answers the same way as a missing one …"
- **Erratum 108** (proposed, `SESSION_STATE.md:959-962`): mcp-read → Ollama "`/api/tags` and `/api/embed` with the
  embedding model only, never generation … The call is not a `model_permit` holder".
- **Erratum 50** (`SESSION_STATE.md:387-388`) and **49** (`:385-386`): the permit's shape and no sweeper permit work.
- **Erratum 57** (`SESSION_STATE.md:403-406`): renewal failure cancels effects, revokes handles, hands the job back.
- **Erratum 65** (`SESSION_STATE.md:495-497`): "`_append_event` refuses (OC006) a payload key outside the event
  schema's thirteen …; `event_rules_ok` mirrors both".
- **Erratum 8** (`SESSION_STATE.md:172`): FAILED via `transition_run` carries no reason; the `run.failed` message says
  why. **Erratum 13** (`:207`): `transition_run` takes a detail `jsonb`; `freeze_proposal` takes the stored bytes.
- **Erratum 3** (Plan C, `tasks.json:409` T07 note): `mode=vector` is the SQL value; the visible `retrieval_mode` is
  `vector_exact`; `routing.py:360-362` repeats it.
- **T44's proposed AM-31 erratum** (`tasks.json:360`): loopback bind primary, scoped firewall fallback; owner step 10
  open (`SESSION_STATE.md:1545`).
- **Plan D review M16** (`docs/reviews/plan-review-d-2026-10-08.md:396-397`): "`freeze_allowed(intent)` (SA:453) is not
  called. `MODEL_MODE` silently defaults to `fake` when unset (P:4849; R130 spirit) — require it." Today the worker
  requires it (`main.py:143`) and `scripts/skeleton.py:435` sets `fake` for the dev skeleton.
- **Plan H ruling 12** (`docs/reviews/plan-review-h-2026-10-15.md:110-115`): permit "ttl = 65 s (60 s model attempt +
  5 s). Release in its own transaction … on completion or cancellation; the TTL is the backstop. The release rule "hold
  until /api/ps idle" waits on T02's measurement and is T19's (debt line)."
- **Plan H final review** (`docs/reviews/plan-h-final-review-2026-10-15.md:139-145`, `:266`, `:277`) as in §1.5.
- **Plan L rulings 13-14** (`docs/reviews/plan-review-l-2026-10-17.md:101-108`) as in §1.5.
- **Plan C review** (`docs/reviews/plan-review-c-2026-10-08.md:322`, `:376`): the `model_summary` rule kept verbatim
  ("model_summary ⇒ type const explanation.ready and a closed payload {message (required), evidence_refs}"); `:378`
  "run-manifest rule. `if model_route not const fake then model_digest type string`."
- **Plan E review** (`docs/reviews/plan-review-e-2026-10-08.md:1880-1891`): SQL and Python both refuse
  `explanation.ready` with `evidence_refs [1, ""]`, both accept `["a:v1:s"]`.
- **Round-2 review** (`docs/reviews/plan-review-2026-10-06.md:112`): "The probe **cannot justify the 90% gate in
  AM-31.** Use the post-repair valid rate as a recorded measurement plus an owner decision, not a fixed gate." (SA:620
  is the result.)
- **Round-4 E2** (`docs/reviews/plan-review-r4-2026-10-06.md:39`): the probe uses the starters "at their MANIFEST
  hashes, validated against 1.0 `model-draft.schem…`".
- **Round-5 H6/must-show** (`docs/reviews/plan-review-r5-2026-10-06.md:49`, `:77`): "There is no run manifest …";
  must-show "(3) sealed-holdout eval with a run manifest; (4) an injected document cannot add authorit…".
- **Round-6 B4** (`docs/reviews/plan-review-r6-2026-10-06.md:28`): "`data/model-pins.json` (model, digest,
  ollama_version, probe date), written by T02; the warm-up check is owned by T19 with a requirement."
- **Plan G** (`docs/reviews/plan-review-g-2026-10-10.md:319`, `:1279`): "`TODO(T19)` and `TODO(T27)` are ownership
  markers."
- **Proposed errata outstanding**: 1-113 (Plans C-O; `SESSION_STATE.md:1575`); the latest are 112-113 (Plan O,
  `SESSION_STATE.md:1022-1031`); 114 is decided. **New errata continue at 115.**
- `handoff/BUILD_BACKLOG.md:122-123` (T19 unchecked with note 1); `STATUS.md:157`, `:189`, `:321`, `:390` (§1.3, §1.5).

---

## 5. Open questions the planner must rule on

1. **The generator interface and where it lives.** Facts: BS:437 names `generate(request_context, evidence_bundle,
   policy_metadata) -> ModelDraft`; today's `DraftGenerator.generate(request, evidence)` has two arguments
   (`drafting.py:48`); SA:379 puts the factory "in the worker"; AM-01 SA:75 "`worker/`: … LangChain draft node", SA:81
   `core/` is a shared library; SA:47 puts prompts in `core/prompts/`; T25 (conditions B and C) and `grading.py` in core
   will consume drafts; BS:197's `adapters/models/` layout is the 1.0 single-package layout. Options: keep the protocol
   in `ops_worker.drafting` and add `QwenDraftGenerator` beside the fake; move the protocol, prompts and validation to
   `ops_core` with the ChatOllama adapter in the worker; or all in core (then `ops-core` gains langchain dependencies
   every service installs). Also open: whether `DraftRequest` gains the interval/alerts/status the template's payload
   names (`incident-draft-v1.md:17-22`) or stays `asset_id`/`text`/`start_at`/`end_at`, and what `policy_metadata` is.

2. **How the router is configured and how "no silent fallback" is enforced.** Facts: SA:379 "from `MODEL_MODE` and
   policy"; BS:441 spells the real mode `ollama`; `ModelRoute` values are `fake` and `qwen3:8b`; `make_generator`
   refuses anything else and `test_model_router_has_one_route_and_no_fallback` asserts `"qwen3:8b"` and `"ollama"` are
   refused (`tests/plan_d/test_worker.py:33`); `MODEL_MODE` is required by the worker, defaulted to `fake` by
   `skeleton.py:435`, `deterministic` in the helm template; "future named model" is not an enum value (Plan C review
   `:134`); `schemas/route.schema.json` and `run-manifest.schema.json` enumerate only `fake`, `qwen3:8b`. Options: the
   `MODEL_MODE` value equals the route value (`qwen3:8b`) vs a mode (`ollama`) plus a model name; where "policy" lives
   (a table in `core/routing.py` like `ADMISSION_RULES`, or code); whether a run records the route chosen at startup or
   per run; what proves no fallback (a test that a failing real route never yields a fake draft; the fake's limitation
   text; R041's "remove real model or block endpoint"); whether the skeleton default stays `fake`; whether "future named
   model" gets an enum slot now or a schema change later.

3. **The qwen3:8b pin format and the digest source.** Facts: `ModelPins` is `{model, digest, ollama_version,
   probed_at}` bare hex (`model_pins.py:26-35`) and matches `probe.py`'s output; `EmbeddingPins` adds `dimension`;
   `/api/show` carried no digest for either model (T19 note 1, `plan-review-n:38`); `/api/tags` lists qwen3:8b
   `500a1f06…8b41`; T18's `OllamaEmbedder.installed_digest`/`verify` is the existing `/api/tags` check
   (`embeddings.py:191-220`), as erratum 107 proposed for the embedding pin; `data/model-pins.json` is written only by
   the probe and now exists uncommitted with `/api/tags`'s digest and `probed_at` `…+00:00` (§3.9). Options: `/api/tags` (an erratum on SA:598's "`/api/show`", from 115),
   `/api/show` for other fields (e.g. parameters) plus `/api/tags` for the digest, or both; reuse/extract the embedder's
   HTTP client vs a separate generation-side client; whether `ollama_version` mismatch also fails closed (SA:587 "Record
   the version actually used"); `probed_at` zero-offset (the loader accepts any aware offset, the schema only `Z` or
   `+00:00`); what the worker does when the file is absent or malformed with `MODEL_MODE=fake` (today never read) vs
   the real route.

4. **The warm-up check: timing and failure mode.** Facts: SA:597 "at startup, before it accepts drafting jobs", "with
   `keep_alive`"; cold load took 53 s against the 60 s timeout (SA:597), and the 2026-10-24 probe's cold call timed out at 60 s (§3.9); R127 "Worker start with a mismatching digest …
   fails closed; matching digest proceeds"; the worker today asserts relations at startup and exits on failure
   (`main.py:153-154`); readiness is `/health/ready` (`main.py:116-125`); the poll loop also runs `execute` jobs that
   need no model; the warm-up is a model call (permit holder? SA:203 governs "global model concurrency"); `keep_alive`
   value unspecified; Ollama may restart and change the model after startup. Options: digest check and warm-up before
   the poll loop starts, process exits non-zero on mismatch/unreachable; or readiness 503 and no `investigate` claims
   until warm; re-check per draft or per interval; whether the warm-up takes the model permit and counts against
   anything; timeout for the warm-up itself; what the fake route does (skip both checks, or still read the pin).

5. **Prompt versioning and storage.** Facts: SA:47 `core/prompts/` once T19 promotes them, `handoff/prompts/` stays
   the starters; BS:447 lists what prompts must instruct; the starters are pinned by sha256 in `probe.py:63-66` and
   SA:607-608; the starter files are Markdown templates with a status line, a system message and a `RENDER_…` payload
   (`incident-draft-v1.md:1-26`), while the probe sends the whole file as the system message and a `{"request",
   "evidence"}` user payload (with no evidence IDs; the probe diagnosis ties the drafts' bundle-key `evidence_refs` to it, §3.9); `PROMPT_VERSION = "incident-draft-v1"` is a hashed proposal field; BS:572 asks for a
   "prompt hash" per run; the CR/BOM checker covers `handoff/prompts` but not `core/`; SA:660 "prompt-version family";
   AM-50 forbids tuning before the (now optional) holdout. Options: promote byte-identical copies (same hashes) vs
   extracted system/payload parts (new hashes, new version string); file format (Markdown, `.txt`, LangChain
   `ChatPromptTemplate` in code); naming `incident-draft-v1`/`schema-repair-v1` vs a new `-v2` if the text changes;
   a test pinning each runtime prompt's sha256; whether the prompt hash enters the manifest (not in AM-80's six fields)
   or only the version; package data for `ops-core` if prompts live in `core/`.

6. **Structural validation, citation membership and the repair bound.** Facts: BS:451's list; `ModelDraft` already
   refuses extra keys, sizes, types, enums, duplicate refs, a question on non-abstain (`contracts.py:319-342`);
   `grading.check_schema` requires both JSON Schema and `ModelDraft` (`grading.py:272-286`); no membership check
   exists in the worker (`proposals.py:73`, `:89` raise `KeyError`); `with_structured_output(..., include_raw=True)`
   gives `parsed`/`parsing_error`; thinking is detected by tag or `reasoning_content` (`probe_stats.py:39-40`, `:61-63`);
   R040 "exhausts one repair within remaining budget; no incident"; the repair starter's inputs (`schema-repair-v1.md:7`)
   and the probe's repair payload (`probe.py:222-227`); measured: first-pass and post-repair schema validity 5/60 each, the failures a `question` on non-abstain drafts that Ollama's `format` does not prevent (`if`/`then`/`else` unenforced) and the repair repeated (§3.9); BS:454 "preserve diagnostic metadata"; SA:496 forbids storing
   the draft payload in `drafts`, checkpoints or events. Options: which failures trigger the repair (parse error,
   schema/model rejection, membership failure, thinking present, authority field) and which fail at once; whether the
   membership check is "offered to this run" only or also tenant-returnable; whether `supersedes_run_id` or other
   authority keys are named in repair feedback; how "safe validation feedback" is produced (rule names, jsonschema
   messages truncated to 10, or pydantic error locations); the remaining-budget rule for the second attempt (BS:555 90 s
   total, 60 s per attempt clipped); what a failed repair writes (a `drafts` row with `validated=false`? a `run.failed`
   message? a log line) and the run's end state (`DRAFTING → FAILED`, SA:451); conflicting-pair and injected-text
   handling as model behaviour vs code rules.

7. **The model permit around a call.** Facts: today one permit hold wraps one `generate` call (`handlers.py:161-162`);
   TTL 65 s = one 60 s attempt + 5 s (`permit.py:22`); two attempts (first pass + repair) can take 120 s; SA:205's
   release rule depends on T02's cancel row: the uncommitted report measures the `ok` call after a cancel at 0.15 s with
   `/api/ps` still listing the model loaded, and records "release on cancel — PROVISIONAL" (§3.9); the cold call
   exceeded 60 s; `release_model_permit` happens in `finally`, including after a lost lease; the heartbeat cancels the
   model call as a lease effect (`lease.py:133`). Options: hold the permit across both attempts (TTL raised, or renewed)
   vs per attempt (re-acquire for the repair); whether the warm-up holds it; adopt the provisional "release on cancel"
   (today's behaviour) or "hold until `/api/ps` idle or the 60 s cap" (the two options printed at `probe.py:366`);
   whether the worker polls `/api/ps` at all; whether `/api/ps` listing a loaded model counts as "not idle" (it lists
   loaded models, `reports/model-probe-qwen3-8b.md:21`); who confirms the rule (T02 DoD 2; the owner confirms or
   reverses the provisional line).

8. **Timeouts and error mapping.** Facts: SA:596/BS:443 60 s per attempt; BS:555 90 s compute total, the heartbeat's
   `OPS_COMPUTE_BUDGET_SECONDS` 90 counts the lease hold from the claim, including the permit wait (`SESSION_STATE.md:
   1171-1173`); `probe.py` uses `asyncio.wait_for(…, 60)`; `OllamaEmbedder` maps errors to `Unavailable` (retryable) /
   `PinMismatch` / `Malformed`; today any generator exception fails the run "drafting failed" and closes the job
   (`handlers.py:149-153`, `tests/e2e/test_worker_live.py:202`); BS:562 do not retry validation; BS:564/BS:680 "Model
   unavailable: retain request/evidence and offer authorized manual search/proposal workflow", "bounded retries"; R061
   and R062 are T29's; templated failure messages (BS:516). Options: wait_for vs the ChatOllama/HTTP client timeout vs
   both; Ollama unreachable mid-run → FAILED (with which message) vs job re-queue with a bound (T22/T29 own bounded
   retries); a pin mismatch discovered mid-run; timeout of the first attempt → repair or fail (the probe does not repair
   an errored call); an exception taxonomy (`ModelUnavailable`, `ModelOutputInvalid`, …) and which are "retryable"; how
   "retain request/evidence" is met when the run is FAILED.

9. **The run manifest's storage.** Facts: AM-80 fixes the six fields and the schema; `RunManifest` exists and is built
   in `build_proposal` but discarded (`proposals.py:100-108`); no table, column or file holds it (§3.5); T25 "reads each
   run's manifest" (`tasks.json:1045`); runs that end ANSWERED, INSUFFICIENT_EVIDENCE or FAILED also need a route record
   for R130 and T25; `explanation.ready`'s payload is closed (schema, code, SQL); BS:572 adds commit, workflow version,
   prompt hash, tool schema version; BS:342 `workflow_version` per run (not stored either); AM-20.2 grants and AM-20.5
   RLS lists would need a row for any new table; the dev database is at 0013. Options: a new `app.run_manifests` table
   (revision 0014, worker `ins, sel`, api `sel`?, RLS, written in the draft unit or at RETRIEVING) vs columns on `runs`
   (worker column grants change) vs `drafts` columns vs a JSON file under `reports/` vs inside an event payload (needs a
   schema/PAYLOAD_KEYS/SQL change); when it is written (before the model call, so a failed draft still has one); whether
   it is immutable (one per run, or per revision); whether `retrieval_mode` stays `lexical` until T20/T25.

10. **What `explanation.ready` gains.** Facts: T19 instructions "records the route in explanation.ready"; SA:379 "the
    choice, model digest and prompt version are written to … the `explanation.ready` event"; today the route and prompt
    version appear only inside `message` text (`handlers.py:197-198`); the payload is closed to `message` and
    `evidence_refs` in `schemas/event.schema.json:250-275`, `outcomes.py:242-256` and `_append_event` SQL
    (`0008:171-180`); a `model_summary` event may carry no `status` (SA:322); the event is emitted in the same unit as
    `freeze_proposal`, only on the proposal path. Options: keep the route in the message text (no contract change);
    add keys (e.g. `model_route`, `model_digest`, `prompt_version`) to the summary payload (schema regeneration,
    `PAYLOAD_KEYS`, a new `_append_event` revision, negative probes in `schemas/examples/index.json`); emit it also for
    answer/abstain drafts; whether the summary `message` is the model's `summary` text (untrusted, R055/R035) or a
    template.

11. **Which draft kinds T19 handles and where the run goes.** Facts: the fake always returns `proposal`; the real model
    can return `answer`, `abstain`, or `abstain` + `question`; SA:137, SA:147, SA:153 and SA:451 define DRAFTING →
    AWAITING_INPUT / ANSWERED / INSUFFICIENT_EVIDENCE; the ANSWERED path, `resume_input` and the graph router are T20's
    (`SESSION_STATE.md:1110-1113`; R114 is T20's); `freeze_allowed` fails `answer_only` runs today; the dev set expects
    29 abstains and 12 answers out of 60. Options: T19 returns a validated draft of any kind and T20 routes it; or T19
    adds minimal handling in `handlers.investigate` (e.g. abstain → INSUFFICIENT_EVIDENCE via `transition_run`) until
    T20; or non-proposal kinds fail the run until T20; whether an `answer` on an `investigate` run, or a `proposal` on an
    `answer_only` run, is a validation failure in T19.

12. **Tests without a model, and live tests against qwen3:8b.** Facts: CI has no Ollama or database; the fake route is
    the "reproducible application-test profile" (BS:441); BS:590 separates fake control tests from LangChain/Ollama
    structured generation; BS:593 real-model evaluations are "not merged into unit-test pass counts"; live tests run only
    with `OPS_LIVE=1` under `check.py --profile test`, which needs the dev stack; `tests/plan_b/live/test_ollama_bridge.py`
    is the only Ollama test; R037 asks for a traced ChatOllama request with "real output, versions and hardware"; T19
    DoD 1 "Recorded real-model run evidence (digest, params, outputs)"; T31 plans a separate trusted workflow for
    real-model checks. Options: unit tests with a scripted chat model / fake HTTP transport for ChatOllama (no network),
    including malformed JSON, thinking tags, timeouts and repair exhaustion; a separate marker or environment flag for
    real-model tests (not counted in the gates), or an evidence script under `scripts/` writing `reports/model/…`;
    whether `check.py --profile test` ever runs the real model; where real-model evidence lives (`reports/…`) and how
    `tests/plan_p/` is added to `testpaths`.

13. **Dependency additions.** Facts: SA:582 pins `langchain-ollama` 1.1.0; the probe runs it in an isolated
    environment, not the lockfile (its freeze: `langchain-core==1.7.0`, `langchain-protocol==0.0.20`, `ollama==0.6.3`, `httpx==0.28.1`, `pydantic==2.14.1`, §3.9); `uv.lock` has no langchain or ollama package (§3.6); CI uses `uv sync --locked`; mypy
    is strict over `worker/src` with per-package overrides only for untyped packages; the workspace uses `httpx2`
    (`core/pyproject.toml`). Options: add `langchain-ollama==1.1.0` (and `langchain-core`) to `worker/pyproject.toml`
    (or `core`) and re-lock; whether the transitive set it brings (to be read from the lock at `uv lock` time) is
    acceptable beside `httpx2`; whether a newer langchain-ollama than SA:582's is allowed (AM-30 "Versions observed on
    2026-10-06"); mypy overrides if the packages ship no `py.typed`; whether the probe's isolated freeze and the
    workspace lock must agree.

14. **R036: the injected-source proof.** Facts: the injected documents are `ALPHA-VENDOR-PORTAL` and
    `BETA-CONTRACTOR-MEMO` (§3.8), returned like any other section; the model never sees a tool (SA:207); `ModelDraft`
    has no authority fields; the draft becomes a proposal only through `freeze_proposal`, whose payload fields are fixed
    (`action="create_incident"`, `destination="synthetic-incidents"` are set by code, `proposals.py:80-81`); R036's
    expected evidence is "no permission/action boundary changes"; DoD 2 "Injected source cannot add tools or authority";
    four dev cases are `injected`. Options: a code-level test (the generator receives injected text; whatever it
    returns, no tool, grant, role or destination changes and authority keys fail validation) with the fake and a
    scripted adversarial model; plus a recorded real-model run over the injected sections; whether it must also prove
    the model's text does not reach `explanation.ready` unescaped (R055 is T26's).

15. **Thinking leakage at runtime.** Facts: SA:596 `reasoning=False` maps to `think:false`; SA:620 "If thinking cannot
    be disabled, the probe fails"; the probe counts a `<think>` tag or `reasoning_content` as a failure "never stripped"
    (`probe_stats.py:4-5`, `:39-40`); BS:460 reasoning "disabled by default, separately classified and redacted if ever
    enabled"; the reference adapter ignores the thinking field (`reference/…/models.py:63`); R039 "raw reasoning stays
    off". Options: a draft whose raw text or metadata shows thinking is invalid (repairable or a hard failure); thinking
    is discarded silently; it is logged (redacted) as diagnostic metadata; whether R039 is evidenced by a test that a
    draft summary claiming success creates no `action.*` event and no status.

16. **The model-hint debt.** Facts: SA:375 makes model-assisted intent classification optional; the admission router
    takes `hint` and the API passes `None` (`api/src/ops_api/store.py:416`, `routing.py:210`); the debt line names T19
    (`SESSION_STATE.md:1108`); a hint call would be a second model use at admission (permit, latency, the API process
    has no model dependency). Options: implement a hint producer in T19; close the debt as "not built in v1" (the hint
    row stays, tested); move it to a later task; and whether the `TODO(T19)` markers are re-owned.

17. **The worker's Ollama URL and network guard.** Facts: `OPS_OLLAMA_URL` (`settings.Urls.ollama`, default loopback)
    serves mcp-read and `embed`; `docs/runbooks/dev-topology.md:71` "the worker's generation path (T19) chooses its
    own"; the probe hard-codes loopback (`probe.py:53`); the reference restricts hosts and refuses redirects
    (`models.py:37-38`, `:54-55`); containers are T30's; SA:599-601 network exposure is the owner's. Options: reuse
    `OPS_OLLAMA_URL`; a separate `OPS_MODEL_URL`; host allowlist or loopback check; whether the worker and mcp-read must
    point at the same Ollama (the embedding pin and the model pin both record one `ollama_version`).

18. **Owner steps that bound T19's DoD.** Facts: the probe has now run and its three outputs exist uncommitted (§3.9),
    with a "proceed — PROVISIONAL" line for the owner to confirm or reverse; T02 is still DONE_PENDING_OWNER in the
    committed `tasks.json:236`; T02 DoD 3 "Owner decision on proceeding recorded"; R081 is `NOT_RUN` in the committed
    matrix; the measured first-pass and post-repair schema validity is 5/60 with the probe's payload (§3.9, and its
    diagnosis: `question` on non-abstain drafts, no evidence IDs in the payload); Ollama 0.40.4 vs SA:587's
    0.33.3 is undecided; T44 step 10 is partly open and the owner chose to go ahead past it (`SESSION_STATE.md:1450-1452`);
    T19 DoD 1 needs recorded real-model evidence; the classifier refuses agent-run owner actions (memory note). Options:
    T19 builds and unit-tests everything, then stays `DONE_PENDING_OWNER` until the owner confirms the probe decisions
    and a recorded real run exists; who commits the probe outputs and with which T02/R081 record (the probe is "the
    owner runs this once, by hand", `probe.py:5`); and what the worker does on the real route if the pin is missing
    (fail closed per SA:598).

19. **Requirement evidence and statuses.** Facts: seven requirements, all `NOT_RUN`; past plans recorded unit tests as
    `RECORDED_LOCALLY` and live tests as `RECORDED_LOCALLY_LIVE`; R130 is co-owned with T25 ("B and C evaluation
    conditions show identical routes"); R036 is listed under M06 in `ACCEPTANCE.md:42` and M07 in the matrix; R040's
    "no incident" and R041's "clear failure/manual path" touch T21 (manual proposals) and T29 (outages). Options: which
    rows T19 can flip and to what (e.g. R127/R041/R040 by unit + live tests, R037 only with a recorded real run, R130
    "subject to" T25's half), notes naming the evidence paths, and any erratum (from 115) on R036's milestone, R041's
    "manual path", SA:598's endpoint, SA:610's "1.0" schema, SA:203-205's release rule or SA:609/SA:704's stale T03
    wording.

20. **The records.** Facts: Plan O's close-out pattern (`SESSION_STATE.md`, `STATUS.md`, `docs/PROJECT_HISTORY.md`, the
    plan file, `handoff/BUILD_BACKLOG.md`, `handoff/acceptance-matrix.json`, `handoff/tasks.json`); the debt list is
    committed before coding ([R6-B7]); `SESSION_STATE.md:13-15`, `:1575` and `STATUS.md:390` still say T19 waits on the
    seal; `tasks.json:3` `current_milestone` is `M06` while T19 is M07 and T41 (M06) is now optional; the last history
    entry is "34. What the process taught" (`docs/PROJECT_HISTORY.md:1093`; erratum 114 inserted its own entry as 33
    and renumbered that one). Open: the
    Plan P debt list, the T19 close-out note, the milestone line, the stale "next" records and the PROJECT_HISTORY
    entry.

---

## 6. Glossary of exact names

- **Task/requirements:** `T19` (M07, "Async LangChain ChatOllama DraftGenerator"); `R036`, `R037`, `R039`, `R040`,
  `R041`, `R127`, `R130`. Neighbours: `T02` (probe, R081), `T03` (optional holdout), `T07`, `T17`, `T44` (R101), `T20`
  (R038, R114, R129), `T21` (R057), `T23` (R111), `T25` (R130, R073), `T26` (R035, R055), `T28` (R058, R059), `T29`
  (R061, R062), `T30` (R065), `T31`, `T37` (R076), `T38`; `R004`, `R028`, `R083`, `R088`, `R113`.
- **Spec anchors:** AM-31 (SA:593-620), AM-16 model router (SA:379), AM-12 permit (SA:203-205) and async (SA:201),
  AM-14 (SA:319, SA:322), AM-20.2 (SA:421, SA:432), AM-20.3 (SA:451-453), AM-20.4 (SA:496), AM-30 (SA:582, SA:587),
  AM-80 (SA:762, SA:768, SA:770), AM-00 §12 (SA:47); BUILD_SPEC §12 (BS:433-460), §17 (BS:549-566), §18 (BS:572).
- **Worker code:** `ops_worker.drafting` (`PROMPT_VERSION = "incident-draft-v1"`, `WORKFLOW_VERSION =
  "investigation-v1"`, `DraftRequest`, `EvidenceItem`, `DraftGenerator`, `ModelRouteError`, `FakeDraftGenerator`,
  `make_generator`); `ops_worker.proposals` (`EXPIRY`, `Frozen`, `evidence_from_search`, `build_proposal`);
  `ops_worker.handlers` (`Deps`, `investigate`, `_draft_and_freeze`, `_fail`, `_event`, `INTERRUPTED`, `QUERY_CHARS`);
  `ops_worker.permit` (`PERMIT_TTL_SECONDS = 65`, `model_permit`, `backoff`); `ops_worker.main` (`_main`,
  `health_app`, `run_forever`); `ops_worker.heartbeat` (`Heartbeat`).
- **Core code:** `ops_core.contracts` (`ModelDraft`, `ProposalPayload`, `AUTHORITY_FIELDS`, `load`);
  `ops_core.routing` (`ModelRoute.FAKE`, `ModelRoute.QWEN3_8B`, `RunManifest`, `AdmissionFacts.hint`);
  `ops_core.model_pins` (`ModelPins`, `ModelPinsError`, `load_model_pins`, `EmbeddingPins`, `load_embedding_pins`);
  `ops_core.embeddings` (`OllamaEmbedder`, `installed_digest`, `verify`, `Unavailable`, `PinMismatch`, `Malformed`,
  `TIMEOUT_SECONDS`); `ops_core.grading` (`check_schema`, `check_citation_validity`, `check_citation_sufficiency`,
  `check_abstention`, `Output`, `DRAFT_SCHEMA`); `ops_core.outcomes` (`EventType.EXPLANATION_READY`,
  `EventSource.MODEL_SUMMARY`, `PAYLOAD_KEYS`, `event_rules_ok`); `ops_core.persistence` (`take_model_permit`,
  `release_model_permit`, `append_event`, `transition_run`, `freeze_proposal`, `fenced`, `assert_relation`);
  `ops_core.states.freeze_allowed`; `ops_core.lease.Lease.effect`; `ops_core.settings` (`env`, `urls().ollama`,
  `leases()`).
- **Settings:** `MODEL_MODE` (worker required; skeleton default `fake`), `OPS_OLLAMA_URL` (default
  `http://127.0.0.1:11434`), `OLLAMA_BASE_URL_HOST`, `OLLAMA_BASE_URL_CONTAINER`, `OPS_COMPUTE_BUDGET_SECONDS` (90),
  `OPS_LEASE_SECONDS` (30), `OPS_HEARTBEAT_SECONDS` (10), `OPS_WORKER_HEALTH_PORT` (8070).
- **Database:** `app.model_permit(slot, holder, run_id, leased_until)` (revision `0007_leases_fences`, one slot);
  `app.drafts(id, tenant_id, run_id, draft_sha256, validated, kind, created_at)`; `app.runs`; `_append_event`
  (`0008_journal_outbox`); latest revision `0013_embeddings`; job types `investigate`, `resume_input`, `execute`,
  `recover`, `expire_proposals`, `sync_memberships`, `sweep_wakeups`, `deliver_outbox`.
- **Schemas:** `schemas/model-draft.schema.json` (`…:model-draft:1`, sha256 `9fe09e07…c8a7`),
  `schemas/run-manifest.schema.json`, `schemas/route.schema.json`, `schemas/model-pins.schema.json`,
  `schemas/embedding-pins.schema.json`, `schemas/event.schema.json`; generator `scripts/build_schemas.py`.
- **Prompts:** `handoff/prompts/incident-draft-v1.md` (sha256 `e3c26da3…a942`), `handoff/prompts/schema-repair-v1.md`
  (sha256 `8b6658eb…c343`); target directory `core/prompts/` (SA:47, absent).
- **Probe:** `scripts/probe.py` (`MODEL`, `OLLAMA`, `TIMEOUT_S = 60`, `EXPECTED`, `model_digest`, `run_probe`,
  `render_report`, `main`); `scripts/probe_stats.py` (`classify_output`, `classify_structured`, `has_thinking`,
  `wilson`, `summarize`); outputs `reports/model-probe-qwen3-8b.md`, `reports/model-probe-freeze.txt`,
  `data/model-pins.json` (untracked when this sheet was committed, §3.9); `evals/probe/inputs.jsonl` (60 inputs, `PR-001`…).
- **Pins/digests:** `data/embedding-pins.json` (`nomic-embed-text`, `0a109f42…e59f`, 768, Ollama 0.40.4); qwen3:8b
  `/api/tags` digest `500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41` (in the untracked `data/model-pins.json`);
  Ollama endpoints `/api/tags`, `/api/show`, `/api/version`, `/api/ps`, `/api/generate`, `/api/embed`.
- **Library names (as used in `probe.py`):** `langchain_ollama.ChatOllama(model, base_url, reasoning=False,
  num_ctx=16384, num_predict=1000, temperature=0)`, `.with_structured_output(schema, method="json_schema",
  include_raw=True)`, `.ainvoke`, `langchain_core.messages.SystemMessage`/`HumanMessage`, result keys `raw`, `parsed`,
  `parsing_error`, `additional_kwargs["reasoning_content"]`; `langchain-ollama==1.1.0` (SA:582).
- **Corpus:** `corpus-1`; injected `ALPHA-VENDOR-PORTAL`, `BETA-CONTRACTOR-MEMO`; conflicting `ALPHA-COMPRESSOR-TRIP`,
  `ALPHA-COMPRESSOR-COOLDOWN`; evidence ID `<DOCUMENT_ID>:v<version>:<section>`.
- **States/events:** `DRAFTING`, `AWAITING_INPUT`, `ANSWERED`, `INSUFFICIENT_EVIDENCE`, `FAILED`,
  `AWAITING_APPROVAL`; `explanation.ready` (source `model_summary`), `run.failed`, `tool.started`, `tool.completed`,
  `proposal.ready`; draft kinds `proposal`, `answer`, `abstain` (+ `question`).
- **Tests:** `tests/plan_d/test_worker.py`, `tests/plan_c/test_jobs_routes_outcomes.py`, `tests/plan_b/test_model_pins.py`,
  `tests/plan_h/test_permit.py`, `tests/plan_h/test_worker_units.py`, `tests/plan_a/test_probe_stats.py`,
  `tests/plan_o/test_grading.py`, `tests/e2e/test_worker_live.py`, `tests/e2e/test_heartbeat_live.py`,
  `tests/e2e/test_r105_walking_skeleton.py`, `tests/plan_b/live/test_ollama_bridge.py`; next free directory
  `tests/plan_p/` (not in `testpaths`).
- **Gates:** `uv run python scripts/check.py` (1540 passed, 219 skipped at `d37f30c`, per the brief), `… --profile
  test` (1737 passed, 21 skipped, Plan O), `uv run python -I scripts/verify_handoff.py --reference-code --manifest
  --contracts` (exit 0). Next erratum: 115.

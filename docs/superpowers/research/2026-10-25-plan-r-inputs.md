# Plan R inputs: T21 (proposals, decisions, manual proposals, feedback and the final grant) — fact sheet

Prepared 2026-10-25 on branch `plan-r` at `84eaee5` (= `plan-q`, PR #16 against `plan-p`, PR #15 against `main`; the
working tree was clean). Read-only on the repository except this file. Facts only, no design. Citations: `SA:<line>` =
`SPEC_AMENDMENTS.md`, `BS:<line>` = `BUILD_SPEC.md` (line numbers as of `84eaee5`); the amendments win wherever the two
conflict. Repository files are cited as `path:line`. Nothing was run against a database, Keycloak, Ollama or any
service for this sheet, no network connection was made, no gate was re-run, and no secret, token or `.env` value was
opened. Two read-only helper scripts (in the session scratchpad, run as `uv run python -I <path> < /dev/null`) printed
the acceptance-matrix rows for the chosen requirement ids and for keyword hits with their line spans, and the context
around a pattern in named files (skipping any path matching `*holdout*`, `*seal*` or `*.sha256`); every other fact is
read from the files.

**Holdout custody.** No holdout case file, label or seal was opened, read, hashed or listed. Paths matching
`*holdout*`, `*seal*` or `*.sha256` skipped by name only: `evals/HOLDOUT.md` and `evals/holdout-case.schema.json`
(allowed, not needed, not opened), `scripts/seal.py` (named in `SESSION_STATE.md:1675`; not opened). Every `git grep`
carried `':!*holdout*' ':!*seal*' ':!*.sha256'`, and every directory listing was piped through `grep -v -i -E
'holdout|seal|\.sha256$'`. **Process slip:** four commands were scoped by explicit directory or glob without the
exclusion: `grep -n -E 'create_revision|…' migrations/app/versions/*.py`, `grep -n 'CREATE TABLE|asset|…'
migrations/incident/versions/*.py`, `grep -rn 'build_proposal|…' worker/src core/src/ops_core/contracts.py
core/src/ops_core/canonical.py`, and `ls incident-sim/src/*/`. Every output line came from a visible non-matching path
(`0002_roles_grants_rls.py`, `incident/versions/0001_walking_skeleton.py`, `worker/src/ops_worker/…` and its
`__pycache__`, and `incident-sim`'s five entries); none named or came from a `*holdout*`, `*seal*` or `*.sha256` path.

Note on line numbers: AM-10 SA:116-162 (ESCALATED and the guard SA:118-122, ABANDONED_UNVERIFIED and the guard's
release SA:124-130, the table SA:132-143, active states SA:145, refusals SA:150, `state_version` SA:151, reasons SA:152,
requester fields SA:154, clock SA:156-162); AM-11 SA:164-168; AM-12 lock order SA:186-191; AM-13 SA:220-299 (grant
SA:228, `mark_sent` SA:229-232, cancellation SA:246-248, transport timeout SA:250-256, asset guard SA:282-289,
defaults SA:291-299); AM-14 SA:301-325 (`action.granted` SA:311, feedback SA:318, SA:325); AM-15 job table SA:340-346;
AM-16 SA:360-381; AM-20.2 SA:406-442 (`runs` SA:415, `proposals`/`decisions`/`execution_grant` SA:422-424, `feedback`
SA:428); AM-20.3 SA:444-490 (`create_run` SA:450, `freeze_proposal` SA:453, `record_decision` SA:454, `create_revision`
SA:455, `create_manual_proposal` SA:456, `expire_proposal` SA:457, `request_cancel` SA:458, `grant_execution` SA:462,
performers SA:476-490); AM-20.4 SA:492-506; AM-20.5 SA:508-524 (sweeper tenant iteration SA:520); AM-20.7 SA:532-566
(R100 SA:538, R093 SA:539, revocation SA:540-553); AM-40 SA:622-636; AM-50 condition A SA:660; AM-80 SA:743-778 (new
schemas SA:763, error codes SA:764, revision/message SA:769, decision SA:773, proposal SA:778). BUILD_SPEC: BS:29;
BS:121-122; §4 BS:176, BS:178; §6 BS:234-236, BS:243, BS:254-258; §7 BS:264, BS:274-276, BS:280-282, BS:299, BS:301;
§8 BS:317-318, BS:321, BS:324, BS:330, BS:340, BS:342; BS:425; §13 BS:462-478; §15 BS:510, BS:514; §16 BS:532, BS:534;
§17 BS:559, BS:564; BS:684; M08 BS:709.

---

## 1. T21 verbatim, and what touches it

### 1.1 T21 (`handoff/tasks.json:896-936`)

- **id/milestone/title:** `T21` (`:897`), `M08` (`:898`), "Proposals, decisions, manual proposals, feedback and final
  grant" (`:899`).
- **instructions** (`:900`, verbatim): "Per-revision proposal IDs; expected_payload_sha256; first decision wins;
  author-set independence; expiry to BLOCKED_REVIEW; manual-proposal API; feedback endpoint; grant_execution final
  gate with UNIQUE(run_id), proposal/run binding, asset freshness and asset guard."
- **depends_on** (`:901-904`): `["T20", "T11"]`, both `DONE` (T20 `:882`; T11's entry starts `:548`).
- **requirement_ids** (`:905-920`): `R023`, `R043`, `R044`, `R045`, `R046`, `R057`, `R090`, `R092`, `R093`, `R100`,
  `R113`, `R116`, `R120`, `R125`.
- **status** (`:921`): `"PLANNED"`. **external_approval_required** (`:927`): `false`.
- **definition_of_done** (`:922-926`, verbatim):
  1. "Self-approval and reviewer-authored-revision approval denied; opposing/stale decisions 409."
  2. "Revocation or cancellation before grant blocks dispatch; a second grant for a run is impossible."
  3. "Lost-wakeup crash between decision commit and processing recovered by the sweeper."
- **review_notes** (`:928-935`, verbatim):
  1. "Asset guard via pg_advisory_xact_lock(tenant, asset) first in lock order; refusal 409 ASSET_ACTION_UNRESOLVED."
  2. "Revision from BLOCKED_REVIEW requires a free conversation slot (SLOT_OCCUPIED 409)."
  3. "Verify R086's grant-blocking half (membership sync <=60 s)."
  4. "Manual proposals must reference assets/evidence of the caller's tenant (alpha proposal for B22 -> 404, nothing
     written)."
  5. "Refusals move the run to BLOCKED_REVIEW with reason asset_action_unresolved / asset_incident_exists."
  6. "Asset guard per AM-13 (1.3.3): refuse on any unresolved action, and on any committed incident regardless of
     timing unless supersedes_run_id names it; approval card shows the superseded incident."
- Milestone M08 (`tasks.json:97-106`): "Independent review, grant, execution and recovery", `task_ids` `["T21",
  "T22"]`, `"status": "PLANNED"`. `tasks.json:3` `current_milestone` is `"M08"`.
- `handoff/BUILD_BACKLOG.md:132` repeats the task unchecked; `:133-138` repeat the six notes as "*Review note:*".
- `tasks.json:4` status vocabulary: PLANNED, DONE, DONE_PENDING_OWNER; "A proposed erratum awaiting the owner's
  decision does not change a task's status; a task met 'subject to' an erratum stays DONE."
- Sources of the notes: note 1 matches `docs/reviews/plan-review-r3-2026-10-06.md:70` ("**Asset guard needs a shared
  lock**: `pg_advisory_xact_lock(tenant, asset)` placed before `runs` in the lock order. Otherwise two conversations
  can both grant.") and `plan-review-r4-2026-10-06.md:54` ("The advisory lock needs `asset_id NOT NULL`, read before
  locking. Prefer `hashtextextended`. Test that `app_definer` can call `pg_advisory_xact_lock`."); note 3 matches
  `plan-review-r3-2026-10-06.md:66` ("The 'grants blocked ≤60 s' half is tested in T21."); note 4 matches
  `plan-review-r5-2026-10-06.md:71` ("**T21:** manual proposals are tenant-scoped. The guard predicate is 'grant
  exists and attempt unresolved', applied atomically."). `plan-review-r6-2026-10-06.md:50`: "**T21:** 'decisions only
  via `record_decision`' does not stop a compromised api forging approvals: the api supplies the reviewer `sub`.
  Restate H1's claim as 'no role except api can write decisions; api is the identity trust anchor'."

### 1.2 Acceptance rows owned by T21 (`handoff/acceptance-matrix.json`)

All `blocking_for_v1: true`, all `NOT_IMPLEMENTED_OR_NOT_TARGET_VERIFIED` / `NOT_RUN` with `evidence_paths: []`.
Expected evidence verbatim:

- **R023 (:419-433)** `M08`, `durability`, "Reply/approval wakeups cannot be lost"; "Inject crash between
  decision/event/checkpoint/job acknowledgement; sweeper resumes exactly the accepted event."; owners `["T21"]`;
  `ACCEPTANCE.md:29` (as "R023 / M04").
- **R043 (:847-861)** `M08`, `approval`, "Requester cannot approve their own proposal"; "Same identity with both scopes
  submits approval; rejected; another permitted reviewer succeeds."; `["T21"]`; `ACCEPTANCE.md:49`.
- **R044 (:862-876)** `M08`, `approval`, "Approval binds exact immutable revision and expiry"; "Edit content, change
  revision/hash or advance time; old decision cannot authorize changed action."; `["T21"]`; `ACCEPTANCE.md:50`.
- **R045 (:877-891)** `M08`, `approval`, "Final grant checks current authority and evidence"; "Revoke
  requester/reviewer or source before grant transaction; zero destination writes."; `["T21"]`; `ACCEPTANCE.md:51`.
- **R046 (:892-907)** `M08`, `approval`, "Cancellation race is ordered at execution grant"; "Race cancel and grant;
  before grant no dispatch, after grant report actual/unknown outcome without undo claim."; `["T21", "T22"]`;
  `ACCEPTANCE.md:52`.
- **R057 (:1062-1076)** `M08`, `product`, "Manual baseline uses the same approval controls"; "With model unavailable,
  search and manual draft work under identical independent review/write policy."; `["T21"]`; `ACCEPTANCE.md:63`
  (as "R057 / M09").
- **R090 (:1607-1622)** `M08`, `approval`, "At most one execution grant exists per run"; "UNIQUE(run_id); revision
  after grant 409; second grant fails even after abort."; `["T21"]`; source `SPEC_AMENDMENTS.md`.
- **R092 (:1645-1660)** `M08`, `approval`, "Expired proposals reach BLOCKED_REVIEW without a live worker"; "Lazy check
  in decision/grant plus scheduled expiry job with injected DB time."; `["T21"]`.
- **R093 (:1661-1676)** `M08`, `approval`, "No content author may approve the proposal"; "Reviewer-authored revision or
  manual proposal cannot be approved by that reviewer."; `["T21"]`.
- **R100 (:1793-1808)** `M08`, `security`, "A write or recovery handle cannot act on another run's proposal"; "Valid
  handle for run X with a proposal of run Y (any tenant) writes nothing."; `["T21"]`.
- **R113 (:2047-2062)** `M08`, `feedback`, "Feedback is recorded without changing runtime behaviour"; "Feedback
  endpoint stores classified feedback, emits feedback.recorded, alters no prompt/policy/permission."; `["T21"]`.
- **R116 (:2109-2124)** `M08`, `approval`, "Stale asset observations block the grant"; "Asset status older than 5
  minutes at grant -> BLOCKED_REVIEW."; `["T21"]`.
- **R120 (:2173-2189)** milestone `M01`, `domain`, "A conversation never holds two active runs"; "Revision from
  BLOCKED_REVIEW with another active run returns 409 SLOT_OCCUPIED."; owners `["T07", "T21"]`.
- **R125 (:2265-2281)** `M08`, `safety`, "A second incident for the same asset and interval requires an explicit
  supersession"; "Two approved runs on one asset/interval: the second grant is refused (asset_incident_exists)
  whenever a committed incident exists, in any order; it proceeds only when runs.supersedes_run_id, set from the
  requester's structured request, names that run and the reviewer approved the payload that freeze_proposal built from
  it; a draft carrying supersedes_run_id fails validation."; owners `["T21", "T22"]`.
- R081-R131 are matrix-only (`ACCEPTANCE.md:3`), so R090-R125 have no `ACCEPTANCE.md` line. Matrix note
  (`acceptance-matrix.json:3`): `RECORDED_LOCALLY` = the evidence-path tests pass in `scripts/check.py` and CI;
  `RECORDED_LOCALLY_LIVE` = passes against the running dev profile with `OPS_LIVE=1`.

### 1.3 Other rows naming proposals, decisions, approval, expiry, BLOCKED_REVIEW, the guard, supersession or R086

- **R086 (:1520-1541)** T11, `IMPLEMENTED_LOCALLY_VERIFIED` / `RECORDED_LOCALLY_LIVE`, "IdP disable and back-channel
  logout end application authority"; expected: "Disabled user: next decision-class mutation 401, grants blocked within
  60 s; back-channel logout destroys sessions; replayed logout token rejected."; evidence `tests/e2e/test_auth_live.py`,
  `reports/auth/t11-sessions-revocation.txt`, `tests/plan_f/test_api_auth.py`, `tests/plan_f/test_id_and_logout_tokens.py`;
  note (verbatim): "the admin-API half and the sync half are live; the grant-side block through a real
  `grant_execution` call lands with T21 (T11 review note 1)". T11's review note (`tasks.json:570`): "The 'grants
  blocked <=60 s' half of R086 is verified in T21."
- **R110 (:1990-2005)** T22, `NOT_RUN`: "Unresolved actions block duplicate incidents for the same asset and interval";
  "Second run for the same asset/overlapping interval cannot freeze or grant while one is unresolved, including two
  concurrent conversations (advisory lock)."
- **R118 (:2141-2156)** T22, `NOT_RUN`: "Cancellation before send is never overtaken by dispatch"; "Two-connection test:
  cancel commits vs mark_sent; nothing is POSTed and the abort yields a tombstone."
- **R094 (:1677-1692)** T22: "Kill tests at INTENT, SENT, post-commit and pre-persist; abort yields receipt or
  tombstone; late POST after tombstone never commits." **R095 (:1693-1708)** T22, **R109 (:1974-1989)** T22 ("Timeout
  path takes the lease lock, bumps the fence, reads the grant; late grant impossible afterwards."), **R119
  (:2157-2172)** T22 ("… run ends ABANDONED_UNVERIFIED; asset guard released; …").
- **R009 (:140-157)** T09, `RECORDED_LOCALLY_LIVE`: "Try attaching alpha proposal/message/approval records to beta
  parents; DB refuses." **R005 (:67-84)** T07: "… store exact bytes; changed payload changes hash."
- **R017 (:297-317)** T08/T12, `RECORDED_LOCALLY_LIVE`: "Concurrent requests cannot start two mutating investigations;
  status question makes no incident job."
- **R028 (:524-547)** T16 note ends: "a read-path freshness bound is T20's, subject to the owner's decision on erratum
  105." (Plan Q passed it to T21, §1.4.)
- **R041 (:801-823)** T19 note ends: "The manual path when the model is unavailable is T21's (R057)."
- **R052 (:987-1001)**, **R055**, **R056**, **R117** T26 (browser review flow, the eight UI states). **R070
  (:1257-1271)** T25: "Same permitted evidence/final approval rule; …" (condition A uses `/manual-proposals`, SA:660).
- **R128 (:2322-2341)** T09, `RECORDED_LOCALLY_LIVE`: "Direct INSERT into events/decisions/proposals/execution_grant/
  action_attempt_state and UPDATE of runs.state are denied for api, worker and sweeper; …".
- **R131 (:2393-2420)** T15/T47: mcp_exec EXECUTE "only resolve_invocation, grant_execution, mark_sent, record_outcome,
  request_abort, lookup_action".
- Development cards (`evals/handoff-development/scenarios.jsonl`): DEV-006 `self-approval` (`:6`, R043, expected
  `DENIED`), DEV-007 `reader-write` (`:7`, R013/R043, `DENIED`), DEV-008 `expired-review` (`:8`, R044,
  `BLOCKED_REVIEW`, "Require fresh revision/review rather than extending expiry."), DEV-009 `changed-proposal` (`:9`,
  R044, `DENIED`, "alex created revision 2 first", "sam clicks old revision 1"), DEV-010 `reviewer-revoked` and DEV-011
  `requester-revoked` (`:10-11`, R045, `BLOCKED_REVIEW`), DEV-012 `duplicate-decisions` (`:12`, R016/R047), DEV-014
  `cancel-before-grant` (`:14`, R046, `CANCELLED`), DEV-020 `stale-source` (`:20`, R032/R045, `BLOCKED_REVIEW`),
  DEV-025 `model-unavailable` (`:25`, R041/R061, `FAILED_WITH_MANUAL_PATH`).

### 1.4 Debts other plans pushed to T21

Code markers (`git grep 'TODO(T21)'` and "T21" in `*.py`, holdout excluded):
- `migrations/app/versions/0004_write_path_functions.py:159` (`freeze_proposal`): "-- TODO(T21): the asset guard
  (advisory lock, AM-13) and BLOCKED_REVIEW on refusal."; `:210` (`record_decision`): "-- TODO(T21): lazy expiry
  (expires_at < app.current_time() → BLOCKED_REVIEW(expired))."; `:301` and `0005_sessions_login_logout.py:140`: "--
  TODO(T21): asset freshness (5 min) and the asset guard; TODO(T13): the lease fence."; `0007_leases_fences.py:179`
  rewords the live body's line to "TODO(T21): asset freshness (5 min) and the asset guard advisory lock, first in the
  lock order (SA:189)." (`0004:12`: "Asset guard, lease fence, expiry and freshness are T13/T21.")
- `worker/src/ops_worker/graph/nodes.py:366`: `revision=1,  # TODO(T21): the revision a re-entered run freezes (Plan Q
  ruling 13)`.
- `worker/src/ops_worker/mcp.py:234`: `# TODO(T21): the write tools (mcp-write) still get only T47's check: no discovery
  and no result-schema check`.
- `worker/src/ops_worker/proposals.py:21`: `EXPIRY = timedelta(minutes=15)  # BUILD_SPEC §12 default; enforced by T21`.
- `worker/src/ops_worker/graph/build.py:118`: "One LangGraph thread per run and revision (Plan Q ruling 13): a revision
  starts a thread of its own (T21)."
- `core/src/ops_core/persistence.py:1056-1058` (`run_manifest_exists`): "(… Plan Q ruling 13 and erratum 125; whether a
  revision records its own is T21's)."
- `core/src/ops_core/locking.py:31`: `"advisory:asset",  # SA:189: … taken by T21`.
- `core/src/ops_core/privileges.py:7`: "the owners of later tables (feedback → T21, operator_resolutions → T22) add their
  rows".
- `sweeper/src/ops_sweeper/main.py:15`: "TODO(T21): proposal expiry."; `sweeper/src/ops_sweeper/tenants.py:3-4`: "T21's
  proposal expiry and T22's deadline escalation will."; `sweeper/src/ops_sweeper/wakeups.py:16-20`: a final grant
  refusal leaves the run APPROVED and is re-dispatched; "Moving such a run out of APPROVED (BLOCKED_REVIEW, AM-10) is
  T21's (debt list; round 1, I3)."
- `tests/plan_i/test_wakeups.py:69`: `assert wakeups.WAKEUPS == (("QUEUED", "investigate"), ("APPROVED", "execute"))  #
  ruling 7: T20, T21, T22 add`; `tests/e2e/test_migration_0010_live.py:152`: "(… the cancel endpoint itself is
  T21's)"; `tests/e2e/test_migration_0007_live.py:5`: an `app_definer` that cannot take the asset guard's advisory lock
  ("T21's gate would …"); `scripts/build_schemas.py:920`: "T21's fixtures use the seed ids, not these."

Debt lines in `SESSION_STATE.md` naming T21 (the lists are "committed before coding"):
- Walking skeleton (T08): "no asset guard or expiry → T12/T21" (`:1191`); "expiry and asset freshness are written but
  not enforced → T09/T21" (`:1197`); "the grant re-reads no current membership, and neither grant nor mark_sent
  re-checks cancellation or the dispatch deadline → T09/T21/T22" (`:1203`). Plan D open items (`:210`, `:212`): "the
  decision-hash cross-check, and BLOCKED_REVIEW on a refused grant (T21/T22)"; "`authored_by` is read outside the
  decision transaction (T21)".
- Plan E (T09/T10): "the definer functions without a caller today arrive with their owners: `create_revision`,
  `create_manual_proposal`, `expire_proposal`, `request_cancel` → T21" (`:1213`); "no asset-guard advisory lock →
  T13/T21" (`:1214`); "`record_decision` and `grant_execution` do not enforce proposal expiry or asset freshness → T21"
  (`:1218`); open items "the expiry and asset guard -> T21" (`:243`).
- Plan F (T11): "the enabled check guards the one decision-class route that exists (`POST
  /api/v1/proposals/{id}/decisions`); revisions, cancel and manual proposals attach the same dependency when they
  arrive → T21" (`:1230`); "the 'grants blocked within 60 s' half of R086 is implemented
  (`MEMBERSHIP_INACTIVE`/`MEMBERSHIP_STALE` in `grant_execution`) but its live evidence through a real grant lands
  with the final gate → T21" (`:1231`); "`expire_proposals` … → T13/T14/T21" (`:1234`).
- Plan G (T12): "the API reads the active run without a lock before a clarification or a status answer … → T21, which
  owns the slot's other doors" (`:1253-1255`); "`feedback` … is not created: its endpoint (BS:282) is in T21's
  instructions → T21" (`:1260-1261`); open items: "a malformed thousands group ('last 1,00 hours') is invisible to the
  window parser … other-script digits are unread by design (ASCII only) -> T21 (revision parsing) or a later parser
  pass" (`:346-347`); "`decide_once` reuses the 'stale' message for any `Conflict` code (only `VERSION_CONFLICT`
  reaches it today) -> T21" (`:351-352`); final review: "lower-case, accented or full-width asset spellings and
  'previous'/'two days' are unread … → T21" (`:369-370`); `docs/reviews/plan-g-final-review-2026-10-10.md:181-182`:
  "Add M3 to T21's `decide_once` item so both `Conflict` mappings are fixed together."
- Plan H (T13): "the asset-guard advisory lock is placed in the lock order and proved callable by `app_definer`, but
  `freeze_proposal` and `grant_execution` do not take it yet → T21" (`:1286-1287`).
- Plan I (T14): "the decision-to-processing crash test of R023 (inject a crash between decision, event, checkpoint and
  job acknowledgement; the sweeper resumes exactly the accepted event) → T21" (`:1327-1328`); "a grant refusal the
  execute handler takes as final (an inactive membership, a missing approval) finishes the job and leaves the run
  APPROVED, so the wake-up sweep re-dispatches it until the job has been claimed `OPS_WAKEUP_MAX_ATTEMPTS` times;
  moving such a run out of APPROVED (BLOCKED_REVIEW, AM-10) so the sweep stops → T21" (`:1342-1344`).
- Plan L (T17): "the final grant's recheck that every cited source version is still approved and effective (BS:425,
  R045) → T21" (`:1434`).
- Plan M (T16): "recording the status observation (`observed_at`, `revision`) where the grant can check its 5-minute
  freshness (R116, BS:476) → T21 (ruling 16)" (`:1455-1456`); "a run's asset is not tied to its tenant at admission (an
  alpha run may name beta's B22; asset-sim's own tenant filter answers NOT_FOUND, and the search then has no run type)
  → T21 (the asset guard; its review note names alpha-for-B22)" (`:1467-1468`).
- Plan P (T19): "with the model unavailable, the authorized manual search and proposal path is not offered → T21
  (BS:564; R057 and R041's 'manual path') (ruling 8)" (`:1570-1571`).
- Plan Q (T20): "the read path has no membership freshness bound (erratum 105) → the owner's decision on erratum 105,
  then T21" (`:1615`); "revision re-entry is a seam only: one LangGraph thread per run and revision, `build_proposal`
  freezes revision 1, `runs.checkpoint_id` is per run, and the manifest stays one per run (erratum 125) → T21"
  (`:1621-1622`); "`workflow_version` lives only in the checkpoint metadata → T21 (a column) and T36 (routing across a
  bump)" (`:1623`); "an execute job whose run's latest decision is not an approval of its active proposal ends without
  a graph run, logs the three ids and leaves the run APPROVED … recovering such a run → T22" (`:1625-1626`); "a
  rejected run's graph thread ends at the reviewer wait: `record_decision` queues no job on a rejection, so
  `publish_state` never runs for it in v1; the run's REJECTED state is the API's and is authoritative → recorded
  (erratum 128), no task" (`:1627-1629`); "the worker's write tool keeps T47's result check: no discovery listing and
  no result-schema check for `create_incident` (Plan Q departure 4) → T21" (`:1630-1631`).
- Plan D/G-era record: `tasks.json:410` (T07): "the 409 SLOT_OCCUPIED of R120 is T21's".

`tasks.json` review-note "Deferred" sentences naming T21: Plan E (`:516`) "the eleven definer functions without a
caller arrive with T11/T13/T15-T17/T21/T22 … expiry and asset guard -> T21"; Plan F (`:574`) "the enabled check on
revisions, cancel and manual proposals, and the grant-side live evidence for R086 through a real grant_execution call
-> T21"; Plan G (`:604`) "the feedback table -> T21"; Plan H (`:638`) "the asset guard -> T21"; Plan I (`:664`) "R023's
decision crash test and moving a finally refused grant's run out of APPROVED -> T21"; Plan L (`:748`) "the grant's
document recheck -> T21"; Plan M (`:784`) "the status observation for the grant's freshness and a run's asset tied to
its tenant -> T21"; Plan P (`:860`) "the manual path -> T21"; Plan Q (`:893`) "revision re-entry -> T21". `STATUS.md:446`
adds "discovery -> T21" and `STATUS.md:447` "Next: T21."

### 1.5 Tasks that consume T21, and what they expect

- **T22** (`tasks.json:937-975`, M08, depends `["T21", "T47"]`): "grant inserts INTENT; mark_sent before I/O;
  record_outcome; recover jobs with redispatch/abort rules; reconciliation backoff; transport-timeout rule; CONFLICT
  and deadlines to ESCALATED; asset guard; receipt retention." Requirements include R046 and R125 (shared with T21),
  R110, R118, R109. Review notes (`:968-973`) include "Redispatch skips the section 13 gate via lookup_action ->
  mark_sent; mark_sent re-checks cancel/deadline under runs lock." and "request_abort is invoked inside create_incident
  after mark_sent returns cancelled/expired …".
- **T24** (`:997-1021`, depends `["T22"]`): core cards in fake mode; review notes (`:1015-1016`) "DEV-008 lazy
  BLOCKED_REVIEW commits even when the decision returns 409." and "Add cards for escalation, tombstone/late POST, asset
  guard, operator resolution, cancel-vs-mark_sent."
- **T25** (`:1022-1051`, depends `["T22", "T18", "T23"]`): condition A is "manual baseline (human-authored proposal via
  `/manual-proposals`)" (SA:660); `core/src/ops_core/grading.py:236-248` `from_manual_proposal` reads a proposal shaped
  as `schemas/manual-proposal.schema.json` (title, summary, evidence_refs, assumptions, limitations).
- **T26** (`:1052-1079`, depends `["T22", "T11"]`): "approval card bound to revision/hash; manual proposal UI"; review
  note (`:1077`): "APPROVED and BLOCKED_REVIEW are mapped". AM-40 state 4: "awaiting independent review (stale/expired
  disabled with a reason)" (SA:628).
- Plan Q's sheet §5 Q14 named the grant's freshness and asset guard as T21's; `docs/reviews/plan-review-m-2026-10-18.md:193`
  had placed the mcp-write discovery check with "**T21** (the first task that drives mcp-write's execute path from the
  graph) rather than T20, unless the plan shows T20 calls mcp-write".

---

## 2. Spec passages that bind T21

### 2.1 Proposal identity and the hash (AM-11, BS §6, AM-80)

- SA:166: "**One ID per revision.** `proposal_id` identifies exactly one immutable revision; `(run_id, revision)` is
  unique. Decisions carry `expected_payload_sha256` (T45 renames the schema field)."
- SA:167: "**At most one grant per run, ever.** `execution_grant` gains `run_id` with `UNIQUE (run_id)`, so it never has
  a second row, even after an abort. A failed or aborted action needs a **new run** for a new incident. Once a grant
  exists, revisions return 409." SA:168: "`action_id` is a random UUIDv4 created inside `grant_execution`."
- BS:234: proposal "run_id, revision, canonical payload bytes, payload hash, evidence IDs/versions/hashes, created_at,
  expires_at; immutable; unique `(run_id, revision)`". BS:235: decision "proposal_id, hash/revision, reviewer,
  approve/reject, reason, decision timestamp, idempotency key; immutable accepted decision". BS:236 (superseded by
  AM-11 for the key): execution_grant "… unique `(proposal_id, action_type)`".
- BS:256: "The hashed payload includes tenant, run, proposal revision, action type, destination identifier, asset, the
  resolved interval, title/summary, evidence references and their hashes/versions, limitations, workflow/prompt
  versions, and expiration. Exclude approval records, …". BS:258: "Different content requires a new proposal revision
  and approval, not reuse of a previous key."
- SA:778 (`proposal.schema.json`): "`authored_by` sits **outside** the hashed payload, as a sibling of `payload`,
  stored and checked at decision time. `supersedes_run_id` **inside** the hashed payload, injected by `freeze_proposal`
  from `runs`; a draft containing it fails validation (AM-13)." SA:773: "`decision.schema.json` + examples |
  `expected_payload_sha256`".

### 2.2 Decisions: first wins, independence, revisions (BS §13, AM-20.3, AM-20.7)

- BS:466: "Decision input includes proposal ID, expected revision, payload hash, approve/reject and optional bounded
  reason; session identifies the reviewer. The server verifies that the reviewer is current, in scope, different from
  requester, viewing the active unexpired proposal, and submitting a permitted transition. First accepted decision wins
  for that revision. Same idempotent replay returns its recorded result; an opposing decision or stale revision
  returns conflict. Corrections create new revisions, never mutate approved bytes." BS:468: "The API commits the
  decision and a deduplicated wake-up job atomically. It does not execute a tool in an HTTP approval handler."
- SA:454 `record_decision(proposal_id, expected_payload_sha256, decision, reason, idempotency_key)`, caller `api`
  ("reviewer identity = the API's authenticated `sub`; the API is the identity trust anchor"); locks "`runs` FOR
  UPDATE → `proposals` FOR SHARE → `decisions` → `memberships` FOR SHARE"; effect "Checks current membership, reviewer
  ∉ `authored_by`, active unexpired revision, hash equality, first-decision-wins, lazy expiry (→ BLOCKED_REVIEW);
  inserts the decision; transition → APPROVED or REJECTED; on approval inserts the `execute` job (dedup
  `proposal_id`)"; event "`approval.recorded` / `run.rejected`".
- SA:453 (`freeze_proposal`): "`authored_by` is derived from `runs` (requester plus revision authors), never passed by
  the worker". SA:539: "**Independence covers every content author.** The proposal records `authored_by` (requester
  plus revision and manual-proposal authors), and the reviewer must not be in it (R093)."
- BS:176: "A person holding both requester and approver roles still cannot approve their own proposal. A signing-valid
  JWT is not proof of current membership." BS:29: "Approval is an independent, authenticated, persisted decision bound
  to exact content."
- SA:455 `create_revision(run_id, expected_version, author, supersedes_run_id)`, caller `api`; "`supersedes_run_id`
  from the requester's structured revision request, validated against the tenant/asset"; locks "`runs` FOR UPDATE →
  `execution_grant` FOR SHARE"; "Refuses (`GRANT_EXISTS`) if a grant exists; refuses (`SLOT_OCCUPIED`) if the
  conversation has another active run; transition APPROVED/BLOCKED_REVIEW/AWAITING_APPROVAL → QUEUED; appends `author`
  to `authored_by`; inserts an `investigate` job (dedup `run_id:revision+1`)"; event `proposal.revised`. The performer
  table (SA:484) says "APPROVED / BLOCKED_REVIEW → QUEUED | `create_revision`" (contract erratum 1, §4, asks it to add
  AWAITING_APPROVAL).
- BS:274: "`POST /api/v1/runs/{id}/revisions` | New immutable proposal/request revision before dispatch; invalidate old
  approval and re-review". BS:275: "`POST /api/v1/proposals/{id}/decisions` | Independent current reviewer; exact
  hash/revision; accepted decision plus wake-up job in one transaction". SA:769: "`message.schema.json`, `revision`
  schema | Optional structured `supersedes_run_id` (requester-asserted)".
- BS:317: "AWAITING_APPROVAL | APPROVED or REJECTED on accepted independent decision; QUEUED on explicit revision;
  CANCELLED; BLOCKED_REVIEW if stale". BS:324: "Reject/revise are not success."
- BS:330: "`await_*` nodes first inspect current authoritative state, then interrupt if still waiting. Resume payloads
  carry only persisted event identifiers; reread the decision rather than trusting `{approved:true}`."

### 2.3 Expiry, BLOCKED_REVIEW and the conversation slot (AM-10, AM-20.3)

- SA:138: "AWAITING_APPROVAL | → BLOCKED_REVIEW on expiry: evaluated lazily inside any decision or grant transaction,
  plus by the scheduled `expire_proposals` job (60 s)".
- SA:139: "BLOCKED_REVIEW | Frees the conversation slot. → QUEUED on revision **only if the conversation has no other
  active run, else 409** [R3-B4]; → CANCELLED".
- SA:140: "APPROVED | → QUEUED only via revision **before the grant exists**; **→ BLOCKED_REVIEW** on asset-guard
  refusal, stale evidence, revoked authority or expiry at grant [R6-B3]".
- SA:137 (DRAFTING): "**→ BLOCKED_REVIEW** on asset-guard refusal at freeze (`asset_action_unresolved` /
  `asset_incident_exists`) [R6-B3]".
- SA:145: "**Active states** (the ones that hold the conversation slot): QUEUED, AWAITING_INPUT, RETRIEVING, DRAFTING,
  AWAITING_APPROVAL, APPROVED, EXECUTING, OUTCOME_UNKNOWN."
- SA:150: "**Asset-guard refusals** [R5-S4, R5-H3]: DRAFTING (at freeze) or APPROVED (at grant) → BLOCKED_REVIEW with
  reason `asset_action_unresolved` or `asset_incident_exists`, emitting `review.blocked`. The requester resubmits by
  revision. Refusals never leave a run holding the slot in APPROVED."
- SA:151: "**`state_version`** increases **only on state transitions**. … so user cancels and decisions don't get
  spurious 409s [R5-S5]."
- SA:152 reasons: "`cancelled_before_send`, `aborted_no_commit`, `rejected`, `asset_action_unresolved`,
  `asset_incident_exists`, `expired`, `stale_evidence`, `authority_revoked`, `conflict`, `escalation_deadline`."
- SA:457 `expire_proposal(run_id)`, callers "`sweeper`; also invoked internally by `record_decision`/`grant_execution`";
  locks "`runs` FOR UPDATE → `proposals` FOR SHARE"; "If the active proposal's `expires_at < app.current_time()`:
  transition AWAITING_APPROVAL/APPROVED → BLOCKED_REVIEW(`expired`)"; event `review.blocked`.
- SA:346 and SA:504: `expire_proposals` is a scheduler job (sweeper role), dedup `name:<minute bucket>`. SA:520: "For
  every other table the sweeper **iterates `tenants`** (no RLS) and sets `app.tenant_id` per tenant before
  `expire_proposal`, `deliver_outbox` and deadline escalation".
- SA:157: "Every lease, expiry, freshness and deadline comparison uses `clock_timestamp()`, evaluated **after** the
  relevant row locks are acquired. Never use `now()` …"; tests use `app.current_time()` (SA:158).
- BS:321: "BLOCKED_REVIEW | QUEUED only after explicit correction/revision; CANCELLED; no silent extension of
  approval". BS:476: "Freshness proposal: a 15-minute proposal expiry; exact source version still approved/effective;
  asset status observation no older than 5 minutes at grant. … If freshness fails, stop at BLOCKED_REVIEW and request
  new evidence/revision." BS:559: "Proposal / asset freshness | 15-minute proposal expiry / status observed within 5
  minutes at grant". BS:684: "Expired/revoked approval | BLOCKED_REVIEW; new evidence/revision/independent approval; no
  silent expiry extension". BS:478: "Reconciliation of an existing action is allowed even after approval expiry because
  it observes, rather than authorizes a new effect."

### 2.4 The manual-proposal API and feedback

- SA:456: "`create_manual_proposal(run_id, payload, author)` | `api` | payload per `manual-proposal` schema | same as
  `freeze_proposal` | Tenant-scopes asset and evidence IDs (404 otherwise); otherwise identical to `freeze_proposal`
  with `authored_by = [author]` | `proposal.ready`".
- BS:281: "`POST /api/v1/manual-proposals` | Human-authored evidence-linked draft entering the same independent
  approval/write path". BS:280: "`POST /api/v1/search` | Authorized lexical/vector search for the manual baseline;
  bounded query/results". BS:564: "Model unavailable: retain request/evidence and offer authorized manual
  search/proposal workflow." SA:660: "A: manual baseline (human-authored proposal via `/manual-proposals`)."
- SA:542-546: "(b) **Every** decision, revision, cancel and manual-proposal mutation checks the user's enabled status
  through the Keycloak admin API. … 2 s timeout … **fails closed** with 503 `retryable`."
- SA:325: "**Feedback** (`POST /runs/{id}/feedback`) stores classified feedback and emits `feedback.recorded`. It has no
  runtime effect (R113)." BS:282: "`POST /api/v1/runs/{id}/feedback` | Store classified user feedback for later review;
  no runtime modification". BS:243: "feedback | run/proposal/event link, reviewer/user, typed feedback, reviewed flag;
  never authoritative runtime policy". SA:428: "`feedback` | ins, sel (api) | — | — | — | —". SA:510 lists `feedback`
  among the RLS tenant tables.
- SA:763: "New: `feedback`, `manual-proposal`, `revision`, `cancel-response` schemas | Per §7 and AM-14.
  `cancel-response` reports whether a grant or dispatch already occurred."

### 2.5 `grant_execution`, the final gate (BS §13, AM-13, AM-20.3)

- SA:462 `grant_execution(raw_handle, proposal_id)`, caller `mcp_exec`; locks "advisory(tenant, asset) → `run_lease`
  FOR SHARE → `runs` FOR UPDATE → `proposals` FOR SHARE → `decisions` FOR SHARE → `memberships` FOR SHARE →
  `execution_grant` → `action_attempt`"; effect "The §13 final gate: proposal belongs to the handle's run and tenant;
  approved, unexpired, hash-matching; requester and reviewer currently active; not cancelled; asset freshness (5 min);
  **asset guard (AM-13)**; inserts `execution_grant` (random `action_id`, `UNIQUE(run_id)`), `action_attempt` 1 and
  `action_attempt_state` INTENT; transition APPROVED → EXECUTING (or → BLOCKED_REVIEW with the refusal reason)"; event
  "`action.granted` (new type) or `review.blocked`".
- SA:228: "`grant_execution` performs the §13 final gate. It inserts the grant **and** attempt 1 in state `INTENT` in one
  transaction, then returns `(action_id, canonical_bytes, sha256)`."
- BS:472: "The MCP write boundary uses a shared domain function to lock the active run/proposal, read current
  requester/reviewer membership, verify the immutable bytes/hash/revision, enforce expiry/freshness/cancellation, and
  compare the active lease fence. Lock/version-check permission records so the authorization snapshot and concurrent
  revocation have a defined ordering. Persist a single execution grant/action ID and dispatch intent. Commit before
  destination I/O." BS:474: "This commit is the **authorization linearization point**. If cancellation or revocation
  wins before it, no dispatch is permitted."
- BS:425: "The final execution gate rechecks document versions and proposal freshness. A materially changed or revoked
  source invalidates pending approval." BS:178: "Requester and reviewer permissions are checked again at the final
  execution-grant transaction."
- SA:538: "**Proposals are bound to runs.** Every write or recovery function requires `proposal.run_id = handle.run_id`
  and the same tenant (R100)."
- SA:547: "(c) A membership sync job (every 60 s, run by the sweeper …) deactivates memberships of disabled or deleted
  users, and `grant_execution` reads membership." SA:550: "a disabled requester or reviewer blocks grants within ≤60 s".

### 2.6 The asset guard (AM-13, AM-12, AM-10)

- SA:283: "**Overlap** means the same tenant and asset and half-open intervals with `a < d ∧ c < b`. A requester who
  chooses a disjoint interval is not blocked; that is by design and documented."
- SA:284-286: "`freeze_proposal` and `grant_execution` both apply the guard, inside the per-(tenant, asset) advisory
  lock, against two sets: **(a) unresolved actions:** any other run with a grant whose latest `action_attempt_state` is
  not RESOLVED (EXECUTING, OUTCOME_UNKNOWN, ESCALATED), excluding runs already ABANDONED_UNVERIFIED → refusal
  `asset_action_unresolved`; **(b) committed incidents:** any other run with a SUCCEEDED outcome **or** SUCCEEDED late
  evidence, **regardless of when it was recorded** [R6-H5, owner decision] → refusal `asset_incident_exists`,
  **unless** `runs.supersedes_run_id` names that run. That field is set only from the requester's structured request
  (admission or revision), stored by `create_run`/`create_revision`, validated to name a run in the same tenant and
  asset, and **injected into the hashed payload by `freeze_proposal`**; a draft that carries its own
  `supersedes_run_id` is rejected [R7-H1]. The approval card shows the referenced incident, so the reviewer sees what
  is being superseded."
- SA:287: "A refusal transitions the run to BLOCKED_REVIEW (AM-10) and never leaves a grant behind. A second incident is
  therefore created only when a reviewer approved a proposal that explicitly named the first (R125)." SA:288: "They
  serialize on the per-(tenant, asset) advisory lock (AM-12), so two conversations cannot both pass the check (R110)."
  SA:289: "A refusal returns 409 `ASSET_ACTION_UNRESOLVED` or `ASSET_INCIDENT_EXISTS`, listing the blocking run only if
  the caller may see it. The run moves to BLOCKED_REVIEW (AM-10)."
- SA:189: "The asset guard lock is `pg_advisory_xact_lock(hashtextextended(tenant_id || ':' || asset_id, 0))`;
  `asset_id` is NOT NULL and read before locking. Proposal freezing and `grant_execution` take it first."
- SA:120: ESCALATED "frees the conversation slot, but the **asset guard** (AM-13) blocks a new incident proposal for the
  same tenant, asset and overlapping interval while the action is unresolved." SA:130: "After this acknowledgement
  [ABANDONED_UNVERIFIED] the asset guard no longer blocks that asset and interval."
- SA:3 (1.3.3 owner decision): "a grant is refused whenever **any** committed incident overlaps the same tenant, asset
  and interval, unless the proposal declares `supersedes_run_id` (R6-H5)." SA:154: "a draft carrying
  `supersedes_run_id` is rejected by `freeze_proposal`." SA:368: admission `investigate` takes "optional structured
  `supersedes_run_id`".
- BS:464: "The reviewer sees asset, fixed interval, destination, title/summary, sources/versions, limitations,
  expiration and whether anything has already been submitted." BS:532: "A proposal card shows exact revision/hash
  prefix, expiration, permitted sources, requester, required reviewer rule and actual submission state. … Expired or
  stale cards are disabled with a reason and backend enforcement."

### 2.7 Cancellation and revocation before the grant

- SA:458 `request_cancel(run_id, expected_version)`, caller `api`; locks "`runs` FOR UPDATE → `execution_grant` FOR
  SHARE"; "Sets `cancel_requested`; if no grant exists, transition → CANCELLED now; otherwise returns `{grant_exists,
  attempt_state}` for the cancel-response"; event "`run.cancelled` or none". SA:485: "any pre-grant active state →
  CANCELLED | `request_cancel`" (contract erratum 5 asks "pre-grant non-terminal state, including BLOCKED_REVIEW").
- BS:276: "`POST /api/v1/runs/{id}/cancel` | Request cancellation; report whether grant/dispatch already occurred;
  never claim undo". SA:247: "In INTENT, cancellation leads to abort, a guaranteed no-commit, because of the `mark_sent`
  re-check." SA:230-232: `mark_sent` "locks `runs` … and re-checks `cancel_requested` and the dispatch deadline. … This
  lock is what makes 'cancel in INTENT = guaranteed no-commit' true (R118)."
- SA:540-553 (revocation (a)-(c), quoted in §2.4/§2.5). BS:318: "APPROVED | EXECUTING only when final grant commits;
  BLOCKED_REVIEW if authority/freshness fails; CANCELLED only if cancellation wins before grant".

### 2.8 Lost wake-ups (DoD 3, R023)

- BS:340: "Avoid lost wakeups: user replies/approvals commit with a unique resume job. Mark their consumption only after
  processing reaches a durable acknowledged state. A sweeper compares pending user events, jobs, checkpoints and
  authoritative run state, and re-enqueues a deduplicated wake-up if a crash occurred between them. Replayed nodes
  reread current state and cannot re-freeze a different approved payload."
- SA:471 `reclaim_leases()`: "lost wake-ups re-enqueued (dedup keys)". SA:502: "`execute` | `record_decision` |
  `proposal_id`". SA:344: "`execute` | API with an approving decision | Final grant and first dispatch |
  `create_incident` | APPROVED, EXECUTING (attempt absent or INTENT)".

### 2.9 The run state machine rows T21 adds or exercises

AM-20.3 performers (SA:476-490): "AWAITING_APPROVAL → APPROVED / REJECTED / BLOCKED_REVIEW | `record_decision` (and
`expire_proposal`)" (SA:483); "APPROVED / BLOCKED_REVIEW → QUEUED | `create_revision`" (SA:484); "any pre-grant active
state → CANCELLED | `request_cancel`" (SA:485); "APPROVED → EXECUTING / BLOCKED_REVIEW | `grant_execution`" (SA:486);
"DRAFTING → AWAITING_APPROVAL / BLOCKED_REVIEW | `freeze_proposal`" (SA:482). The T07 table as code is
`core/src/ops_core/states.py:136-206` (§3.4); the SQL mirror `app.transitions` holds `TRANSITION_ROWS_0002`
(`migrations/app/versions/0002_roles_grants_rls.py:138-195`).

### 2.10 Lock order (SA:188 and errata)

- SA:188: "`asset guard advisory lock → run_lease → runs → messages → proposals → decisions → memberships →
  execution_grant → action_attempt → operator_resolutions → events → outbox`. Idempotency rows are written last, before
  commit." SA:186: "**Writes without a lease:** API and sweeper mutations (decision, cancel, revision, expiry) hold no
  lease. They serialize with `SELECT … FROM runs … FOR UPDATE` plus `expected_version`." SA:190: "Every transaction and
  definer function follows this order."
- Erratum 37 (`SESSION_STATE.md:293-295`): "the lock order begins with the idempotency scope's advisory lock,
  PostgreSQL's two-key form `pg_advisory_xact_lock(1, hashtext(<scope>))` …, a lock space distinct from the asset
  guard's one-key locks." Erratum 17 (`:231`): "the definer functions take no row lock on `proposals`, `decisions`,
  `memberships` or `execution_grant`, because a lock needs UPDATE on the table (plan ruling 23)." Erratum 52 (`:412`)
  and erratum 71 (`:541`, "a third advisory lock, the dead letter's announcement, after the asset guard") extend it.
  The published order is `core/src/ops_core/locking.py:29-51` (§3.5).

### 2.11 API errors and Idempotency-Key (BS §7, AM-80, Plan G)

- BS:264: "Every mutation requires an authenticated current session, CSRF/origin protection in cookie mode, a bounded
  body, and `Idempotency-Key`. State-specific mutations include `expected_version` or expected proposal
  revision/hash. The server sets actor, tenant, roles, timestamps and authority fields; reject client attempts to
  supply them." BS:299: "Same key/body returns the same logical result; same key/different body returns 409."
- BS:301: "Use 401 for missing/expired identity, 404 for inaccessible resource existence, 403 for a known permitted
  resource with a disallowed operation, 409 for stale versions/key conflicts, 422 for shape/content limits, 429 for
  bounded capacity, and 503 for unavailable durable admission."
- SA:764: "`error.schema.json` | Codes `ASSET_ACTION_UNRESOLVED`, `ASSET_INCIDENT_EXISTS`, `GRANT_EXISTS` (409 on
  revision after grant), `SLOT_OCCUPIED`, `AUTHORITY_VIOLATION`". SA:297: request-dedup replay window 24 hours.
- `api/src/ops_api/idempotency.py:1-14` (Plan G rulings 1-7): the key is scoped to tenant, subject, route template and
  key; "its record is the response … written last in the unit that did the work"; the unit's first statement is an
  advisory lock on the scope; never recorded: a key reused for another request (409 `IDEMPOTENCY_CONFLICT`), "anything
  raised before or outside the router's verdict (401, 403, the header and body shape refusals, 503)", and a full queue
  (429). Defaults `max_body_bytes = 65536`, `idempotency_ttl_seconds = 86400` (`core/src/ops_core/settings.py:289-290`).

---

## 3. The tree as it is (branch `plan-r`, `84eaee5`)

### 3.1 `api/src/ops_api/` — routes, the decision unit and what it does not check

- Modules: `app.py` (767 lines; every route is defined inside `create_app`, no `routes` package), `store.py` (1188),
  `auth.py`, `idempotency.py`, `limits.py`, `__main__.py`.
- Routes (`app.py`): `GET /health/live` (`:383`), `/health/ready` (`:387`), `GET /` (`:397`), the four auth routes
  (`:407`, `:430`, `:493`, `:511`), `GET /api/v1/me` (`:548`), `POST /api/v1/conversations` (`:558`), `POST
  /api/v1/conversations/{conversation_id}/messages` (`:571`), `POST /api/v1/runs/{run_id}/clarifications` (`:596`),
  `GET /api/v1/runs/{run_id}` (`:619`), `GET /api/v1/proposals/{proposal_id}` (`:636`), `POST
  /api/v1/proposals/{proposal_id}/decisions` (`:653`), `GET /api/v1/runs/{run_id}/events` (`:680`), and under the test
  profile `POST /internal/faults/{kind}` (`:697`). **Absent:** `POST /api/v1/runs/{id}/revisions`, `POST
  /api/v1/runs/{id}/cancel`, `POST /api/v1/manual-proposals`, `POST /api/v1/search`, `POST /api/v1/runs/{id}/feedback`,
  `GET /api/v1/evidence/{id}`, the stream route.
- Idempotency scopes (`app.py:62-65`): `ROUTE_CONVERSATIONS`, `ROUTE_MESSAGES`, `ROUTE_CLARIFICATIONS`,
  `ROUTE_DECISIONS = "POST /api/v1/proposals/{proposal_id}/decisions"`.
- Dependencies: `identity` (`:201-241`; bearer or cookie, current membership on every request), `browser_mutation`
  (`:243-253`; CSRF and origin in cookie mode), `enabled_identity` (`:255-268`; the Keycloak admin check, 503
  `UNAVAILABLE` when down, 401 when disabled), `requester_mutation` (`:275-278`; role `requester`, no enabled check),
  `reviewer_mutation` (`:280-284`; `enabled_identity` then role `reviewer`), `idempotency_key` (`:286-292`), `scoped`
  (`:294-304`), `recorded` (`:306-322`; 409 `IDEMPOTENCY_CONFLICT`, 429 with `Retry-After`).
- Error mapping (`app.py:324-375`): `ApiError` → SafeError; `st.Internal`, `PersistenceError`, `IllegalTransition`,
  `EventRuleViolation`, `psycopg.Error` → 503 not retryable; `OperationalError`/`InterfaceError` → 503 retryable unless
  SQLSTATE class 54 or 53400.
- `post_decision` (`app.py:653-678`): parses `DecisionRequest`, scopes the key with `{"proposal_id": …}` and the body,
  calls `store.decide_once(idem, tenant_id, proposal_id, reviewer=who.subject, roles=who.roles, request)`; `st.Forbidden`
  → 403 "an independent current reviewer is required" (unrecorded).
- `get_proposal` (`app.py:636-651`) returns `proposal_id`, `run_id`, `revision`, `payload`, `payload_sha256`,
  `authored_by`, `expires_at` — no requester, no reviewer rule, no submission state, no superseded incident. `get_run`
  (`:619-634`) returns `run_id`, `conversation_id`, `status`, `state_version`, `active_proposal_id`, `asset_id`,
  `start_at`, `end_at`, `created_at` (no `reason`).
- `store.decide_once` (`store.py:619-665`), inside `_idempotent`: reads the proposal with its run's `requester` and
  `state` without a lock (`DbUnit.proposal`, `:984-993`: `SELECT p.*, r.requester, r.state AS run_state FROM
  app.proposals p JOIN app.runs r …`); 404 when absent (`:636`); `check_reviewer` (`:637-642`, defined `:154-159`:
  Forbidden unless role `reviewer`, and Forbidden when `reviewer == requester or reviewer in authored_by`); 409
  `VERSION_CONFLICT` with the message "the proposal is not the active, undecided revision" when
  `row["revision"] != request.expected_revision` (`:643-645`); then `unit.record_decision` inside a savepoint
  (`DbUnit.record_decision`, `:995-1017`), mapping `persistence.NotFound` → 404, `VersionConflict` → `Conflict
  ("VERSION_CONFLICT")`, `Refused` → `map_refusal` (`:171-179`: `NOT_REVIEWER`, `SELF_REVIEW`, `MEMBERSHIP_INACTIVE` →
  Forbidden; `SLOT_OCCUPIED` → `Conflict("SLOT_OCCUPIED")`; `INVALID_ARGUMENT` → Internal; anything else →
  `Conflict("VERSION_CONFLICT")`); a `Conflict` is recorded as 409 with `ErrorCode(exc.code)` and the "stale" message
  (`:652-653`). Success body: `proposal_id`, `run_id`, `decision`, `status`, `state_version` (200).
- The `api` unit never writes `decisions`, `approval.recorded`, `run.rejected` or the `execute` job itself: all four
  are in `app.record_decision` (§3.3). What the decision path does **not** check today: proposal expiry (no lazy
  expiry, no `expires_at` read anywhere in the API); the revision-vs-active check happens twice, once in Python
  (`expected_revision`, unlocked) and once in SQL (`active_proposal_id`, under `runs FOR UPDATE`); the reviewer-
  authored-revision case cannot arise (no revision route, `authored_by` is always `[requester]`); no manual-proposal
  author exists.

### 3.2 `core/src/ops_core/` — proposals, persistence, states, routing, privileges, locking, contracts

- **There is no `core/src/ops_core/proposals.py`.** The proposal builder is `worker/src/ops_worker/proposals.py`:
  `EXPIRY = timedelta(minutes=15)` (`:21`), `Frozen(payload, canonical, sha256)` (`:24-30`), `evidence_from_search`
  (`:33-52`), `build_proposal(*, tenant_id, run_id, proposal_id, revision, asset_id, start_at, end_at, draft, evidence,
  now, supersedes_run_id)` (`:55-97`; `action="create_incident"`, `destination="synthetic-incidents"`,
  `workflow_version=WORKFLOW_VERSION`, `prompt_version=PROMPT_VERSION`, `expires_at=now + EXPIRY`; returns
  `canonical_json(doc)` and `canonical_sha256(doc)` of `payload.canonical_dict()`). Its only caller,
  `nodes.validate_and_freeze` (`worker/src/ops_worker/graph/nodes.py:362-374`), passes `proposal_id=uuid4()`,
  `revision=1` and `now=datetime.now(UTC).replace(microsecond=0)` (the worker's wall clock, `:372`).
- `canonical.py` (122 lines): `canonical_json`, `canonical_sha256` (canonical JSON v1).
- `contracts.py`: `DecisionRequest` (`:217-224`; `expected_revision ≥ 1`, `expected_payload_sha256`, `decision ∈
  {approve, reject}`, optional `reason`); `RevisionRequest` (`:227-232`; `expected_version`, optional
  `supersedes_run_id`; no content fields); `CancelRequest` (`:235-240`); `CancelResponse` (`:243-273`; validator rules
  on `grant_exists`/`attempt_state`/status); `FeedbackRequest` (`:276-286`; `subject_kind ∈ {run, proposal, event}`,
  `subject_id`, `category ∈ {wrong_evidence, missing_evidence, wrong_conclusion, unclear, other}`, `text` ≤2000;
  docstring "The subject kinds and categories are a project choice; the spec names none."); `ManualProposalRequest`
  (`:289-316`; `asset_id`, `start_at`, `end_at`, `title`, `summary`, `evidence_refs` 1-8, `assumptions`, `limitations`;
  **no `run_id`, no `supersedes_run_id`**); `ProposalPayload` (`:358-416`; fields incl. `revision ≥ 1`,
  `source_snapshots`, `workflow_version`, `prompt_version`, `expires_at`, `supersedes_run_id`); `Proposal` (`:419-438`;
  `authored_by` 1-8 unique, hash check); `ErrorCode` (`:441-456`) already has `ASSET_ACTION_UNRESOLVED`,
  `ASSET_INCIDENT_EXISTS`, `GRANT_EXISTS`, `SLOT_OCCUPIED`, `AUTHORITY_VIOLATION`; `RunRequestFields` (`:189-199`).
- `persistence.py`: errors `NotFound`/`VersionConflict`/`Refused`/`HashMismatch`/`HandleRejected`/`AuthorityViolation`
  (`:41-70`) mapped from SQLSTATEs OC001-OC008 (`:74-83`); `freeze_proposal(conn, *, run_id, draft_id,
  payload_canonical, expires_at) -> Frozen(proposal_id, revision, state_version)` (`:368-378`); `record_decision(conn,
  *, tenant_id, proposal_id, reviewer, expected_payload_sha256, decision, reason=None, idempotency_key=None) ->
  Decided(run_id, state, state_version)` (`:389-409`); `grant_execution(conn, *, handle, azp, proposal_id) -> Grant`
  (`:611-621`; `Grant` `:582-593`); `lookup_action` (`:624-629`), `mark_sent` (`:632`), `request_abort` (`:644`),
  `record_outcome` (`:655`); `insert_job` (`:670`); `run_manifest_exists` (`:1056-1061`); `GraphFacts`/`graph_facts`
  (`:1064-1101`; `decision_present` = a `decisions` row exists for `runs.active_proposal_id`; the attempt state of the
  newest grant); `store_checkpoint_id` (`:1104-1113`); `insert_maintenance_job` (`:1152`). No wrapper exists for
  `create_revision`, `create_manual_proposal`, `expire_proposal` or `request_cancel`.
- `states.py`: `Reason` (`:45-57`, the SA:152 enum); `Performer` (`:76-96`, 13 performers incl. `EXPIRE_PROPOSAL`,
  `CREATE_REVISION`, `REQUEST_CANCEL`, `CREATE_MANUAL_PROPOSAL`); `IllegalTransition`, `SlotOccupied`, `AnswerOnlyRun`
  (`:98-108`); `_rows()` (`:136-206`): DRAFTING → AWAITING_APPROVAL and → BLOCKED_REVIEW (`_ASSET_GUARD`) for
  `freeze_proposal` and `create_manual_proposal` (`:157-163`, plan ruling 9); AWAITING_APPROVAL → APPROVED, → REJECTED
  (`rejected`), → BLOCKED_REVIEW (`expired`) by `record_decision` (`:164-173`); AWAITING_APPROVAL/APPROVED →
  BLOCKED_REVIEW (`expired`) by `expire_proposal` (`:174-175`); AWAITING_APPROVAL/APPROVED/BLOCKED_REVIEW → QUEUED by
  `create_revision` (`:176-178`); APPROVED → EXECUTING and → BLOCKED_REVIEW (`_GRANT_REFUSAL` =
  `asset_action_unresolved`, `asset_incident_exists`, `stale_evidence`, `authority_revoked`, `expired`) by
  `grant_execution` (`:179-180`); → CANCELLED by `request_cancel` from QUEUED, AWAITING_INPUT, RETRIEVING, DRAFTING,
  AWAITING_APPROVAL, APPROVED, BLOCKED_REVIEW (`:181-191`). `ACTIVE_STATES` (`:211`), `TERMINAL_STATES` (`:223-225`,
  REJECTED included), `PRE_GRANT_STATES` (`:227-229`, BLOCKED_REVIEW included), `GRANTLESS_STATES` (`:233`);
  `revision_allowed(src, *, conversation_has_other_active_run)` (`:271-283`; raises `SlotOccupied`); `freeze_allowed`
  (`:286-298`). No EXPIRED state exists (expiry is BLOCKED_REVIEW with reason `expired`).
- `routing.py`: `GRAPH_ROUTES` (`:422-461`): `awaiting_decision` (AWAITING_APPROVAL, `decision_present=False` →
  `await_decision`, `:441-443`); `approved` (APPROVED, `decision_present=True`, attempt `None` → `execute`,
  `:444-450`); `executing` (EXECUTING, decision present, attempt INTENT/SENT/ABORT_REQUESTED → `execute`, `:452-457`);
  `outcome_unknown` (`:459`); `settled` (`TERMINAL_STATES | {BLOCKED_REVIEW}` → `publish`, `:460`). There is no
  `rejected` row: REJECTED is in `TERMINAL_STATES`, so it falls under `settled`. An AWAITING_APPROVAL run with
  `decision_present=True` matches no row (`route_graph` raises `LookupError`, `:464-474`).
- `privileges.py`: `DEFINER_FUNCTIONS` (`:214-237`) lists `freeze_proposal` (`"uuid, uuid, bytea, timestamptz"`,
  worker), `record_decision` (`"uuid, uuid, uuid, text, text, text, text"`, api), `grant_execution` (`"text, text,
  uuid"`, mcp_exec) and no `create_revision`, `create_manual_proposal`, `expire_proposal`, `request_cancel`; `GRANTS`
  (`:73-…`) has no `feedback` row; `HELPER_FUNCTIONS` (`:239-251`) has no `_asset_guard`.
- `locking.py`: `LOCK_ORDER` (`:29-51`): `advisory:idempotency`, `advisory:asset`, `advisory:notification`,
  `jobs:claim`, `run_lease`, `runs`, `messages`, `drafts`, `proposals`, `decisions`, `memberships`, `execution_grant`,
  `action_attempt`, `action_attempt_state`, `operator_resolutions`, `invocation_context`, `run_state_history`,
  `events`, `outbox`, `jobs:finish`, `idempotency_request`. `OBSERVED_UNITS` (`:91-…`) include `"mcp-write
  grant_execution": ("run_lease", "runs")` (`:117`) and `"api decision (record_decision)": ("advisory:idempotency",
  "runs", "idempotency_request")` (`:122`); no unit takes `advisory:asset`.
- `jobs.py`: `JobType.EXPIRE_PROPOSALS = "expire_proposals"` (`:44`); `JOB_RULES[EXECUTE]` (`:89-93`: `create_incident`,
  APPROVED/EXECUTING, server write); `dedup_key` (`:170-…`; `investigate` `run_id:revision`, `execute` `proposal_id`).
- `outcomes.py`: `EventType` has `PROPOSAL_READY`, `APPROVAL_RECORDED`, `RUN_CANCELLED`, `FEEDBACK_RECORDED`,
  `PROPOSAL_REVISED`, `REVIEW_BLOCKED`, `RUN_REJECTED`, `ACTION_GRANTED` (`:150-166`); `PAYLOAD_KEYS` (`:189-205`):
  `message`, `status`, `evidence_refs`, `proposal_id`, `action_id`, `code`, `reason`, `outcome`, `receipt`,
  `tombstone`, `question_id`, `message_id`, `outbox_id` (no `subject_kind`, `subject_id`, `category`).
- Schemas: `schemas/manual-proposal.schema.json` (the `ManualProposalRequest` fields, `additionalProperties: false`),
  `feedback.schema.json` (`subject_kind`, `subject_id`, `category`, `text`; required the first three),
  `revision.schema.json` (`expected_version`, optional `supersedes_run_id`), `decision.schema.json`
  (`expected_revision`, `expected_payload_sha256`, `decision`, `reason`), `cancellation.schema.json`,
  `cancel-response.schema.json`, `error.schema.json` (the 13 codes), `proposal.schema.json`, `route.schema.json`.

### 3.3 Revisions 0001-0015: the tables and functions T21 touches

- **`app.runs`** (`0001_walking_skeleton.py:72-92`): `supersedes_run_id uuid` (`:79`), `active_proposal_id uuid`
  (`:86`), `cancel_requested boolean` (`:87`), `reason`, `state_version`; `0002:200-208` adds `slot_held`,
  `next_event_seq`, `cancel_requested_at`, `checkpoint_id text`, `budget_used`; the slot index is `CREATE UNIQUE INDEX
  runs_one_active_per_conversation ON app.runs (conversation_id) WHERE slot_held` (`0002:213`). No column for revision
  authors, no `workflow_version`, no revision counter. Grants (`0002:73-91`): `api` sel + upd(`cancel_requested`,
  `cancel_requested_at`); `worker` sel + upd(`checkpoint_id`, `budget_used`); `app_definer` ins, sel, upd(`state`,
  `state_version`, `reason`, `active_proposal_id`, `next_event_seq`, `slot_held`, `supersedes_run_id`, `updated_at`).
- **`app.proposals`** (`0001:142-156`): `draft_id uuid NOT NULL REFERENCES app.drafts (id)` (`:147`), `authored_by
  uuid[] NOT NULL` (`:152`), `expires_at timestamptz NOT NULL` (`:153`), `UNIQUE (run_id, revision)` (`:155`); 0002
  re-keys `(tenant_id, run_id)`, `(tenant_id, draft_id)` and adds `UNIQUE (tenant_id, proposal_id)`. Grants: api, worker,
  sweeper sel; `app_definer` ins, sel (`0002:109`). `app.drafts` (`0001:133-140`): AM-20.2 gives `ins, sel` to the worker only.
- **`app.decisions`** (`0001:158-167`): `proposal_id uuid NOT NULL UNIQUE` (`:161`, comment `:158`: "the first accepted
  decision wins (SA:454); a second one is a 409, never an overwrite"), `reviewer`, `decision ∈ {approve, reject}`,
  `reason`, `expected_payload_sha256`, `decided_at`; 0002 adds `tenant_id` and `idempotency_key` (`0002:255`). Grants:
  api, worker sel; `app_definer` ins, sel (`0002:110`).
- **`app.execution_grant`** (`0001:169-176`): `run_id uuid NOT NULL UNIQUE` (`:172`, comment `:169`: "At most one grant
  per run, ever (SA:167): UNIQUE (run_id) is the rule, not application code."), `proposal_id`, `payload_sha256`,
  `granted_at`; no authority snapshot, no dispatch deadline column (the deadline is `granted_at + _dispatch_seconds()`,
  `0010:128`). `action_attempt` (`0001:178-183`), `action_attempt_state` (`0001:185-196`; state ∈ {INTENT, SENT,
  ABORT_REQUESTED, RESOLVED}, `outcome`, `detail`).
- **`app.transitions`** (`0002:336`) holds `TRANSITION_ROWS_0002` (`0002:138-195`), frozen "A change to the table ships
  as a new revision with its own TRANSITION_ROWS_<rev>" (`0002:134-137`); it already has every row of §3.2's table,
  `create_revision`, `create_manual_proposal`, `expire_proposal`, `request_cancel` included.
- **`app._transition(run_id, dst, performer, reason, expected_version, event, payload)`** (`0003:193-235`): locks the
  run `FOR UPDATE`, checks `expected_version`, checks the row in `transitions` (OC004 otherwise), then `UPDATE runs SET
  state, state_version + 1, reason, slot_held = (p_dst = ANY (v_active))` with `v_active` the eight active states
  (`:201-202`, `:222`), inserts `run_state_history`, appends the event. A move into an active state whose conversation
  slot is taken raises the unique index's 23505 from inside `_transition`; only `create_run` maps that constraint to
  `SLOT_OCCUPIED` (`0003:296-301`).
- **`app.create_run`** (`0003:238-320`): validates `supersedes_run_id` as "a run with this tenant and this conversation"
  (`:279-283`, erratum 41: "validated against the tenant and the conversation"), not the asset; inserts the
  `investigate` job `format('%s:1', run_id)` (`:311-312`).
- **`app.freeze_proposal(run_id, draft_id, payload_canonical bytea, expires_at)`** (`0004:107-167`, unchanged since):
  caller worker; locks the run `FOR UPDATE`; requires DRAFTING (OC003), refuses `answer_only` (OC005 `ANSWER_ONLY`);
  requires a validated `drafts` row whose `draft_sha256` equals the recomputed hash (OC007); requires the payload's
  `run_id`/`tenant_id` (`PAYLOAD_RUN_MISMATCH`) and `supersedes_run_id` to equal the run's (`SUPERSEDES_MISMATCH`,
  `:144-147`: it verifies rather than injects, erratum 13); takes `proposal_id` from the payload; requires
  `payload.revision = max(revision) + 1` (OC003 `revision`, `:149-152`); inserts with `authored_by =
  ARRAY[v_run.requester]` and the passed `expires_at` (`:153-157`); sets `active_proposal_id`; `_transition(…,
  'AWAITING_APPROVAL', 'freeze_proposal', …, 'proposal.ready', {proposal_id})`. No advisory lock, no guard
  (`:159`).
- **`app.record_decision(tenant_id, proposal_id, reviewer, expected_payload_sha256, decision, reason,
  idempotency_key)`** (`0004:170-236`, unchanged since): caller api; NULL arguments → OC005 `INVALID_ARGUMENT`; reads
  the proposal (no lock), then the run `FOR UPDATE` (`:197`); OC003 "not the active undecided revision" unless the run
  is AWAITING_APPROVAL, `active_proposal_id = proposal_id` and the stored hash equals the expected one (`:198-201`);
  OC005 `NOT_REVIEWER` unless an active `reviewer` membership in the tenant (`:203-206`); OC005 `SELF_REVIEW` when
  `reviewer = requester OR reviewer = ANY(authored_by)` (`:207-209`); no expiry check (`:210`); inserts the decision,
  a unique violation → OC003 "first decision wins" (`:211-218`); on approve inserts the `execute` job (dedup
  `proposal_id`, `ON CONFLICT DO NOTHING`) and `_transition(…, 'APPROVED', …, 'approval.recorded', {proposal_id})`; on
  reject `_transition(…, 'REJECTED', 'record_decision', 'rejected', …, 'run.rejected', {proposal_id})` and no job.
- **`app.grant_execution`**: 0004 (`:253-316`) → 0005 (`:81-155`, adds `MEMBERSHIP_STALE`: a requester's or reviewer's
  row not synced within 120 s) → 0007 (`:173-181`, only the comment: "The lease fence was checked by _resolve_handle
  above … TODO(T21): asset freshness (5 min) and the asset guard advisory lock, first in the lock order (SA:189).") →
  0010 (`:90-123`, signature `(p_raw_handle text, p_client_azp text, p_proposal_id uuid)`, the token's azp). The live
  body: `_authority` (mcp_exec); NULL proposal → `INVALID_ARGUMENT`; `_resolve_handle(handle, azp, 'write')` (lease
  row `FOR SHARE`, fence, expiry, revocation, azp, job-type server; `0007:122-171`); the run `FOR UPDATE`; an existing
  grant for the run is returned as a replay when its `proposal_id` matches, else `OTHER_PROPOSAL`; then refusals, each
  `RAISE … OC005` with a DETAIL: `PROPOSAL_NOT_IN_RUN` (proposal not of the handle's run and tenant), `NOT_ACTIVE_APPROVED`
  (run not APPROVED or not its active proposal), `NO_APPROVAL` (no approving decision), `CANCELLED`
  (`cancel_requested`), `MEMBERSHIP_INACTIVE`, `MEMBERSHIP_STALE`; then inserts the grant (`gen_random_uuid()`),
  attempt 1, state INTENT, and `_transition(…, 'EXECUTING', 'grant_execution', …, 'action.granted', {action_id,
  proposal_id})`. It does **not** check: the decision's `expected_payload_sha256` against the proposal, `expires_at`,
  the cited source versions (BS:425), the asset observation's age (R116), the asset guard or its advisory lock. Every
  refusal raises, so the transaction rolls back and the run stays APPROVED (no BLOCKED_REVIEW, no `review.blocked`).
- **`mark_sent`** (`0010:139-…`) re-checks cancel and the dispatch deadline (`_dispatch_seconds()` = 300, `0010:128`)
  under the runs lock; **`request_abort`** (`0010:200-…`) is new in 0010; **`record_outcome`** (0004 → 0007 → 0010).
- **Absent functions:** `create_revision`, `create_manual_proposal`, `expire_proposal`, `request_cancel`,
  `escalate_run`, `resolve_escalation`, `reclaim_leases` (as a definer; the reclaim is a sweeper routine, erratum 49),
  `_asset_guard`. **Absent tables:** `feedback`, `operator_resolutions` (T22). `0003:45` already has
  `feedback.recorded` in `EVENT_TYPES_0003`.
- **Incident side.** `migrations/incident/versions/0001_walking_skeleton.py:23-41`: `incident.action_key(action_id PK,
  payload_sha256, state ∈ {COMMITTED, ABORTED, REJECTED}, incident_id, reason, receipt_id, decided_at)` and
  `incident.incidents(incident_id PK, action_id UNIQUE, payload jsonb, created_at)`; no tenant, asset or interval
  column (the asset and interval are only inside `payload`). The incident database is separate (role `incident`);
  `app_definer` cannot read it. On the application side a committed incident is a run that reached SUCCEEDED through
  `record_outcome` (`action.confirmed`, `source=destination`) or carries `action.late_evidence` with outcome SUCCEEDED
  (SA:127, SA:286); runs keep `asset_id`, `start_at`, `end_at` (`0001:80-82`).
- **No asset table in `app`.** No revision creates an assets table (`git grep 'CREATE TABLE app.asset'` finds none);
  assets live in asset-sim (`data/corpus/assets.json`, Plan M). `documents`/`chunks`/`embeddings` (0011, 0013) are
  readable by `worker` and `app_definer` only (AM-20.2 SA:431; `api` has no cell).
- **The asset observation is not stored.** `worker/src/ops_worker/evidence.py:48-81` reads `observed_at` from
  `get_asset_status` into the in-memory bundle (`FRESHNESS = 5 min`, `:27`); the `tool.completed` event carries only
  `{"message": tool}` (`nodes.py:211`); no column or table keeps the observation (`git grep observed_at` finds no
  migration or core hit).
- **Run manifests.** `app.run_manifests` (`0014_run_manifests.py:38-50`): `run_id uuid PRIMARY KEY`, one row per run.
- **Latest revision:** `0015_checkpoints`; next `0016`.

### 3.4 `worker/src/ops_worker/graph/` and `handlers.py` — the reviewer wait and the execute job

- `nodes.await_independent_decision` (`nodes.py:529-540`): rereads the run; while AWAITING_APPROVAL,
  `interrupt(str(run["active_proposal_id"]))`; then returns `facts` (state, intent, `decision_present`, attempt).
- `handlers._approval` (`handlers.py:174-194`): the resume value is the newest `approval.recorded` event's id, accepted
  only when no `run.rejected` exists and its `proposal_id` equals the run's active proposal; otherwise the job ends
  with an error log and no graph run (`:184-193`).
- `handlers.execute` (`handlers.py:197-233`): returns early unless the run is APPROVED/EXECUTING (`:208-210`); thread
  `build.thread_id(lease.run_id, 1)` (`:212`); a stored interrupted checkpoint → `Command(resume=str(approval))`
  (`:217-223`); a stored non-ended checkpoint → fork with `None` (`:224-225`); an ended checkpoint → a new graph run
  (`:226-227`); `Requeue` → `release_lease(…, requeue_seconds=EXECUTE_RETRY_SECONDS=30)` and return False (`:230-232`).
  `handle` (`:236-256`) closes `recover` jobs unhandled.
- `nodes.execute_approved_proposal` (`nodes.py:550-602`): only an `execute` job proceeds (`:568-572`); rereads under a
  fenced unit, requires APPROVED/EXECUTING; mints a write handle; calls `create_incident` with `{"proposal_id":
  active_proposal_id}`; `McpCallFailed` → `Requeue`; `GRANT_DEFERRED` envelope → `Requeue` (`is_deferred`,
  `:543-547`); an `outcome`/UNKNOWN envelope → `mark_unknown`; any other envelope (a `GRANT_REFUSED` error included) is
  final and the node returns facts (the run stays APPROVED). `reconcile_outcome` (`:633-642`) logs and ends.
- `nodes.validate_and_freeze` (`:348-404`): one fenced unit: `run_row(lock=True)`, `freeze_allowed`, `build_proposal`
  (revision 1, `:366`), the `drafts` insert, `explanation.ready` (templated), `persistence.freeze_proposal`; any
  non-lease exception → FAILED `DRAFTING_FAILED`.
- Revision seam: `build.thread_id(run_id, revision)` → `f"{run_id}:{revision}"` (`build.py:117-119`); `run_graph(…,
  revision: int = 1)` (`:173`); `handlers.py:86`, `:124`, `:212` pass revision `1`; `config()` puts `workflow_version`
  in the checkpoint metadata (`build.py:122-132`). A REJECTED run's thread ends at the interrupt (no job is queued on
  rejection; erratum 128).
- `ops_worker.mcp`: `check_listing` (`mcp.py:90-…`) checks the read server's listing against `READ_TOOLS`; the write
  tools have no discovery or result-schema check (`:234`).

### 3.5 `mcp-write` — the grant's call path

- `execution.create_incident` (`mcp-write/src/ops_mcp_write/execution.py:113-154`): unit 1 `persistence.grant_execution`
  (a replay returns the stored grant and its attempt state); `next_step`; unit 2 `mark_sent` (committed before I/O);
  `cancelled`/`expired` → `_abort`; then the POST and `_record`.
- `server.answer` (`server.py:218-243`): resolves the handle first (`persistence.resolve_invocation`), then the work;
  `HandleRejected` → `INVALID_HANDLE`; `Refused` → `refusal_error(code)`; `NotFound` → `NOT_FOUND`; `VersionConflict`
  → `STALE_RUN`. `refusal_error` (`:71-82`): `MEMBERSHIP_STALE` → `{"code": "GRANT_DEFERRED", "retryable": true}`;
  `ABORT_NOT_DUE` retryable; `NOT_REDISPATCHABLE`; every other refusal → `{"code": "GRANT_REFUSED", "message": "grant
  refused: <DETAIL>", "retryable": false}`. No asset-guard code is mapped (no `ASSET_ACTION_UNRESOLVED` /
  `ASSET_INCIDENT_EXISTS` envelope exists).
- No asset guard exists anywhere in mcp-write or the definers.

### 3.6 The sweeper: wake-ups and expiry

- `sweeper/src/ops_sweeper/wakeups.py:47`: `WAKEUPS = (("QUEUED", "investigate"), ("APPROVED", "execute"))`; the scan
  `LOST` (`:64-74`) and the re-arm `REARM` (`:77-84`) reopen the newest done job of the type for a run still in the
  state, not cancel-requested, past `OPS_WAKEUP_GRACE_SECONDS` (60) and below `OPS_WAKEUP_MAX_ATTEMPTS` (10); past the
  cap a WARNING per tick. The APPROVED/execute pair re-arms both a lost decision wake-up (R023's case) and a run whose
  grant was refused for good (erratum 63).
- `sweeper/src/ops_sweeper/main.py:119-…` `tick`: sync, purge, `leases.reclaim`, `wakeups.sweep`, outbox; no expiry
  (`:15` TODO). `tenants.py:15-30`: `in_tenant`, `for_each_tenant` (the per-tenant iteration SA:520 asks expiry to
  use). `JobType.EXPIRE_PROPOSALS` exists; nothing inserts or claims it.

### 3.7 Tests that pin decisions and grants today

- `tests/plan_d/test_api.py:209-226` `test_decision_requires_an_independent_current_reviewer`: GET proposal 404 for
  another tenant; the requester (alex) 403, a reader (lee) 403, beta's reviewer 404; `expected_revision: 2` → 409
  `VERSION_CONFLICT`; an `approved_by` field → 422; sam 200 APPROVED; a second post 409. `test_pure_rules` (`:229-…`):
  `check_reviewer` refuses alex holding both roles, a reader, and a content author who is not the requester.
- `tests/plan_g/test_api_admission.py:265` `test_a_member_who_lost_the_reviewer_role_cannot_replay_a_decision`;
  `:308` `test_a_decision_replays_and_the_first_decision_wins` (same key → same bytes; the key on the decision row).
  `tests/plan_g/test_store_units.py:399` `test_a_decision_carries_its_key_and_a_reviewer_refusal_is_never_recorded`
  (first decision wins → 409). `tests/plan_e/test_api_store_mapping.py:20` `test_map_refusal`.
  `tests/plan_f/test_api_auth.py:310` `test_decision_is_503_retryable_when_keycloak_is_unavailable`.
- `tests/e2e/test_definers_write_path_live.py:192` `test_record_decision_independence_hash_and_first_wins` (requester
  `SELF_REVIEW` OC005, reader and beta's reviewer `NOT_REVIEWER` OC005, through beta OC002, stale hash OC003, worker
  42501, NULL hash OC005; approve → APPROVED v5; second decision OC003; jobs `investigate run:1` and `execute
  proposal`; events `run.accepted`, `proposal.ready`, `approval.recorded`); `:236` `test_rejection_frees_the_slot`
  (REJECTED v5, `slot_held` false, reason `rejected`, last event `run.rejected`); `:120`
  `test_freeze_proposal_binds_bytes_to_the_draft_and_refuses_the_rest`; `:305`
  `test_write_path_grant_sent_outcome_once_and_only_once` (`OTHER_PROPOSAL` at `:344`); `:604`
  `test_r106_the_definer_path_cannot_cross_tenants` (beta's handle with alpha's proposal → OC005 `PROPOSAL_NOT_IN_RUN`,
  `:620`, no grant rows); `:717` `test_grant_execution_refuses_a_stale_sync` (`MEMBERSHIP_STALE` at 121 s, no grant;
  fresh rows grant).
- `tests/plan_f/test_grant_deferred.py:21` (`MEMBERSHIP_STALE` is the one deferred refusal; `MEMBERSHIP_INACTIVE`,
  `NO_APPROVAL`, `CANCELLED`, `OTHER_PROPOSAL` → `GRANT_REFUSED`, not retryable); `:58`
  `test_execute_requeues_a_deferred_grant_and_releases_its_lease`. `tests/plan_k/test_write_tools_server.py:180`
  `test_a_refusal_before_the_destination_is_a_plain_error`; `tests/plan_k/test_recovery_tools.py:299`
  (`OTHER_PROPOSAL` for a recovery call).
- `tests/plan_q/test_graph_flow.py:417` (an approved run resumed from before its freeze executes), `:431` (a decision for
  another proposal runs nothing), `:473` (a re-dispatched execute job after a final refusal calls mcp-write again),
  `:593` (a `run.rejected` event refuses the resume). `tests/e2e/test_graph_live.py:195`
  `test_a_run_waits_for_its_reviewer_at_the_stored_checkpoint`. `tests/e2e/test_wakeups_live.py:79`
  `test_an_approved_runs_execute_wakeup_stops_at_its_cap`. `tests/e2e/test_worker_live.py:314`
  `test_unreachable_write_server_requeues_the_execute_job`. `tests/e2e/test_auth_live.py:240`
  `test_disabled_user_is_refused_and_synced_within_60s`. `tests/e2e/test_migration_0007_live.py` (`app_definer` can take
  the asset advisory lock).
- `tests/plan_c/test_states.py` (the table; `revision_allowed` and `SlotOccupied`), `tests/plan_c/test_contracts.py:357`
  `test_cancel_response_reports_grant_and_never_undo`.
- `pyproject.toml:48-52` `testpaths` ends `"tests/plan_q", "tests/e2e"`; `tests/plan_r/` does not exist.

### 3.8 Gates (as recorded, not re-run for this sheet)

`SESSION_STATE.md:1139-1140` (also `STATUS.md:432-433`): `PYTHONUTF8=1 uv run python scripts/check.py` `CHECK: GREEN`,
pytest `1738 passed, 227 skipped`; `… --profile test` `CHECK: GREEN`, pytest `1944 passed, 21 skipped`;
`verify_handoff.py` exit 0. The dev database is at 0013 (`SESSION_STATE.md:1761`: the owner's migration to 0015 is
open).

---

## 4. Prior rulings, debt lines and proposed errata touching T21

Errata continue at **131** (`SESSION_STATE.md:9`: "the next free erratum number is 131"). Open owner inputs: errata
35-130 undecided (`:1757-1760`), the nine contract errata (`:1776`).

- **Contract errata (Plan C, `SESSION_STATE.md:185-193`):** "1. AM-20.3 'Who performs which transition': the
  `create_revision` row should read 'AWAITING_APPROVAL / APPROVED / BLOCKED_REVIEW → QUEUED', matching the function
  table and BUILD_SPEC §8." "5. AM-20.3 'any pre-grant active state → CANCELLED' should read 'any pre-grant non-terminal
  state, including BLOCKED_REVIEW' …" "6. … `manual-proposal`, `model-pins` and the `get_recent_alerts` input accept `Z`
  or `+00:00` …, and the contract normalises to `Z` before hashing." "9. AM-20.3 'Who performs which transition': add
  `create_manual_proposal` with the `freeze_proposal` rows (DRAFTING → AWAITING_APPROVAL; DRAFTING → BLOCKED_REVIEW on
  `asset_action_unresolved` / `asset_incident_exists`) …". `states.py:159-160` (ruling 9): "a manual proposal replaces
  the model's draft for a run waiting for one (AM-50 condition A)".
- **Plan E errata:** "13. AM-20.3 signature deviations: … `freeze_proposal` takes the stored bytes and verifies a
  requester-asserted `supersedes_run_id` instead of having it injected; `record_decision` takes the tenant and the
  reviewer; …" (`:227`). "17. AM-20.3: the definer functions take no row lock on `proposals`, `decisions`,
  `memberships` or `execution_grant`, because a lock needs UPDATE on the table (plan ruling 23)." (`:231`).
  `docs/reviews/plan-e-final-review-2026-10-08.md:214-216`: "A refused grant (MEMBERSHIP_INACTIVE, CANCELLED,
  NO_APPROVAL) leaves the run APPROVED and holding its slot instead of moving to BLOCKED_REVIEW. Parked by Plan D to
  T21/T22, and unreachable today."; `:80-82`: "The R082 'one table' invariant would break silently the first time T21
  or T22 edits a row or adds an event type." (the frozen-revision rule followed).
- **Plan G errata:** 37 (lock order, §2.10); "41. SA:450: `supersedes_run_id` is validated against the tenant and the
  conversation." (`:303`); `docs/PROJECT_HISTORY.md:133`: "a requester-asserted `supersedes_run_id` was stored without
  checking that it named a run of the same tenant and conversation". `docs/reviews/plan-review-g-2026-10-10.md:53-55`:
  "The version check is therefore not serialised. A cancel (T21), a worker transition or crash recovery that moves the
  run between the read and the commit still gets a 202, a `resume_input` job and a `clarification.received` on a run
  that is no longer AWAITING_INPUT at that version."; `:115-116`: "Alternatively, a definer change that appends the
  replier to `authored_by` (a T20/T21 item)."
- **Erratum 63** (`SESSION_STATE.md:498-511`): lost wake-ups are re-armed for QUEUED/`investigate` and
  APPROVED/`execute`; "A grant refusal the worker takes as final leaves its run APPROVED and is therefore re-dispatched
  up to the cap (moving such a run out of APPROVED is T21's). **Trade-off for the owner (final review, M9).** AM-10 says
  a refused grant moves the run to BLOCKED_REVIEW; that is T21's work. Until then the re-arm re-dispatches an APPROVED
  run whose grant was refused, up to `OPS_WAKEUP_MAX_ATTEMPTS` claims (about ten minutes at the defaults). Each
  dispatch re-runs the full grant check … In v1 a deactivated membership cannot be reactivated (no admin surface; the
  sync only deactivates), so such a refusal does not clear and the re-dispatch only costs attempts; and the
  GRANT_DEFERRED (stale sync) retries depend on the re-arm. The conservative alternative is to drop the `("APPROVED",
  "execute")` pair from `WAKEUPS` until T21 lands BLOCKED_REVIEW. The owner decides." `docs/PROJECT_HISTORY.md:437-442`
  and `docs/reviews/plan-i-final-review-2026-10-15.md:140-147`, `:237-240` record the same; `:199`: "Proposal expiry
  not checked by `grant_execution`: T21's". Erratum 62 (`:496-497`): the sweeper "never inserts a `resume_input` or
  `execute` row". Erratum 69 (`:534-536`): per-tenant iteration for "T21's expiry and T22's deadline escalation later".
- **Erratum 105** (`SESSION_STATE.md:916-924`): `asset_scope` and `search_procedures_scoped` require an active
  requester membership "matched without the issuer …; the read-path check requires only an active row, with no
  `synced_at` freshness bound like the write gate's `MEMBERSHIP_STALE` (0005:129-139). … A read-path freshness bound is
  T20's, subject to the owner's decision on this erratum." (Plan Q moved the bound to T21, `:1615`.)
  `docs/PROJECT_HISTORY.md:762`, `:822`.
- **Erratum 125** (`SESSION_STATE.md:1156-1157`): "AM-80 and erratum 120: a run that retrieves again after a
  clarification keeps its one manifest; whether a revision records its own is T21's decision." Erratum 120
  (`:1107-…`): `run_manifests` is a tenant table neither AM-20.2 nor AM-20.5 lists.
- **Erratum 128** (`:1164-1171`): "… The graph thread of a rejected run ends at the reviewer wait: `record_decision`
  queues no job on a rejection, `publish_state` does not run for it in v1, and the run's REJECTED state is the API's."
- **Erratum 122** (`:1146-1149`): SA:377's sufficiency rule with a 5-minute window "(SA:462's asset freshness) of the
  instant mcp-read answered".
- **Plan Q ruling 13** (`docs/reviews/plan-review-q-2026-10-25.md:147-150`): "**Revision re-entry.** One thread per run
  and revision (`run_id:revision`); T20 leaves the seam (the handler reads the job's revision) and T21 builds re-entry;
  `build_proposal` stays `revision=1`; the manifest stays one per run in v1 (erratum 125: a revision's manifest is T21's
  decision); `workflow_version` goes in the checkpoint metadata only (debt → T21 for a column)." Ruling 14 (`:151-156`):
  "mcp-write discovery: T20 adds the startup listing check for `create_incident` … if it is one function and one test;
  the committed result schema → T21 (debt line)." Decision 4 (`:208-210`): "**No mcp-write discovery check; marker →
  `TODO(T21)`.** Accepted …". (The handler does not read the job's revision: `handlers.py:86`, `:124`, `:212` pass 1.)
- **Plan M** (`docs/reviews/plan-review-m-2026-10-18.md:39`, `:150`): "recording the status observation for the
  grant's freshness check (T21)"; "(R116) → T21 debt line". `docs/reviews/plan-m-final-review-2026-10-18.md:133`: "Give
  the missing freshness bound an owner in the debt list. The candidates are T21, next to the grant's freshness …".
- **Plan L** (`docs/reviews/plan-review-l-2026-10-17.md:142`): "**The grant's document recheck (FS Q22).** T21's (debt
  line); T17's state rows make it a query, nothing more."
- **Plan C review** (`docs/reviews/plan-review-c-2026-10-08.md:534`): "`authored_by` is alex, a real alpha persona …,
  while `payload.tenant_id` is the placeholder `0…01`. Harmless today; T21's 'reviewer ∉ authored_by' fixtures should
  not copy it."
- **Round 4** (`docs/reviews/plan-review-r4-2026-10-06.md:53`): "The slot rule is enforced by a partial unique index on
  `runs(conversation_id)` over active states, with a concurrent R120 test." **Round 5** (`plan-review-r5-2026-10-06.md:46`):
  the R6-H5 owner question on committed incidents, "then T21/T22".
- **Records that describe T21's work as done:** `docs/ARCHITECTURE.md:76`: "**The final gate is a database function.**
  `grant_execution` re-checks membership, hash, expiry, cancellation and the asset guard inside one transaction, and
  only `mcp_exec` may call it." (the live body checks no expiry, no decision-hash and no guard, §3.3);
  `docs/ARCHITECTURE.md:61` gives `api` "INSERT on … feedback" (no table exists).
- `BUILD_BACKLOG.md:53` (Plan E) lists untested branches "freeze_proposal ANSWER_ONLY/SUPERSEDES_MISMATCH/revision,
  grant_execution NO_APPROVAL/CANCELLED/MEMBERSHIP_INACTIVE … -> T13/T22".

---

## 5. Open questions the planner must rule on

1. **Per-revision proposal ids and the revision re-entry seam Plan Q left.** Facts: SA:166 (one id per revision,
   `(run_id, revision)` unique, enforced by `0001:155`); `freeze_proposal` requires `payload.revision = max + 1`
   (`0004:149-152`) and takes `proposal_id` from the payload; `build_proposal` is called with `revision=1` and a fresh
   `uuid4()` (`nodes.py:362-366`); the thread key is `run_id:revision` but every caller passes 1 (`handlers.py:86`,
   `:124`, `:212`; `build.py:173`); `runs.checkpoint_id` is one column per run (`0002:205`) and is resumed by the next
   job; `run_manifests` is keyed on `run_id` (`0014:39`) and `retrieve_evidence` skips the insert when one exists
   (`nodes.py:292-293`); SA:455 queues `investigate` with key `run_id:revision+1`; the held bundle and draft live in the
   process (`Context.held`), and a resumed graph run without them retrieves again (`nodes.py:11-13`). Options: what a revision
   re-enters (a new thread `run_id:N` started fresh from QUEUED; the same thread with an edge back to retrieval; the
   revision number read from the job's dedup key, from `max(proposals.revision)`, or from a new `runs` column); what
   happens to `runs.checkpoint_id` at a revision (cleared by `create_revision`, overwritten by the new thread's first
   checkpoint, or kept alongside a revision column); one manifest per revision (key change to `(run_id, revision)`,
   erratum 125) or one per run; whether the investigate handler's "QUEUED with a stored checkpoint → resume" branch
   (`handlers.py:118-127`) must distinguish a revision's QUEUED from a clarification's.
2. **What a revision is, and who may make one.** Facts: BS:274 "New immutable proposal/request revision before
   dispatch; invalidate old approval and re-review"; `RevisionRequest` has only `expected_version` and
   `supersedes_run_id` (`contracts.py:227-232`), so the content is re-drafted by the worker; SA:455's `author` is
   appended to `authored_by`; R093 / DoD 1 speak of a "reviewer-authored revision"; SA:542 requires the enabled check on
   revisions; `create_revision` refuses `GRANT_EXISTS` and `SLOT_OCCUPIED`; contract erratum 1 adds AWAITING_APPROVAL
   as a source; the Plan G parser blind spots are parked on "revision parsing" (`SESSION_STATE.md:346-347`, `:369-370`)
   though a revision carries no text today. Options: which roles may revise (the run's requester only, any requester
   of the tenant, a reviewer too, as DoD 1 implies); whether a revision carries text or fields (asset/interval
   unchanged, SA:154 and BS:297 "A later change is a revision"); whether the parser debt is closed, re-homed or left.
3. **Where "first decision wins" and the decision rules are enforced.** Facts: `UNIQUE (proposal_id)` on `decisions`
   (`0001:161`) raises OC003 "first decision wins" (`0004:216-217`); the API checks `expected_revision` before the
   definer, without a lock (`store.py:644`), and the definer checks `active_proposal_id` and the hash under `runs FOR
   UPDATE`; `check_reviewer` runs in Python on an unlocked read and again in SQL (`SELF_REVIEW`); `decide_once` maps
   every `Conflict` to the "stale" message (`SESSION_STATE.md:351-352`; Plan G final review M3); SA:454's signature
   omits the tenant and reviewer (erratum 13). DoD 1 "opposing/stale decisions 409": a same-key replay returns the
   recorded result (BS:466), a different key on a decided proposal is 409 today. Options: keep the definer as the one
   authority and the API's pre-checks as early refusals, or move the revision check into the definer (a new argument
   `expected_revision`); the 409 codes and messages for "already decided", "stale revision", "stale hash", "expired";
   whether Forbidden for a non-independent reviewer stays an unrecorded 403 or becomes 409.
4. **How the author set is known.** Facts: `proposals.authored_by` is written as `ARRAY[requester]` by `freeze_proposal`
   (`0004:157`); SA:453 says it is "derived from `runs` (requester plus revision authors)", but `runs` has no column for
   revision authors (§3.3); SA:456 gives a manual proposal `authored_by = [author]`; SA:539 "(requester plus revision and
   manual-proposal authors)"; the Plan D item "`authored_by` is read outside the decision transaction (T21)"
   (`SESSION_STATE.md:212`); `Proposal.authored_by` allows 1-8 unique entries (`contracts.py:426`). Options: a `runs`
   column (e.g. an array of revision authors) that `freeze_proposal` reads; the author set carried from proposal to
   proposal (new revision = previous `authored_by` + author); for a manual proposal whether the run's requester is in
   the set (`[author]` per SA:456, or `[requester, author]`); what happens at a cap of eight authors.
5. **Expiry.** Facts: `proposals.expires_at` is computed by the worker from its wall clock (`nodes.py:372`, `EXPIRY` 15
   min) while SA:157 requires `app.current_time()` for every expiry comparison; no code compares it (`0004:210`,
   `0005:140`); SA:138 asks for a lazy check in decision and grant plus a 60 s `expire_proposals` job; SA:457's
   `expire_proposal` is callable by the sweeper (which iterates tenants, SA:520; `tenants.for_each_tenant` exists) and
   internally; `JobType.EXPIRE_PROPOSALS` exists and nothing inserts it; a definer that refuses by RAISE rolls back any
   transition it made, so a "lazy BLOCKED_REVIEW that commits even when the decision returns 409" (T24 note, DEV-008)
   needs the function to return a verdict rather than raise, or a second transaction; the API's decision unit runs the
   definer inside a savepoint (`store.py:999-1012`); the transitions table already has the expiry rows (§3.2); there is
   no EXPIRED state; BS:478 allows reconciliation after expiry. Options: who sets `expires_at` (the worker's clock, the
   definer `app.current_time() + interval`, or both checked); where the lazy check lives (inside `record_decision` and
   `grant_execution` by calling `expire_proposal`, or in the API unit before the decision); how the decision's 409 and
   the committed BLOCKED_REVIEW coexist; the sweeper routine's shape (a maintenance row per minute like
   `sync_memberships`, the expiry per tenant, `review.blocked` payload); whether APPROVED runs expire before the grant
   (SA:140, SA:457 say yes).
6. **The revision path from BLOCKED_REVIEW and the conversation slot.** Facts: SA:139 (409 unless no other active run);
   `_transition` sets `slot_held` for active targets and a taken slot raises the index's 23505 from inside it
   (`0003:222`), which only `create_run` maps to `SLOT_OCCUPIED` (`0003:296-301`); `states.revision_allowed` raises
   `SlotOccupied` (`states.py:271-283`); `map_refusal` maps a `SLOT_OCCUPIED` DETAIL to `Conflict("SLOT_OCCUPIED")`
   (`store.py:175-176`); BLOCKED_REVIEW is not active (frees the slot, SA:139), so a new investigation may take the
   conversation meanwhile; Plan G's debt: the API reads the active run without a lock before a clarification (→ T21,
   "which owns the slot's other doors", `SESSION_STATE.md:1253-1255`); R120's test is "Revision from BLOCKED_REVIEW with
   another active run returns 409 SLOT_OCCUPIED". Options: catch the unique violation in `create_revision` by constraint
   name (as `create_run` does) or test the slot explicitly first; whether `create_revision` from AWAITING_APPROVAL or
   APPROVED (slot already held) needs the check at all; whether the Plan G read-without-lock debt is closed here.
7. **The manual-proposal route.** Facts: BS:281 `POST /api/v1/manual-proposals` with no run in the path, and
   `ManualProposalRequest` has no `run_id` (`contracts.py:289-316`), while SA:456 is `create_manual_proposal(run_id,
   payload, author)` and its transitions are DRAFTING → AWAITING_APPROVAL / BLOCKED_REVIEW (contract erratum 9, plan
   ruling 9: "a manual proposal replaces the model's draft for a run waiting for one"); `proposals.draft_id` is NOT NULL
   and references `drafts`, which only the worker may insert (`0001:147`, AM-20.2 SA:421); `ProposalPayload` requires
   `source_snapshots` (hash and version per evidence id), `workflow_version` and `prompt_version`; `api` holds no grant
   on `chunks`/`documents` (SA:431), so evidence ids can be checked only through a definer; there is no asset table in
   `app` (§3.3) and a run's asset is not tied to its tenant at admission (Plan M debt → T21); note 4 requires an alpha
   proposal for B22 to be 404 with nothing written; SA:542 requires the enabled check; R057 also names "search" (`POST
   /api/v1/search`, BS:280, absent); condition A of T25 reads the manual-proposal shape (`grading.py:236`); DEV-025
   expects `FAILED_WITH_MANUAL_PATH`. Options: a run-less route that creates its own run (via `create_run` then the
   manual proposal in one unit, a run starting in DRAFTING or a new creation row) vs a route bound to an existing run
   (a body or path `run_id`; which states: DRAFTING only, FAILED after a model outage, AWAITING_APPROVAL as a revision);
   how `drafts.draft_id` is satisfied (a definer-inserted drafts row, a nullable column, or a separate key); how the
   asset is tenant-scoped (asset-sim's catalogue, the corpus's asset families, a seeded table, or the run's own asset);
   which role may author (requester, reviewer); what `workflow_version`/`prompt_version` a human proposal carries;
   whether `POST /api/v1/search` is in T21.
8. **The feedback endpoint.** Facts: SA:325, BS:282, BS:243 ("run/proposal/event link, reviewer/user, typed feedback,
   reviewed flag"), SA:428 (`api` ins, sel), SA:510 (RLS); `FeedbackRequest` (subject kind/id, category, text) and
   `feedback.schema.json` exist; no table, no grant row (`privileges.py:7`), no route; `feedback.recorded` is in the
   event vocabulary (`0003:45`) and `api` may append it through `append_event` (only `action.*`, `run.*`, `review.*` are
   refused, SA:452), but `PAYLOAD_KEYS` has no subject or category key (`outcomes.py:189-205`); R113 "alters no
   prompt/policy/permission"; ARCHITECTURE:61 already lists the grant. Options: the table's columns (subject kind and
   id, category, text, author, created_at, a `reviewed` flag per BS:243 and who could set it); which roles may post
   (requester, reviewer, reader); whether the subject must belong to the run in the path and to the tenant (404
   otherwise); the event's payload (`message`, `reason`, or new payload keys, which is an event-schema change); whether
   the text is bounded/redacted in logs; how "no runtime effect" is evidenced (a test that no prompt, policy or
   membership table changes).
9. **`grant_execution`'s new checks.** Facts: present today: `UNIQUE (run_id)` (`0001:172`), replay of the run's grant,
   `OTHER_PROPOSAL`, `PROPOSAL_NOT_IN_RUN` (R100's binding), `NOT_ACTIVE_APPROVED`, `NO_APPROVAL`, `CANCELLED`,
   `MEMBERSHIP_INACTIVE`, `MEMBERSHIP_STALE`, the lease fence via `_resolve_handle`; absent: the decision's expected
   hash vs the stored hash, `expires_at`, the cited source versions still approved/effective (BS:425, Plan L debt; T17's
   state rows), the asset observation's age (R116; no observation is stored, §3.3), the asset guard and its lock;
   every refusal is a RAISE, so nothing commits. Options: which checks become refusals that commit BLOCKED_REVIEW with
   a reason (`expired`, `stale_evidence`, `authority_revoked`, `asset_*`) and which stay plain refusals (`OTHER_PROPOSAL`,
   `PROPOSAL_NOT_IN_RUN`, `NOT_ACTIVE_APPROVED`, `MEMBERSHIP_STALE` deferred); where the status observation is recorded
   for R116 (a new table or column written by the worker after `get_asset_status`, an event payload field, the run
   manifest) and whether a stale one blocks or the grant re-reads asset-sim (the definer cannot call HTTP); what "source
   still approved/effective" reads (the chunks' document states at `app.current_time()`).
10. **The asset guard.** Facts: SA:284-289; the advisory key `hashtextextended(tenant_id || ':' || asset_id, 0)`
    (SA:189), proved callable by `app_definer` (`test_migration_0007_live.py`); `locking.LOCK_ORDER` puts
    `advisory:idempotency` before `advisory:asset` (erratum 37), while note 1 says "first in lock order" and the API's
    decision unit already takes the idempotency lock; set (a) reads `execution_grant` + latest `action_attempt_state` of
    other runs, excluding ABANDONED_UNVERIFIED; set (b) reads runs SUCCEEDED or with `action.late_evidence` outcome
    SUCCEEDED — the application database knows both, the incident database has no asset column and is unreachable to
    `app_definer`; overlap is `a < d ∧ c < b` on `runs.start_at/end_at`; `supersedes_run_id` is validated today against
    tenant and conversation (erratum 41), SA:286 says tenant and asset; `freeze_proposal` verifies rather than injects
    it (erratum 13); R110 (the freeze-time guard and two conversations) is T22's, R125 is T21's and T22's; T22's
    instructions also say "asset guard". Options: one `_asset_guard(tenant, asset, start, end, run_id)` helper called
    by `freeze_proposal`, `create_manual_proposal` and `grant_execution`, or the guard in the grant only with freeze left
    to T22; whether `supersedes_run_id` must also name a run with an overlapping committed incident, and whether
    `create_run`'s check widens to the asset; whether the guard looks across conversations (SA:288 says yes); what
    "listing the blocking run only if the caller may see it" means for mcp-write's envelope.
11. **Refusals → BLOCKED_REVIEW, and erratum 63.** Facts: AM-10 wants every grant refusal for asset guard, stale
    evidence, revoked authority or expiry to end in BLOCKED_REVIEW (SA:140, SA:150); `_GRANT_REFUSAL` already lists the
    five reasons (`states.py:127-129`); the worker treats `GRANT_REFUSED` as final and leaves the run APPROVED
    (`nodes.py:598-602`); the sweeper re-arms APPROVED/execute up to ten claims (erratum 63, undecided); `MEMBERSHIP_STALE`
    is deliberately retryable (`GRANT_DEFERRED`); `mcp-write` maps every other refusal to `GRANT_REFUSED` (no
    `ASSET_*` codes); SA:289 names 409 `ASSET_ACTION_UNRESOLVED` / `ASSET_INCIDENT_EXISTS` (an HTTP vocabulary; the grant
    is an MCP call). Options: which refusal reasons map to which `Reason` (`MEMBERSHIP_INACTIVE` → `authority_revoked`;
    `CANCELLED` → `request_cancel`'s path, not BLOCKED_REVIEW); the envelope codes mcp-write returns after a committed
    BLOCKED_REVIEW; whether the `("APPROVED", "execute")` wake-up pair stays (it then covers only lost wake-ups and
    deferred grants).
12. **Revocation and cancellation before the grant (DoD 2, R045, R046).** Facts: no cancel route and no `request_cancel`
    definer; `api` holds UPDATE on `runs.cancel_requested` and `cancel_requested_at` (`0002:73-75`) but SA:458 routes
    the cancel through the definer; `grant_execution` refuses `CANCELLED` and `mark_sent` returns `cancelled` (R118,
    T22); `CancelRequest`/`CancelResponse` exist; the enabled check is required on cancel (SA:542); membership
    revocation reaches the grant through the sync (`MEMBERSHIP_INACTIVE`); DEV-010/011 expect BLOCKED_REVIEW;
    `test_migration_0010_live.py:152` sets the column directly as "What the API's cancel does to the run row". Options:
    whether T21 builds `POST /runs/{id}/cancel` and `request_cancel` (DoD 2 says "cancellation before grant blocks
    dispatch") or only proves the grant's refusal with the column set by a test; the cancel-response after a grant
    (`grant_exists`, `attempt_state`); who may cancel (the requester; a reviewer).
13. **DoD 3 and R023: the lost wake-up between decision commit and processing.** Facts: `record_decision` commits the
    decision, `approval.recorded` and the `execute` job in one transaction; the worker consumes the job in its final
    unit; the sweeper already re-arms APPROVED/execute after 60 s (`wakeups.py:47`) and `test_wakeups_live.py:79` proves
    the cap; the execute handler resumes with the newest `approval.recorded` id (`handlers.py:174-194`); R023's expected
    evidence names a crash "between decision/event/checkpoint/job acknowledgement" and "sweeper resumes exactly the
    accepted event"; a rejection queues no job (erratum 128); Plan H fault hooks exist under `PROFILE=test`. Options:
    which crash points the test injects (after the decision commit, after the job claim, after the resume's checkpoint
    store, before the job's final unit); whether "exactly the accepted event" is asserted through the resume value or
    the grant's proposal id; unit (fakes) vs live evidence.
14. **R086's grant-blocking half.** Facts: the sweeper syncs every 30 s (`main.py` docstring, SA:547 "every 60 s");
    the gate refuses `MEMBERSHIP_INACTIVE` once the sync deactivates the row and `MEMBERSHIP_STALE` when a row is older
    than 120 s (`0005:129-139`); R086 says "grants blocked within 60 s"; `test_disabled_user_is_refused_and_synced_within_60s`
    proves the sync half; no live test drives a real `grant_execution` after a disable; the read path has no freshness
    bound (erratum 105, pushed to T21). Options: the live test's shape (disable in Keycloak, wait for a sync, a real
    execute job's grant refused, run → BLOCKED_REVIEW `authority_revoked`); whether the 120 s stale bound changes to meet
    "≤60 s" when the sweeper stops; whether a read-path `synced_at` bound is added to `asset_scope` and
    `search_procedures_scoped`.
15. **The approval card (API payload; T26 renders it).** Facts: `GET /api/v1/proposals/{id}` returns the proposal fields
    of §3.1 only; BS:464 and BS:532 list asset, interval, destination, title/summary, sources/versions, limitations,
    expiration, requester, required reviewer rule, submission state; SA:286 "The approval card shows the referenced
    incident"; the referenced incident's id lives in the incident database (the app side has the superseded run's
    `action.confirmed` receipt in its event); `get_run` returns no `reason`, so a BLOCKED_REVIEW reason is invisible to
    the API caller. Options: extend `GET /proposals/{id}` (requester, decision state, `expired`, `superseded` with the
    run id and receipt's incident id) vs a new card route; add `reason` to the run snapshot; response schemas (T26
    debt).
16. **Revision 0016.** Facts: next free number; frozen-revision rule (`0002:134-137`; Plan E final review); `migrations`
    re-create a function by deriving from the applied body (`0010:_derived`); `privileges.DEFINER_FUNCTIONS`,
    `GRANTS`, `RLS_TABLES` and `locking.OBSERVED_UNITS` must name every new function, table and unit (the R124/R106/R107
    tests read them); the dev database is at 0013 (owner). Candidate contents named by §5's facts: `feedback` (+ grants,
    RLS), `create_revision`, `create_manual_proposal`, `expire_proposal`, `request_cancel`, `_asset_guard`; new bodies
    for `freeze_proposal`, `record_decision`, `grant_execution`; possibly a `runs` column for revision authors and/or
    `workflow_version`, an asset-observation store, a `run_manifests` key change, a `drafts` change for manual
    proposals, new event payload keys. Open: which of these, in one revision or several, and the mcp-write/worker startup
    checks that name 0016's functions (as 0009-0013 did).
17. **The mcp-write discovery and result-schema debt.** Facts: `mcp.py:234` `TODO(T21)`; `check_listing` covers the
    read server only (`mcp.py:90-…`); mcp-write advertises its generated schemas, not the committed files
    (`SESSION_STATE.md:1457-1459`); Plan Q decision 4 accepted the marker. Options: add the write listing check and a
    committed result schema for `create_incident` in T21, or re-home it (T22 drives `get_incident_receipt` and
    `abort_incident`; T30 has the transport bound).
18. **`workflow_version` per run.** Facts: BS:342 "Pin `workflow_version` per run"; it is in the hashed payload
    (`ProposalPayload.workflow_version`) and in checkpoint metadata (`build.py:128-131`); no `runs` column; T36 (M15)
    owns routing across a bump; Plan Q debt → "T21 (a column)". Options: a column written at creation/claim, the
    manifest, or leave it in payload and metadata with an erratum.
19. **The rejected run's thread and the REJECTED path.** Facts: erratum 128; `GRAPH_ROUTES` routes REJECTED to `publish`
    but no job runs it; `_approval` refuses a resume when `run.rejected` exists. Options: leave as recorded, or queue a
    job on rejection so the thread ends at `publish_state`.
20. **Tests and records.** Facts: `tests/plan_r/` is free and not in `testpaths` (`pyproject.toml:48-52`); live tests run
    under `check.py --profile test`; requirement rows to move: R023, R043, R044, R045, R046 (T21 half), R057, R090,
    R092, R093, R100, R113, R116, R120 (T21 half), R125 (T21 half), R086's grant half (owner T11); development cards
    DEV-006..DEV-014, DEV-020, DEV-025; the `TODO(T21)` markers of §1.4; `docs/ARCHITECTURE.md:61` and `:76`;
    `STATUS.md`, `README.md`, `docs/PROJECT_HISTORY.md` (every review round's problems and fixes); the Plan R debt list
    in `SESSION_STATE.md` before coding (R6-B7 practice); errata from 131. Open: which markers T21 closes and which it
    re-homes, and where each requirement's evidence lands (unit, live, report).

---

## 6. Glossary of exact names

- **Task/requirements:** `T21` (M08, "Proposals, decisions, manual proposals, feedback and final grant"); `R023`,
  `R043`, `R044`, `R045`, `R046`, `R057`, `R090`, `R092`, `R093`, `R100`, `R113`, `R116`, `R120`, `R125`. Neighbours:
  `T20` (done), `T11` (done; R086), `T22` (R046, R094, R109, R110, R118, R119, R125), `T24`, `T25` (R070, condition A),
  `T26` (R052, R117), `T36`, `T38`; DEV-006, DEV-007, DEV-008, DEV-009, DEV-010, DEV-011, DEV-012, DEV-014, DEV-020,
  DEV-025.
- **Spec anchors:** AM-10 SA:137-140, SA:145, SA:150-152; AM-11 SA:166-168; AM-12 SA:186-191; AM-13 SA:228, SA:230-232,
  SA:247, SA:283-289; AM-14 SA:311, SA:318, SA:325; AM-20.2 SA:415, SA:421-425, SA:428; AM-20.3 SA:453-458, SA:462,
  SA:482-486; AM-20.4 SA:500, SA:502, SA:504; AM-20.5 SA:510, SA:520; AM-20.7 SA:538-551; AM-50 SA:660; AM-80
  SA:763-764, SA:769, SA:773, SA:778; BS:176, BS:234-236, BS:243, BS:256-258, BS:264, BS:274-282, BS:299-301,
  BS:317-321, BS:330, BS:340, BS:342, BS:425, BS:464-478, BS:532, BS:559, BS:564, BS:684.
- **API:** `ops_api.app` (`create_app`, `identity`, `browser_mutation`, `enabled_identity`, `requester_mutation`,
  `reviewer_mutation`, `idempotency_key`, `scoped`, `recorded`, `post_decision`, `get_proposal`, `get_run`,
  `ROUTE_DECISIONS`, `ApiError`); `ops_api.store` (`AdmissionStore`, `DbStore`, `DbUnit`, `Unit`, `decide_once`,
  `check_reviewer`, `map_refusal`, `Forbidden`, `NotFound`, `Conflict`, `Internal`, `Decided`, `Membership`);
  `ops_api.idempotency` (`Idem`, `Scope`, `Verdict`, `IdempotencyConflict`, `fingerprint`, `HEADER`).
- **Core:** `ops_core.contracts` (`DecisionRequest`, `RevisionRequest`, `CancelRequest`, `CancelResponse`,
  `FeedbackRequest`, `ManualProposalRequest`, `ProposalPayload`, `Proposal`, `SourceSnapshot`, `RunRequestFields`,
  `ErrorCode`, `SafeError`); `ops_core.canonical` (`canonical_json`, `canonical_sha256`); `ops_core.persistence`
  (`freeze_proposal`, `Frozen`, `record_decision`, `Decided`, `grant_execution`, `Grant`, `lookup_action`, `mark_sent`,
  `request_abort`, `record_outcome`, `graph_facts`, `GraphFacts`, `run_manifest_exists`, `insert_maintenance_job`,
  `Refused`, `VersionConflict`, `NotFound`); `ops_core.states` (`RunState`, `Reason`, `Performer`, `TRANSITIONS`,
  `ACTIVE_STATES`, `TERMINAL_STATES`, `PRE_GRANT_STATES`, `GRANTLESS_STATES`, `require_transition`,
  `revision_allowed`, `SlotOccupied`, `freeze_allowed`); `ops_core.routing` (`GRAPH_ROUTES`, `GraphRule`, `GraphKey`,
  `route_graph`); `ops_core.jobs` (`JobType.EXECUTE`, `JobType.EXPIRE_PROPOSALS`, `JOB_RULES`, `dedup_key`);
  `ops_core.outcomes` (`EventType.APPROVAL_RECORDED`, `RUN_REJECTED`, `REVIEW_BLOCKED`, `PROPOSAL_REVISED`,
  `FEEDBACK_RECORDED`, `ACTION_GRANTED`, `PAYLOAD_KEYS`); `ops_core.privileges` (`DEFINER_FUNCTIONS`, `GRANTS`,
  `HELPER_FUNCTIONS`); `ops_core.locking` (`LOCK_ORDER`, `OBSERVED_UNITS`); `ops_core.grading.from_manual_proposal`.
- **Worker:** `ops_worker.proposals` (`build_proposal`, `EXPIRY`, `Frozen`, `evidence_from_search`);
  `ops_worker.graph.nodes` (`validate_and_freeze`, `await_independent_decision`, `execute_approved_proposal`,
  `is_deferred`, `Requeue`, `reconcile_outcome`); `ops_worker.graph.build` (`thread_id`, `run_graph`, `config`,
  `interrupted`, `ended`, `known`); `ops_worker.handlers` (`execute`, `_approval`, `EXECUTE_RETRY_SECONDS`);
  `ops_worker.evidence` (`FRESHNESS`, `observations`, `sufficient`); `ops_worker.mcp` (`check_listing`, `READ_TOOLS`).
- **mcp-write:** `ops_mcp_write.execution.create_incident`, `ops_mcp_write.server.refusal_error`, `tool_error`; envelope
  codes `GRANT_REFUSED`, `GRANT_DEFERRED`, `INVALID_HANDLE`, `NOT_FOUND`, `STALE_RUN`; definer DETAILs
  `PROPOSAL_NOT_IN_RUN`, `NOT_ACTIVE_APPROVED`, `NO_APPROVAL`, `CANCELLED`, `MEMBERSHIP_INACTIVE`, `MEMBERSHIP_STALE`,
  `OTHER_PROPOSAL`, `NOT_REVIEWER`, `SELF_REVIEW`, `SLOT_OCCUPIED`, `INVALID_ARGUMENT`.
- **Sweeper:** `ops_sweeper.wakeups` (`WAKEUPS`, `LOST`, `REARM`, `sweep`), `ops_sweeper.tenants` (`in_tenant`,
  `for_each_tenant`), `ops_sweeper.main.tick`; settings `OPS_WAKEUP_GRACE_SECONDS` (60), `OPS_WAKEUP_MAX_ATTEMPTS` (10).
- **Database:** `app.runs` (`supersedes_run_id`, `active_proposal_id`, `cancel_requested`, `cancel_requested_at`,
  `slot_held`, `reason`, `state_version`, `checkpoint_id`), index `runs_one_active_per_conversation`; `app.proposals`
  (`UNIQUE (run_id, revision)`, `authored_by uuid[]`, `expires_at`, `draft_id` → `drafts`); `app.decisions`
  (`UNIQUE proposal_id`, `expected_payload_sha256`, `idempotency_key`); `app.execution_grant` (`UNIQUE run_id`);
  `app.action_attempt`, `app.action_attempt_state`; `app.transitions`; `app.run_manifests` (PK `run_id`);
  `app._transition`, `app.create_run`, `app.freeze_proposal`, `app.record_decision`, `app.grant_execution(text, text,
  uuid)`, `app._resolve_handle`, `app._grant_row`, `app.mark_sent`, `app.request_abort`, `app._dispatch_seconds`;
  absent: `app.feedback`, `app.create_revision`, `app.create_manual_proposal`, `app.expire_proposal`,
  `app.request_cancel`, `app._asset_guard`; `incident.action_key`, `incident.incidents`; latest revision
  `0015_checkpoints`, next `0016`.
- **Job types / keys:** `investigate` (`run_id:revision`), `execute` (`proposal_id`), `expire_proposals`
  (`name:<minute bucket>`).
- **States/reasons/events:** `AWAITING_APPROVAL`, `APPROVED`, `REJECTED`, `BLOCKED_REVIEW`, `CANCELLED`, `EXECUTING`;
  reasons `rejected`, `expired`, `stale_evidence`, `authority_revoked`, `asset_action_unresolved`,
  `asset_incident_exists`; events `proposal.ready`, `approval.recorded`, `run.rejected`, `review.blocked`,
  `proposal.revised`, `run.cancelled`, `action.granted`, `feedback.recorded`, `action.late_evidence`.
- **Error codes:** `VERSION_CONFLICT`, `IDEMPOTENCY_CONFLICT`, `FORBIDDEN`, `NOT_FOUND`, `UNAVAILABLE`,
  `ASSET_ACTION_UNRESOLVED`, `ASSET_INCIDENT_EXISTS`, `GRANT_EXISTS`, `SLOT_OCCUPIED`, `AUTHORITY_VIOLATION`.
- **Routes (BS §7):** `POST /api/v1/proposals/{id}/decisions` (exists), `POST /api/v1/runs/{id}/revisions`, `POST
  /api/v1/runs/{id}/cancel`, `POST /api/v1/manual-proposals`, `POST /api/v1/search`, `POST /api/v1/runs/{id}/feedback`
  (absent).
- **Gates:** `uv run python scripts/check.py` (1738 passed, 227 skipped at `84eaee5`), `… --profile test` (1944 passed,
  21 skipped), `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts` (exit 0). Next
  erratum: 131.

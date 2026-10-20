# Plan N final review record — T18 exact vector retrieval and the comparison

Branch `plan-n`. The whole-branch review covered `4c99f14..3c69add` (the plan review record to the close-out): eight
tasks, each with one task review and one fix round, recorded in `docs/PROJECT_HISTORY.md` §31. It was also the only
review of Task 8's records. No agent connected to any database other than the `ops_test` databases of the test
profile; reviewers ran no live test and did not call Ollama.

Outcome: ready to merge with fixes — 0 Critical, 1 Important, 7 Minor. The controller ruled every item fixed, with
two recorded instead of changed: the close-out commit's subject wrongly names the comparison report, which Task 6
committed (history is not rewritten), and the read path's missing check of the stored rows' model digest stays a
debt owned by the first change of the embedding model. The fix wave is `1d71485` (11 new tests, red first). A scoped
re-review confirmed every item and found two leftovers: lines over 120 characters and a synchronous test under an
asyncio mark. The controller fixed them in `353c201`. Gates after the wave: dev 1461 passed / 218 skipped; live
(`--profile test`) 1658 passed / 21 skipped; `verify_handoff.py --reference-code --manifest --contracts` exit 0.

---

# Controller rulings on the final review

## Plan N final review — controller rulings (review: C:\Users\joeys\Desktop\MLOps\.superpowers\plann\final-review.md)

Verdict: ready to merge with fixes, 0 Critical / 1 Important / 7 Minor. One fix wave, then one scoped re-review.

### Important — fix
1. **I1, erratum 107 and the `skeleton.embed` docstring.** Both say a pin mismatch always ends `embed` with "nothing
   written". That is false for the per-tenant re-check: a mismatch found after an earlier tenant committed raises
   `EmbedInterrupted` and names the tenants already written. Reword 107 (`SESSION_STATE.md` ~:929-935) and the docstring
   (`scripts/skeleton.py` ~:312-315) to match `embed.py` and `docs/retrieval.md`. Grep the records for any other copy of
   the claim.

### Minor — fix
- **m1, magnitude bound in `checked()`.**
  - Every component must have |v| ≤ 1e6. The vector's double-precision norm must be at least 1e-6 (this replaces the
    "not all zero" test, which it includes). Otherwise the answer is `Malformed`.
  - Why: nomic-embed-text answers unit vectors, and pgvector stores and sums in single precision. A component near
    3.4e38 is out of range for `vector` and raises a database error outside mcp-read's envelope. Extreme components give
    NaN, and that row then silently vanishes. Tiny ones underflow to a zero norm.
  - The NaN filter stays as defence in depth.
  - Unit tests: a component of 1e7 is refused, a vector of norm 1e-7 is refused, and an ordinary unit vector passes.
  - The docs (`docs/retrieval.md`, the client docstring) state the rule.
  - Add a debt line: a NaN similarity on a permitted row is dropped, not refused. With the bound, only a row written
    around the client (a superuser insert) can hit it.
- **m2, unreadable pin file.** `load_embedding_pins` turns `OSError` and `ValueError` (decode) into `ModelPinsError`, so
  `skeleton.py embed` and the pin script answer in their one failure shape. Add a unit test for each caller, or for the
  loader plus one caller. mcp-read's own catch stays.
- **m3.** ARCHITECTURE §4's Downstream row (~:175) gains mcp-read → Ollama, for embeddings only.
- **m4.** The T18 note in `tasks.json` and `BUILD_BACKLOG.md` must:
  - name `/api/version`, which only the pin script calls;
  - list among the deferred items the stored-digest check on the read path, for the first re-embedding revision;
  - list the Ollama 0.40.4 decision as the owner's.
- **m5.** The `3c69add` commit subject wrongly says "the comparison report" (it was committed in Task 6). Do not rewrite
  history. Say it once in the history section's close-out sentence, or the final review record.
- **m6, stored-digest gap.**
  - Ruling: the gap stays trigger-based debt: the first revision that changes the embedding model re-embeds, and it
    owns the check.
  - Record it in the BUILD_BACKLOG debt list as "→ the first embedding-model change (no task yet; the owner opens one)",
    so it is visible.
  - Cost if wrong: an owner who hand-edits the pin without a re-embedding revision gets mixed-model answers. That is
    already documented as a reviewed repository change.
- **m7.**
  - Re-wrap the lines over 120 characters left by the fix rounds.
  - `embeddings.py:40`: `TODO(T30)` marker.
  - Make the ambiguous ARCHITECTURE sentence precise, using the reviewer's suggestion.

Gates after the wave: dev, live (`git checkout -- reports/` afterwards, keeping nothing), verify_handoff. Update every
count the records state if the new tests change them (dev passed rises; live passed rises by the same number).

---

# The final review

## Plan N final whole-branch review (T18: exact pgvector retrieval and the comparison)

Range `4c99f14..3c69add` (16 commits), branch `plan-n`, HEAD `3c69add`. Reviewer: final whole-branch seat, read-only.
Method: `superpowers/requesting-code-review/code-reviewer.md`. The 538 KB diff was read in passes: the code first
(0013, core, mcp-read, scripts), then tests, then docs, then the Task 8 records. Nothing was delegated.

What I ran (no database, no service, no Ollama):
- `uv run python -m pytest tests/plan_n tests/plan_l/test_migration_0011.py tests/plan_m/test_migration_0012.py -q`:
  92 passed. (`uv run pytest` without `-m` cannot import `scripts`/`tests`; that is the repo's layout, not a defect.)
- Rendered 0013's `SEARCH_PROCEDURES_SCOPED` and `MIN_SIMILARITY` from the module and read the SQL as it will run.
- Recomputed every k = 5 and k = 3 figure of `reports/retrieval-comparison.json` from its own `cases` (hit, every
  expected, mean recall, micro recall 31/31, 30/31, 29/31, 28/31, MRR, precision, answered-empty, forbidden rows
  122/85/87/71, Wilson bounds, both McNemar lists and p-values): all agree with the summary.
- `rc.markdown(json)` regenerates `reports/retrieval-comparison.md` byte for byte.
- The comparison's lexical answers equal `reports/retrieval/t17-lexical-baseline.json` per case, ids and ranks, and
  the committed T17 file's `answers_digest` equals the pinned `T17_ANSWERS_SHA256`.
- The threshold rule over the JSON's 100-row sweep chooses 0.68. The margins in PROJECT_HISTORY are right: A15, a
  draft_only no-source case, is kept at 0.685237 (+0.0052), and the weakest labelled hit is A22 at 0.68968 (+0.0097).
- R034's evidence paths, the research input and the plan review record all exist. The pin file's digest matches the
  report, SESSION_STATE's Environment row and the R034 note. The added lines carry no secret, token or private address.

### Strengths

- **The authority boundary holds, and it was checked.** In the rendered body, `_authority`, then `_resolve_handle`,
  then `set_config('app.tenant_id', …, true)`, then the R028 membership check, then the argument rule, and only then
  any corpus read and the vector branch (`tests/plan_n/test_migration_0013.py:106-123` asserts this order). The
  tenant comes only from the handle. `app.embeddings` gives INSERT+SELECT to `worker` and SELECT to `app_definer`, and
  REVOKE ALL from every other role (`0013_embeddings.py:65-70`, `privileges.py:149-151`). It has FORCE RLS with
  `tenant_isolation`. The live test `test_only_the_worker_writes_embeddings_and_only_its_tenants` proves `mcp_read`,
  `mcp_exec`, `api`, `sweeper` and `operator` get 42501 on SELECT and INSERT, that the worker cannot UPDATE or
  DELETE, and that the worker cannot write another tenant's row. `_min_similarity` is a helper granted to nobody. No
  new write path reaches mcp-read.
- **mcp-read's Ollama edge is narrow and in the right place.** `server.py:389-413`: handle, scope, asset-sim's asset
  type and the `ASSET_TYPE_OUT_OF_SCOPE` check all come first. Then `query_embedding` makes `/api/tags` (verify) and
  `/api/embed` calls under one 10 s budget, outside any transaction, and only then the third unit runs. Lexical never
  touches Ollama, and a test proves it (`test_a_lexical_search_leaves_the_embedding_model_alone`). The error strings
  are fixed rules and never carry an address.
- **0013 is built so it cannot drift.** The search is 0012's frozen body with three `changed()` replacements. Each
  one is checked to occur once, a unit test reverses all three and compares against 0012, and the vector branch's
  filters are sliced from 0012's own text. Ranking, ties, limit and the answer keys match lexical. The NaN filter
  sits in the vector branch only. `EMBEDDINGS_INCOMPLETE` is decided over the permitted and asset-filtered `scored`
  set, so a draft chunk without an embedding refuses nothing. The downgrade order is right: the 0012 body and its
  grants first, then the helper, then the table. The startup marker is unique to 0013 and is asserted absent from
  every older revision.
- **The fail-closed pin chain is complete end to end, except for the one gap that is recorded.** The pin script
  refuses to re-pin another build. `embed` verifies before planning and refuses a mixed store before writing
  anything. It verifies again after each tenant's vectors come back and before that tenant's transaction (proven by
  the RED/GREEN live test), and `ON CONFLICT DO NOTHING` makes concurrent runs safe. mcp-read reads and verifies the
  pin on every vector call, and a missing, unreadable, malformed or mismatched pin is `UNSUPPORTED_MODE`.
- **The report supports R034 and DoD 1 without overclaiming.** It gives both modes at k = 5 and 3 with denominators
  and Wilson intervals, recall both per case and per section, and every change named. It applies McNemar only to the
  two pre-declared comparisons and says p >= 0.05 is not evidence of equality. It names the tuning asymmetry (lexical
  would be 0.79 and 17/20 under the same rule), and states that the window experiment degenerates to whole-version
  embeddings. Its figures are exactly the JSON's.
- **The task reviews caught real problems.** The single-precision NaN, which passes `> 0.68` and sorts first, was
  reproduced live and fixed with a test that fails without the filter. A per-tenant pin re-check was added. The
  forbidden window check was moved to threshold 0. All of these are in the code, and all are recorded.

### Issues

#### Critical (Must Fix)

None.

#### Important (Should Fix)

**I1. Erratum 107 and `skeleton.embed`'s docstring say a pin mismatch always "writes nothing". The per-tenant
re-check, which this plan added, can stop the run after earlier tenants committed.**
- Files: `SESSION_STATE.md:929-935` (erratum 107: "verified … by `scripts/skeleton.py embed` before it writes (and
  again before each tenant's write) … a mismatch or a missing pin makes `embed` exit 1 writing nothing").
  `scripts/skeleton.py:312-315` ("Exit 1 with the reason, and nothing written, when the pin is missing or does not
  match …"; the "failure while writing" list names only "Ollama gone, an answer that is not the pinned vectors").
- Code: `core/src/ops_core/embed.py:152-155` calls `embedder.verify(pins)` inside `_write`. A `PinMismatch` there,
  after tenant `a` committed, becomes `EmbedInterrupted(written=("a",))` (`embed.py:135-138`), and the command prints
  `EMBED: failed (UNSUPPORTED_MODE: …) after writing a` (`skeleton.py:357`). The live test
  `test_a_model_replaced_mid_run_stores_nothing_under_the_pinned_digest` asserts exactly that (`written == ("a",)`).
- Why it matters: the brief requires erratum wording to match the code as reviewed, and an accepted erratum becomes
  spec text. As written, 107 tells the owner that a mismatch never leaves rows. In fact it leaves the rows of tenants
  written while the pin still matched. Those rows are correct, but the statement is false. `docs/retrieval.md:145-150`
  and `embed.py:18-20` already describe this correctly, so the records disagree with the code's own documentation.
- Fix: in 107, write "a mismatch or a missing pin found before the run writes makes `embed` exit 1 writing nothing;
  one found by the re-check before a later tenant's write exits 1 naming the tenants already written". In the
  `skeleton.embed` docstring, add "or the pin re-check finding another model" to the "failure while writing" list.

#### Minor (Nice to Have)

**m1. Vectors are checked for finiteness in double precision, but stored and compared in single precision. A stored
row can then be silently invisible, and a query can silently answer empty.**
- `core/src/ops_core/embeddings.py:103-122` (`checked`) accepts any finite double that is not all zeros.
  `0013_embeddings.py:158-159` drops a NaN similarity without refusing. The live test
  `tests/e2e/test_migration_0013_live.py:233-268` shows a stored row with 3e38 components passes the CHECK and is
  never returned.
- Scenarios. (a) The model answers components large enough that pgvector's float4 sums overflow: `embed` stores the
  row, and that chunk is never returned and never refused. This contradicts the design's "nothing is left out
  silently", which the docs state only for a missing embedding. (b) A query vector like that makes every similarity
  NaN or 0, so mcp-read answers `ok` with no results. (c) A component above about 3.4e38 is finite in Python but out
  of range for `vector`: the definer call raises a non-OC psycopg error, which escapes mcp-read's envelope (the same
  path as any unexpected database error).
- Likelihood: nomic-embed-text answers unit-scale vectors, so this needs a broken or replaced model. The pin makes
  that unlikely, so this is Minor.
- Fix: in `checked()`, also refuse any component whose magnitude is not float4-safe, for example `abs(v) > 1e6`, or a
  sum of squares that overflows after rounding through `struct.pack('f')`, as `Malformed`. The NaN filter then stays
  as defence in depth. Optionally, refuse (`EMBEDDINGS_INVALID`) instead of dropping when a permitted row's
  similarity is NaN.

**m2. A pin file that cannot be read or decoded is handled in mcp-read only. The other two callers still crash with a
traceback.**
- `core/src/ops_core/model_pins.py:80-82` (`load_embedding_pins`): `read_text` can raise `PermissionError` (an
  `OSError`) or `UnicodeDecodeError` (a `ValueError`), and neither becomes `ModelPinsError`.
- mcp-read catches both (`server.py:310`, Task 5's fix). `skeleton.py embed` catches only `ModelPinsError`
  (`skeleton.py:325`), and `pin_embedding_model.replaces_another_model` does the same (`:72-75`). Each prints a
  traceback, which contradicts the pin script's docstring claim that "every failure has one shape" (`:19-20`). An
  unwritable path at `out.write_text` (`:98`) is a third unhandled shape.
- Fix: map `OSError` and `UnicodeDecodeError` to `ModelPinsError` inside `load_embedding_pins`, which fixes all three
  callers. Then mcp-read's extra `except (…, OSError, ValueError)` can be narrowed, or kept as a belt.

**m3. One stale "Downstream" row in ARCHITECTURE.** `docs/ARCHITECTURE.md:175` (section 4's table) still lists
mcp-read's downstream as "asset-sim, governed corpus (through functions)". The role table (`:64`), the diagram
(`:44`) and section 11 now name the Ollama embedding edge. Task 7's fix aimed for "the Ollama edge reads the same in
every place". Fix: add "Ollama (query embeddings only, T18)" to that cell.

**m4. The T18 review note in `handoff/tasks.json:804` and `handoff/BUILD_BACKLOG.md:117` gets the client's endpoints
wrong.** It says "the Ollama client: /api/tags and /api/embed only". `OllamaEmbedder` also has `version()`
(`/api/version`, `embeddings.py:174-179`), which the pin script and the live comparison use. Only mcp-read is
limited to the two endpoints. Fix: "mcp-read asks Ollama only /api/tags and /api/embed; the pin script also asks
/api/version". The same note's "Deferred:" list also omits two items that `SESSION_STATE.md`'s debt list carries:
the read-path check of the stored digest, and the Ollama 0.40.4 decision. Consider naming both there.

**m5. The close-out commit subject claims a file the commit does not contain.** `3c69add`'s subject ends with "the
comparison report", but the commit changes only seven record files. The report was committed in `5c98e03` and
`62967e4`, following the controller's Task 6 ruling. The branch is not pushed, so the subject can still be reworded
(the owner's call). Otherwise, leave it: SESSION_STATE ruling (d) records where the report was committed.

**m6. The stored-digest read-path gap is recorded honestly, but it has no owning task.** `SESSION_STATE.md:1286-1290`
ends with "→ no task until a model change", and ARCHITECTURE section 11 states what is and is not guaranteed. I
judge the record honest. The only gap is that a hand edit of the pin file, reviewed but without a re-embedding
revision, would make mcp-read compare a new model's queries with old rows without refusing. R6-B7 asks for an owning
task per shortcut. "The first re-embedding revision" is a trigger, not a task. If the owner wants a task, T30 (which
already owns packaging the pin) is the natural one. Alternatively, a cheap guard is for `skeleton.py up` or
mcp-read's startup to compare `SELECT DISTINCT model_digest` against the pin. mcp_read cannot read the table, so
that would have to be a definer or an operator check.

**m7. Prose and comment polish (docs/CODE_COMMENTS.md rules 7 and 10).**
- Ragged wraps past 120 characters, left by the fix-round edits: `docs/adr/ADR-0001-…md:47-48` (127),
  `docs/runbooks/mcp-read.md` (two lines, 123 and 168), `docs/retrieval.md` (four lines, 148-195),
  `docs/ARCHITECTURE.md` section 11 (147), and the `tool_error` docstring wrap in `server.py:85-86`.
- `core/src/ops_core/embeddings.py:40`, `# read from the checkout (T30)`, marks incomplete work without `TODO(T30)`
  (rule 7).
- `docs/ARCHITECTURE.md:366`: "A vector search returns exactly what a lexical search may return" can be read as "the
  same results". It means "the same permitted set". Suggest: "A vector search draws from exactly the sections a
  lexical search may return".

### Records check (Task 8; this review is their only review)

- **Counts:** dev 1450/218, live 1647/21 and verify_handoff 0 match the brief and the ledger everywhere (SESSION_STATE,
  STATUS, PROJECT_HISTORY §31). The plan's 1434/1628 is quoted correctly as out of date.
- **Commits:** the `4c99f14..799beda` span plus "the close-out is the commit after" is correct (`3c69add`).
- **Figures:** every figure in SESSION_STATE, STATUS, the R034 note, the T18 note and §31 agrees with the JSON. That
  covers 27/27 and 26/27 (A08), 31/31 and 29/31, 15/20 and 18/20 (B10, B13, B17, B18 improve; A13 regresses), 0/122
  and 0/87, p 1.0 and 0.375, 0.79 → 17/20, 8 windows with hit@1 27/27 and MRR@5 1.0, the repeat cosine 1.0, and the
  margins +0.0052 and +0.0097. The 69 = 39 + 30 split matches the plan review and the unit test.
- **R034:** `IMPLEMENTED_LOCALLY_VERIFIED` / `RECORDED_LOCALLY_LIVE`, matching R033's pattern. All seven evidence
  paths exist. Lock `81f50c2b…1862` and digest `0a109f42…e59f` match the report and the pin.
- **Errata 107-111:** 108, 109, 110 and 111 match the code. 110's `OC005 EMBEDDINGS_INCOMPLETE` is the SQL's own
  code. Every envelope-level record (runbook `mcp-read.md:91,136`, debt list `SESSION_STATE.md:1292`) correctly
  says `REFUSED` with message `EMBEDDINGS_INCOMPLETE` (`server.py:432-433`, `test_mcp_read_vector.py:158`). The
  "refused (`EMBEDDINGS_INCOMPLETE`)" wording in `SESSION_STATE.md:1390` and `walking-skeleton.md:19` is loose but
  true. 107 is wrong as described in I1.
- **PROJECT_HISTORY §31:** it covers both plan review rounds with their counts, all seven task reviews with their
  problems and fixes, the parked item, the Task 6 ruling and the results. It records all four process slips: the
  plan writer's `python3 -`, Task 3's `python -`, the close-out heredoc, and the live-gate pair from Tasks 1 and 2.
  The renumbering to §32 leaves no stale reference: no file cites "§31"/"section 31" for "What the process taught",
  and every other "§30" reference is to the Plan M section, which is unchanged.
- **SESSION_STATE:** the owner inputs are complete: migrate to 0013, then `embed`; errata 1-111; Ollama 0.40.4
  against SA:587; merge PR #12; `plan-n` stacked and unpushed. The next step (T23; T19 and T41 wait on owner steps;
  T25 on T22, T23 and T41) matches a dependency scan of `tasks.json`, which finds T41, T19 and T23 as
  dependency-satisfied PLANNED tasks. The milestone line (M06: T41 open) is right.

### Declined to judge

- `app.embeddings.embedded_at DEFAULT now()` reads the database wall clock, not `app.current_time()`. The controller
  accepted it as an audit stamp (ledger, Task 4), and no logic reads it.
- mcp-read's verify-then-embed within one call has a millisecond TOCTOU window if the model is re-pulled between
  `/api/tags` and `/api/embed`. `embed` closes the same window with a post-check. For a read I judged it outside the
  plan's rulings (ruling 3 asks for a check on every call, which is done).
- `embed`'s planning phase reads full bodies only to count them: parked by ruling.
- Ollama 0.40.4 against SA:587's 0.33.3: an owner decision, recorded.
- `schemas/embedding-pins.schema.json` and `EmbeddingPins` do not fix `model` to `nomic-embed-text`. `verify()` and
  the table CHECK do, so this changes no behaviour.
- The brute-force exactness test orders by double-precision cosine while pgvector orders by single precision. A near
  tie closer than float4 precision could make it flaky. It passed on the real corpus, and the plan accepted the
  approach.
- Non-OC psycopg errors escaping mcp-read's tool envelope is pre-existing behaviour common to every definer call.
  Only its new trigger (m1c) is in scope.

### Recommendations

- Fix I1's wording in the same records pass as m3-m4 (text-only, no gate change).
- Take m1 and m2 as one small code change in `ops_core` (`checked()` bounds, `load_embedding_pins` exception
  mapping), each with a unit test. Neither needs a migration.

### Assessment

**Ready to merge: With fixes** (I1 is text-only; the minors can ride along or be parked with an owner).

**Reasoning:** The code meets the plan and the spec on every authority, exactness and fail-closed point I checked,
and the comparison report's figures reproduce exactly from its own data. The one Important finding is erratum 107's
"writes nothing", which is false for the per-tenant pin re-check this plan added. It should be corrected before the
owner decides the errata.

Counts: Critical 0, Important 1, Minor 7.

---

# Re-review of the fix wave (`3c69add..1d71485`)

Every ruled item was fixed in substance:
- I1: erratum 107 and `skeleton.embed`'s docstring now say that a mismatch found before writing leaves everything
  unwritten. A mismatch caught by the per-tenant re-check names the tenants already written.
- m1: `checked()` refuses any component above 1e6 and any norm below 1e-6. A unit vector is far inside both, and
  the edges are tested.
- m2: an unreadable or undecodable pin is a `ModelPinsError`, tested for the loader, `embed` and the pin script.
- m3, m4, m6: done as ruled.
- m5: recorded, not rewritten.
- m7: done, except the re-wrap.

The counts agree everywhere they are stated. All five process slips are in §31.

Two leftovers, both Minor and text-only:
- prose lines over 120 characters in `docs/retrieval.md`, `docs/runbooks/mcp-read.md` and one test docstring;
- `test_the_magnitude_bound_…` was synchronous under the module's `asyncio` mark, which raised a `PytestWarning`.

The controller fixed both in `353c201`: it re-wrapped the lines and made the test async, and the dev gate gave 1461
passed / 218 skipped, GREEN. One over-length line in `docs/retrieval.md` (line 11) predates Plan N and is left as is.

# First Slice G: Durable Admission, Idempotency and the AM-16 Router (T12) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every `/api/v1` mutation carries a scoped `Idempotency-Key` and runs as one recorded unit (advisory lock on
the scope, record lookup, the route's checks and the AM-16 router's verdict, the effect, the record written last,
commit), so a crash before commit leaves no acknowledgement and no record, a replay returns the first answer byte for
byte and a changed body is a 409; the six admission routes (investigate, clarification_reply, status_question,
readonly_answer, clarify, reject) live as an enumerable table in `core/routing.py` with a deterministic
text-versus-fields parser; the conversation slot holds one run; the interval is resolved once on the database clock;
and every refusal, including the framework's own, is the safe error schema with a server-made request id (T12;
R015, R016, R017, R018, R115, R129).

**Architecture:** Revision `0006_admission_idempotency` on the `app` main line creates `app.idempotency_request`
(the scoped record: status and JSON body; `api` sel/ins, `sweeper` sel/del; no RLS) and gives `app.messages` an
identity column `seq`, a CHECK on the stored kind vocabulary and a nullable `author` for the two system kinds. The
API gains two pure ASGI middlewares (`RequestId`, `BodyLimit` in `api/src/ops_api/limits.py`), a handler for every
exception class with `retryable` true only for an outage, the `idempotency_key` dependency, the clarifications route
of BS:273 and a test-profile-only fault route. `api/src/ops_api/idempotency.py` holds the key, the scope, the
fingerprint and the generic `idempotent()` unit; `api/src/ops_api/store.py` gains `AdmissionStore`, the T12
orchestration written once over a `Unit` of primitive operations (`DbUnit` in SQL, an in-memory unit in the tests),
so the unit tests run the same lock-lookup-work-record code as PostgreSQL. `core/src/ops_core/routing.py` gains
`ADMISSION_RULES` (first match wins), `REPLY_RULES`, the parser and the question templates. The sweeper purges
expired records with the other three tables.

**Tech Stack:** as Plan F; no new dependency (`psycopg-pool` stays out: two plain `api` connections race in the
live test, spike §4). FastAPI 0.143.0, Starlette 1.7.0, psycopg 3.3.6, PostgreSQL 17.11 (spike, Versions).

**Spec:** `SPEC_AMENDMENTS.md` (OPS-BUILD-1.3.6) over `BUILD_SPEC.md`. The fact sheet
`docs/superpowers/research/2026-10-09-plan-g-inputs.md` (T12 verbatim, the spec's admission, idempotency, error and
limit text row by row, the tree as it is, 28 open questions) and the measured spike
`docs/superpowers/research/2026-10-10-plan-g-spike.md` (§1 the record in the work's transaction and the race, §2 the
`jobs` INSERT-only grant, §3 `app.current_time()` from `api`, §4 concurrent admission, §5 the error surfaces and the
body limit, §6 message ordering, §7 the interval's clock, §8 the queue bound) are committed on `plan-g` (b4e97bc)
with this plan; the rulings below cite them as (fact sheet §n) and (spike §n). Earlier artefacts this plan builds on:
revisions 0001-0005 and the `testclock` branch, `ops_core.persistence`/`privileges`/`settings`/`routing`/`contracts`,
the six services, `scripts/skeleton.py`, `tests/e2e/`, and the Plan D/F unit tests.

## Global Constraints

Carried from Plan F's header, verbatim (rewrapped to 120 characters; "Plan F" and "T11" there mean the plan that
wrote them, and the Plan G additions below say how each applies here):

- **Debt before code (SA:698).** The Plan F debt list (below) is committed in Task 1 before any code changes.
  Nothing not on the list may be shortcut; every line names its owning task.
- **Authority boundaries stay where the spec puts them.** The browser never holds a Keycloak token (BS:350; the
  access token is discarded after the exchange, the refresh token is sealed and used once, at logout); identity is
  the verified `sub` resolved against current memberships on every request (BS:176, BS:348); the API stays the
  identity trust anchor for `create_run` and `record_decision` (SA:450, SA:454); runtime roles still never UPDATE
  `runs.state` or INSERT into audit tables (SA:387); the sweeper writes only the three `memberships` columns AM-20.2
  gives it (`active`, `permission_version`, `synced_at`) and only to deactivate; nothing reactivates a membership
  (SA:107: no tenant-administration surface). Keycloak is never the application role database.
- **Secrets** live only as files under `OPS_SECRETS_DIR` (`kc_client_secret_ops_web`, `kc_client_secret_ops_view_users`,
  the new `kc_client_secret_ops_test_admin` and `api_session_key`), declared in `SECRET_NAMES` and in compose's
  top-level `secrets:`. No secret, token, authorization code, session ID, CSRF token, cookie value, refresh token or
  logout token in an environment variable, URL the API builds, log line, exception message, assertion operand,
  evidence file, migration string, report or review. Live tests bind responses before asserting and never put a
  header or cookie in an assert operand (Plan B's lesson).
- **Every redirect target is exact.** The only redirect URI is `{OPS_PUBLIC_BASE_URL}/auth/callback` with the base
  `http://localhost:8000` in dev (`127.0.0.1` is refused by Keycloak, spike §1); the only post-logout target is
  `{OPS_PUBLIC_BASE_URL}/`; the API never redirects to a URL taken from a request parameter.
- **Server-to-server calls to Keycloak use `settings.keycloak().server_url`** (`127.0.0.1`, keep-alive): `localhost`
  resolves to `::1` first on this machine and costs about 2 s per new connection, which alone would exhaust the
  admin check's 2 s budget (spike §3). Browser-facing URLs (the authorization endpoint) keep `localhost`, the
  registered host. `iss` is identical either way (`KC_HOSTNAME`).
- **Clock.** Every session, login-state and `jti` comparison in SQL uses `app.current_time()` (SA:157, R126); column
  defaults stay `now()`. Python compares nothing about expiry itself: a session is live only if the one
  `UPDATE … RETURNING` in `DbStore.live_session` returned a row.
- **One string per function**, binds and the ISC004 rule exactly as in Plan E (a colon after a quote is a bind;
  `tests/plan_e/test_transitions_table.py` scans every revision, including 0005).
- **Loopback only, async only, autocommit connections with explicit units** (Plan D rulings 15, 23, 24): unchanged.
  The sweeper follows the worker's process shape (one loop connection, one probe connection, uvicorn health server
  on a selector loop).
- **Live tests never touch the dev databases**, run against `ops_test`/`incident_test` under `PROFILE=test`, and
  restore every Keycloak user they disable (`finally`); they never delete a realm object. The Keycloak container
  reaches the host API at `host.docker.internal:8000` (spike §2); nothing on the host routes through that name (T05
  review note).
- **Tests:** unit tests in `tests/plan_f/` (DB-free; the API tests use `TestClient` with a fake store and a fake OIDC
  client; token tests sign with a throw-away RSA key), live tests in `tests/e2e/` gated by `OPS_LIVE=1`;
  `tests/plan_d/test_api.py` and `tests/plan_b/test_realm_template.py` are updated where an interface they pin
  changes, never deleted. No xfail or skip except the live gate (BS:597).
- **Comments** per `docs/CODE_COMMENTS.md`; ≤120 characters per line (count characters, not bytes: the counting
  command is under the Plan G additions, because it is longer than one line); no `type: ignore`; ruff + mypy strict
  clean; UTF-8 without BOM, LF.
- **Gates:** `uv run ruff format <files> && uv run ruff check --fix <files>` (then
  `uv run ruff check --select ISC004 --fix --unsafe-fixes <revision>` after writing a revision),
  `PYTHONUTF8=1 uv run python scripts/check.py` GREEN after every task,
  `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts` exit 0, and the live suite
  `PYTHONUTF8=1 uv run python scripts/check.py --profile test` after every task that changes a migration, a service,
  the realm or a live test. After a live run: `git checkout -- reports/bootstrap reports/skeleton` (both are
  rewritten by live runs; a task commits the R105 file only when it says so). `verify_handoff.py` runs in every
  task's gate step. mypy's incremental cache can report spurious errors after many edits; rerun with
  `--no-incremental` before treating one as real.
- **No interim red across tasks.** Task 2 changes the realm export and the `sessions` table under Plan D's API, which
  gains its session code only in Task 4; nothing is red between tasks: the API keeps the bearer path, the autouse
  `fresh_memberships` fixture (function-scoped, so it runs after the module-scoped skeleton starts and before each
  test body) keeps every live test, R105 included, inside the 120 s window until Task 5 gives the skeleton a
  sweeper, and from Task 5 (R105) and Task 6 (the auth module) the skeleton modules opt out of the stamp
  (`@pytest.mark.sweeper_stamps`) and age the rows first, so they prove the sweeper's stamping rather than the
  fixture's. Inside Task 2 the newest-revision unit test is red between Step 1 and Step 3 only.
- **Commits:** one logical group per step; messages free of any attribution trailer; never push; never
  `docker compose down -v`; never change system settings; never drop a role, database, persona or Keycloak object
  (the test databases excepted). `scripts/bootstrap_dev.py down` then `up` (a realm re-import that keeps the
  PostgreSQL volume) is allowed and required once, in Task 2.

Plan G additions (they win over the carried text where the two differ):

- **Debt before code, here:** the Plan G debt list ("Declared debt and errata" below) is committed in Task 1 Step 1
  before any code change; Plan G touches no realm, no secret and no Keycloak object, so `bootstrap_dev.py` is never
  run and no realm re-import happens.
- **Counting characters** (the carried "Comments" rule): print every line over 120 characters in the given files;
  no output means the files pass.

  ```bash
  uv run python - <files> <<'EOF'
  import sys
  for path in sys.argv[1:]:
      for number, line in enumerate(open(path, encoding="utf-8"), start=1):
          if len(line.rstrip("\n")) > 120:
              print(path, number)
  EOF
  ```

- **Toolchain and locks:** run everything through the locked environment from the repository root
  (`uv run python -m pytest …`, never a bare `pytest`, so `tests` imports as a package); no `uv add`, no `uv lock`
  (`uv.lock` does not change in this plan); Python 3.13, FastAPI 0.143.0, Starlette 1.7.0, psycopg 3.3.6 as locked.
- **Never migrate the dev databases.** Nobody runs `scripts/skeleton.py migrate` or `up` against `ops`/`incident`
  in this plan; the live suite migrates its own `ops_test`/`incident_test`. Migrating the dev database to 0006 is an
  owner input recorded in Task 7 (until then the API and the sweeper refuse to start on it, by design).
- **Scratch objects:** a test that creates anything outside the per-session test databases removes it in `finally`;
  every conversation a live admission test creates is purged with all its rows (`purge_conversation`), because
  revision 0006's downgrade (which a later live module runs) refuses a database that still holds a system message.
- **No secrets in evidence or assert operands:** `reports/admission/t12-admission.txt` holds status codes, counts,
  causes and the seeded tenant's run ids only; `tests/plan_b/test_evidence.py` scans `reports/admission` too.
- **Clock, here:** the admission interval, the record's `expires_at` and its lookup use `app.current_time()` inside
  the unit (ruling 11); the record table's `created_at` default is `clock_timestamp()` (ruling 4) and every other
  default stays `now()`.
- **Tests, here:** Plan G's unit tests live in `tests/plan_g/` (added to `testpaths` in Task 1), its live tests in
  `tests/e2e/`; `tests/plan_d/test_api.py`, `tests/plan_f/test_api_auth.py`, `tests/plan_e/test_transitions_table.py`,
  `tests/plan_f/test_sweeper.py`, `tests/plan_b/test_evidence.py`, `tests/e2e/conftest.py` and the two live modules
  that post to the API are updated in the task that changes the interface they pin, never deleted.
- **No `noqa: BLE001`** and no broad `except Exception` added by this plan (the one existing `except Exception` in
  the back-channel route is Plan F's and stays).
- **No interim red, here:** every task ends with the dev gate GREEN at the stated counts and, where it changes a
  migration, a service or a live test, the live gate GREEN too. Task 4 keeps the three pre-T12 store methods beside
  the new units so Task 2's routes keep working; Task 5 switches the routes and deletes them; Task 5 also adds the
  key to the two live modules that post to the API, so the live suite is never red between tasks.
- **Line numbers** in "Modify" lines and in the edit headings are those of the file as the previous task left it
  (the current tree for a file no earlier Plan G task touched).
- **Counts.** Today (b4e97bc) the dev gate is `679 passed, 95 skipped`; 74 of the 95 skips are live tests, so the
  live gate is `753 passed, 21 skipped` (Plan F's close: dev 663/95, live 737/21; the 16 tests added since are unit
  tests). Task 1 Step 1 records both before any change; if either differs, every expected count below shifts by the
  same difference and the report says so.

## Review Focus

1. **One key reused on another conversation, or with a changed body, must be a 409, never the other request's
   answer** (a client that reuses keys per session, not per request). Pinned in Task 4
   (`test_the_fingerprint_ignores_layout_but_not_the_path_or_the_body`), Task 5
   (`test_a_replay_is_the_same_bytes_and_a_reused_key_is_a_conflict`) and live in Task 6 (R016).
2. **An `Idempotency-Key` with a space, too short, too long or empty must be a 422 before anything is read**
   (a proxy may fold or trim it, and the replay would then miss). Pinned in Task 4
   (`test_a_key_is_8_to_128_visible_ascii_characters`) and Task 5
   (`test_a_malformed_key_is_refused_before_anything_is_read`).
3. **A body whose `Content-Length` lies low, or a chunked body, must not get past 64 KiB, and a route that reads no
   body must not run for one.** Pinned in Task 1 (`test_a_content_length_that_lies_low_is_caught_by_counting`,
   `test_a_chunked_body_over_the_limit_is_refused_before_the_route_runs`,
   `test_a_body_refusal_through_the_app_creates_nothing_and_names_its_request`) and live in Task 6 (R115).
4. **A text that names the form's asset among others agrees; a text that names only other assets, or another window,
   asks** (the reader's "Compare B22 with A17" is not a conflict; "Investigate B22" with A17 in the form is). Pinned
   in Task 3 (`test_text_and_fields`, its rows "Compare B22 with A17, last 24 hours." and "Investigate B22 over the
   last 24 hours.", and `test_questions_name_what_disagreed`) and live in Task 6 (R018).
5. **A member whose membership was revoked must not replay a recorded success** (BS:264: an authenticated current
   session): identity runs before the record. Pinned in Task 5
   (`test_a_revoked_member_cannot_replay_a_recorded_success`). A clarification reply with a stale
   `expected_version`, the sixth candidate, is pinned too: Task 4
   (`test_a_reply_binds_to_the_outstanding_question_and_its_version`) and Task 5
   (`test_a_stale_clarification_reply_is_a_recorded_409`).

## Rulings (decisions the spec leaves to this plan)

Each answers the fact sheet's question of the same subject (fact sheet §5), cites what the spike measured, and names
the cost if wrong. Where a ruling reads the spec one of two ways it is proposed to the owner as an erratum (numbered
35-43 under "Declared debt and errata"). Executors do not re-litigate them.

1. **Idempotency-Key is required on every `POST /api/v1/*` mutation.** `POST /api/v1/conversations`,
   `POST /api/v1/conversations/{id}/messages`, `POST /api/v1/proposals/{id}/decisions` and the new
   `POST /api/v1/runs/{id}/clarifications` require it; `/auth/logout` (idempotent by construction: a second call
   has no session) and `/auth/backchannel-logout` (Keycloak's, T11 review note 3) stay exempt, and so does the
   test-only `/internal/faults/{kind}`. A missing or malformed header is 422 `INVALID_INPUT` "Idempotency-Key header
   is required (8–128 visible ASCII characters)"; the shape is 8-128 characters, each in `0x21-0x7E`. — Why: BS:264
   says every mutation, and T11 deferred exactly this (Plan F ruling 20); a key that may contain a space or a
   non-ASCII character can be folded or re-encoded by a proxy, and the replay would miss its record. — Cost if
   wrong: every client sends one header; R105, `test_auth_live.py` and the Plan D/F unit tests send a `uuid4()`
   from Task 5 on. Erratum 35 records the `/auth/*` exemption against BS:264's "every mutation".
2. **Scope = (tenant, subject, route template, key); the path parameters are in the fingerprint.** `route` is the
   method plus the template (`POST /api/v1/conversations/{conversation_id}/messages`), so one key reused on another
   conversation is the same scope with another fingerprint: 409 `IDEMPOTENCY_CONFLICT`, as is a changed body. The
   bearer and the cookie identity of one `(issuer, subject)` share the scope. — Why: BS:244 lists tenant, subject,
   route and key; a concrete path would make one key silently valid once per conversation, which is the client bug
   R016 exists to catch; the subject is the person, not the credential. — Cost if wrong: a client that reuses keys
   across conversations gets 409s it did not expect (by design; review focus 1).
3. **Fingerprint = `canonical_sha256({"path": {...}, "body": <validated model dump or null>})`.** Computed in the API
   after the body parses (a body that fails to parse gets no fingerprint and no record). — Why: canonical JSON v1 is
   the project's one hash (`ops_core.canonical`), the validated model is NFC-normalised and stripped, so whitespace,
   key order and a reformatted retry replay (spike §5 showed the body parser is the only layer that sees the
   request as the API understands it). — Cost if wrong: a retry with a semantically different but byte-equal body
   would be impossible to tell apart; none exists under the strict models.
4. **The record is the response.** `app.idempotency_request(tenant_id, subject, route, key, fingerprint_sha256,
   status_code smallint, response jsonb, created_at DEFAULT clock_timestamp(), expires_at, PRIMARY KEY (tenant_id,
   subject, route, key))`, no RLS (SA:523), owned by `migrator`; `api` sel+ins, `sweeper` sel+del (erratum 25
   extended, erratum 36). A replay returns the stored status and body, rendered with sorted keys so the bytes are
   the first answer's; a replayed 202 says `QUEUED` even when the run moved on. The row is written last in the unit
   (SA:188) by a target-less `INSERT … ON CONFLICT DO NOTHING`. — Why: BS:299 asks for "the same logical result", and
   `api` holds no UPDATE (SA:429), so there is no "in progress" row to complete; the full answer is the only thing a
   replay can return without re-deciding (spike §1: write-once works with SELECT + INSERT; jsonb reorders keys, so
   the rendering is canonical). — Cost if wrong: a client that wants the current state follows `status_url`.
5. **What gets a record: the router's verdict and the route's own decisions.** 201/202/200, 409 `SLOT_OCCUPIED`,
   409 `VERSION_CONFLICT`, 404 for a conversation, run or proposal the caller cannot see, 422 router rejections and
   429 are recorded; 401, 403, the 422s of header, body size and body parse, 409 `IDEMPOTENCY_CONFLICT` and 503 are
   not. Rule of thumb in the code: the router's verdict is recorded; everything before the router is not. — Why:
   AM-16's reject row writes "nothing … except the idempotency record"; a refusal of identity or shape decided
   nothing, and a 503 committed nothing (BS:681). — Cost if wrong: a replay of a recorded 404 stays 404 after the
   conversation appears (it cannot appear under the same id: ids are server-made).
6. **In-flight duplicates wait on an advisory lock on the scope.** The unit's first statement is
   `SELECT pg_advisory_xact_lock(hashtextextended('<tenant>|<subject>|<route>|<key>', 0))`, then the lookup
   (`expires_at > app.current_time()`): a hit replays, a miss proceeds. The loser of a race waits, then replays the
   winner's record. The lock comes before every table lock (erratum 37 adds it to SA:188's order). The final
   `ON CONFLICT DO NOTHING` is belt and braces: rowcount 0 rolls the unit back and the store re-reads; a test proves
   that path with a pre-inserted (expired, unpurged) row. — Why: spike §1 measured both alternatives: with the record
   written last a racing replay gets `SLOT_OCCUPIED` from `create_run` instead of its 202, and with it written first
   it gets a 23505 whose DETAIL prints the tenant, the subject and the key in clear; spike §6 measured the lock as
   available to `api` without a grant. — Cost if wrong: one lock per mutation (microseconds; spike §4 measured a
   whole admission at 6-14 ms).
7. **TTL from settings; lookups ignore expired rows; the sweeper purges them.** `expires_at = app.current_time() +
   make_interval(secs => ttl)`, ttl from `OPS_IDEMPOTENCY_TTL_SECONDS` (default 86400, 60 ≤ ttl ≤ 604800); a fourth
   `DELETE … WHERE expires_at < app.current_time()` in `sync.purge_expired`, no new job type; the sweeper's startup
   `assert_relation` moves to `app.idempotency_request`. — Why: SA:297 fixes 24 h and the test clock must move it
   (spike §3: `api` and `sweeper` hold EXECUTE on `app.current_time()`); SA:346/SA:504 list no purge job, and the
   other three purges already ride the tick. — Cost if wrong: an expired but unpurged row blocks its key until the
   next tick (at most 30 s), answered as a 409 "not reusable yet".
8. **Revision `0006_admission_idempotency`.** Creates the record table (ruling 4) and alters `messages`: `seq bigint
   GENERATED ALWAYS AS IDENTITY NOT NULL` with `UNIQUE (conversation_id, seq)`, a CHECK on the stored kinds
   (ruling 26), `author` nullable with `CHECK ((kind IN ('status_answer','clarification_question')) = (author IS
   NULL))`. The downgrade restores NOT NULL after deleting nothing (it refuses while a system message exists).
   `GRANTS_0006` frozen the 0005 way; `privileges.GRANTS` and `NO_RLS` gain the table; the newest-revision check in
   `tests/plan_e/test_transitions_table.py` covers 0006; the API's lifespan asserts the new relation. — Why: two rows
   of one transaction share `now()` (spike §6), an identity column needs INSERT only where a serial needs USAGE on its
   sequence (spike §6: 42501), and the only `kind` today is `investigate` (fact sheet §3.6), so the CHECK is safe on
   existing rows. — Cost if wrong: a later revision; the dev database needs the owner's migrate (owner input).
9. **The slot rule stays the partial unique index; the API takes no lock for its active-run read.** T12 review note 1
   is satisfied by `runs_one_active_per_conversation … WHERE slot_held` (0002) kept by `_transition`. The read before
   `clarify`/`status_question` is `SELECT run_id, state, state_version FROM app.runs WHERE conversation_id = %s AND
   slot_held ORDER BY created_at DESC LIMIT 1` under the tenant unit. — Why: `api` cannot lock `conversations` (spike
   §6: 42501 in every mode) and an absent run cannot be locked; the index is the authoritative backstop (spike §4:
   10 of 10 races ended one 202, one `SLOT_OCCUPIED`). — Cost if wrong: a concurrent `investigate` can take the slot
   between the read and a stored clarification; the clarification is then answered by a new message that meets the
   409 (benign; a debt line).
10. **A read-only run holds the slot and needs an asset and an interval.** `create_run` sets `slot_held` for both
    intents (fact sheet §3.5); `readonly_answer` uses the same parser as `investigate`, so without an asset or a
    window it is `clarify`, never a 422. Such a run ends FAILED in today's worker (fact sheet §3.13): the live test
    asserts only the admission (202, `runs.intent = 'answer_only'`, the job row); T20 ends it ANSWERED (R114). —
    Why: SA:145 counts every active run; `runs.asset_id`/`start_at`/`end_at` are NOT NULL and `create_run` refuses
    without them. — Cost if wrong: an `ask` blocks an `investigate` in the same conversation until it ends (erratum
    38 against BS:548/R017's "state-mutating").
11. **The interval is resolved once, inside the unit, on the database clock.** `SELECT app.current_time()` in the
    admission unit, then `resolve_interval(hours, now)` (whole seconds); the record keeps the interval, so a replay
    returns it unchanged and `runs.start_at/end_at` never move. A `clarify` stores no interval; the reply resolves its
    own at its admission. — Why: spike §7 measured the API's wall clock 3 days apart from `create_run`'s
    `app.current_time()` under the test clock, which made R018 untestable; spike §3: `api` may call it. — Cost if
    wrong: none for production (the two clocks are equal outside the test profile).
12. **Text versus fields: a deterministic parser in `core/src/ops_core/routing.py`.** `TEXT_ASSET` (an upper-case
    token containing a digit, at most 32 characters), `TEXT_WINDOW` ("last|past N hours|hrs|h|days|d", days × 24)
    and `TEXT_WINDOW_WORD` ("last hour" = 1, "last day" = 24); the first window in the text counts. Asset rules run
    before interval rules and the first disagreement names the one cause: a form asset among the text's ids agrees,
    none of them is `asset_conflict`; no form asset and one id fills it, none is `missing_asset`, two or more is
    `asset_ambiguous`; a form window equal to the text's agrees, different is `interval_conflict`; no form window and
    a text window in 1-168 fills it, outside is `interval_out_of_range`, none is `missing_interval`. `kind=status`
    skips the parser. — Why: BS:297 ("structured fields take precedence only when they agree … ask rather than
    guess") and R018; prose and acronyms never match (no digit), and a lower-case id is not an `AssetId`. — Cost if
    wrong: a stray upper-case token with a digit in prose (a ticket id such as `T12`) asks a question instead of
    starting work, which is the safe direction.
13. **The `clarify` response.** HTTP 200 `{conversation_id, message_id, question_id, cause, question, status:
    "clarification_needed"}`; two `messages` rows in one unit: the requester's (its request kind, text and context,
    `author` = subject) and the question (`clarification_question`, `author` NULL, the cause's template, `context =
    {"cause", "reply_to"}`); no run, no job, no event; the requester answers with a new message (AM-16: it re-enters
    admission). — Why: SA:372 fixes 200 and the stored question; the requester's own row keeps the conversation
    readable. — Cost if wrong: a schema for the body arrives with T26's UI.
14. **`status_question`.** HTTP 200 `{conversation_id, question_id, answer_id, answer, run_id|null, status|null,
    state_version|null}` describing the conversation's latest run by `created_at` and its latest event (`ORDER BY
    sequence DESC LIMIT 1`, the real column of 0001): "This conversation has no runs yet." or "Run {run_id} is
    {state} (version {v}); the last recorded event is {type} at {time}." (`…Z`, whole seconds); two messages
    (`status_question` by the subject, `status_answer` with `author` NULL and `context = {"run_id", "reply_to"}`);
    allowed while the conversation is busy; the parser is not run. — Why: SA:370 ("answered from recorded events and
    state … no run, no job, no run event") and R017. — Cost if wrong: the wording changes with T26.
15. **`clarification_reply` enters through BS:273's `POST /api/v1/runs/{run_id}/clarifications`** with the existing
    `ClarificationReply(question_id, expected_version, context)`. The run must be the caller's tenant's (404), in
    `AWAITING_INPUT` at `expected_version` (else 409 `VERSION_CONFLICT`), and `question_id` must be its latest
    `clarification.requested` event (else 404 "no outstanding clarification"). One unit: a `clarification_reply`
    message ("Clarification: asset {asset_id}, hours {hours}"), a `resume_input` job by target-less `INSERT … ON
    CONFLICT DO NOTHING` (dedup `<run_id>:<question_id>`, `available_at = app.current_time()`; rowcount 0 means the
    question was already answered: 409), `clarification.received` through `persistence.append_event`, the record;
    202 with the accepted body. On the messages route `kind=clarification` is `reject`, 422 "clarification replies go
    to /api/v1/runs/{run_id}/clarifications". The live test stages `AWAITING_INPUT` through the worker role's
    `app.transition_run`; the worker finishes the `resume_input` job unhandled today (fact sheet §3.13). — Why:
    `MessageRequest` has no `question_id` (a schema change would ripple through `build_schemas.py`); `api` holds INSERT
    only on `jobs` (spike §2: a target or `RETURNING` is 42501). — Cost if wrong: erratum 40.
16. **Route table shape.** Frozen dataclasses `AdmissionFacts(kind, text, asset_id, hours, active_run, hint)`,
    `AdmissionDecision(route, cause, asset_id, hours, question)`, `AdmissionRule(name, predicate, route, cause)`;
    `ADMISSION_RULES` first-match-wins in the order status → `kind=clarification` reject → slot reject → the parser's
    clarify → the hint's clarify → investigate → ask; `route_admission(facts)` pure. The API answers 409
    `SLOT_OCCUPIED` from the slot row without calling `create_run`; the index stays the backstop. The hint can only
    turn a run into `clarify`; any other value is ignored; no producer exists (the API passes `None`; debt → T19). A
    one-row `REPLY_RULES` (`route_reply`) is the clarifications route's entry, so R129's walk reaches all six routes
    through the two tables. `GraphRoute` rows arrive with T20. — Why: SA:362, SA:375, R129 ("each of the six routes
    tested … a model hint can only produce clarify"). — Cost if wrong: one more row when T19 adds a hint.
17. **Body limit: a pure ASGI middleware `BodyLimit(app, max_bytes)`.** A declared `Content-Length` over the limit
    (or not a number) is refused without reading; otherwise the body is pre-read and counted, and past the limit
    `read_bounded` raises `BodyTooLarge`, which the middleware turns into the same 422 `INVALID_INPUT` "request body
    exceeds 65536 bytes"; under the limit the bytes are replayed to the app. Every route; limit from
    `OPS_MAX_BODY_BYTES` (default 65536, 1024-1048576); not recorded; `Text` (≤ 4000 characters) stays the content
    limit. — Why: spike §5 measured Starlette's `RequestBodyLimitMiddleware` answering a plain-text 413 after the
    route ran (a conversation was created) and never stopping a route that reads no body; the pre-read shape gave
    the safe 422 with no side effect; BS:301 puts content limits under 422. — Cost if wrong: 64 KiB held per request
    before routing, which is the bound itself.
18. **429 is a per-tenant quota of QUEUED runs.** In the admission unit `SELECT count(*) FROM app.runs WHERE state =
    'QUEUED'` (RLS scopes it, spike §8); at or above `OPS_TENANT_QUEUE_QUOTA` (default 100, 1-10000) an admission
    that would start a run is 429 `RATE_LIMITED` "tenant queue is full" with `Retry-After: 5`, recorded, no run. —
    Why: BS:550 bounds queued work; `api` cannot count across tenants or read `jobs` (spike §8: 42501), so the global
    "100 total" needs a definer or a grant (debt → T13; erratum 39). A status question or a clarification adds
    nothing to the queue and is never a 429. — Cost if wrong: the unit test sets the quota to 1; the live test does
    not exercise 429.
19. **503 and `retryable`.** `retryable: true` only for `psycopg.OperationalError`/`InterfaceError` ("database
    unavailable") and the identity provider's outages (`AdminUnavailable`, `SigningKeysUnavailable`, the token
    endpoint: every `ApiError` that carries 503). `AuthorityViolation`, `st.Internal`, `PersistenceError`,
    `IllegalTransition`, `EventRuleViolation`, any other `psycopg.Error` (a 23505 included) and the catch-all
    `Exception` are 503 `UNAVAILABLE` `retryable: false` "service error", logged once at ERROR with the request id
    and the exception's class name, never its text. Starlette's `HTTPException`: 404 → `NOT_FOUND` "no such route",
    405 → `INVALID_INPUT` "method not allowed" with `Allow`, anything else → 422 `INVALID_INPUT` "request refused". —
    Why: BS:562 ("do not retry … as transient errors") and BS:301; spike §5: FastAPI's 404/405 answer `{"detail": …}`
    and an unhandled exception a plain-text 500; Starlette re-raises after the catch-all, so uvicorn still logs the
    traceback through the redaction filter. — Cost if wrong: a client stops retrying a defect a restart would fix.
20. **`request_id`.** An ASGI middleware `RequestId` assigns `uuid4()` per request (a client's `X-Request-Id` is
    ignored), keeps it in `scope["state"]` (`request.state.request_id`), echoes it as `X-Request-Id` on every
    response, and every error body carries it; error log lines include it. `safe(request, status, code, message, *,
    retryable=False)` takes the id from the request; `ApiError` is unchanged. — Why: today's id is random per error
    and logged nowhere (fact sheet §3.1), so an operator cannot match a client's report to the log. — Cost if wrong:
    none; the header is additive.
21. **Check order on the messages route.** identity (401) → CSRF/origin (403) → role `requester` (403) →
    Idempotency-Key shape (422) → body parse (422) → fingerprint → unit: advisory lock → record lookup (replay, or 409
    `IDEMPOTENCY_CONFLICT`) → conversation in tenant (404) → quota count → active-run read → router → effect → record
    → commit. The body size is checked first of all, because it is middleware (erratum 43). A replay by a subject
    whose membership was revoked fails at identity (401) and never reaches the record. Conversations: identity →
    CSRF → key → unit. Decisions: `enabled_identity` → key → body → unit (lock, lookup, proposal 404, reviewer check
    403 unrecorded, revision 409, `record_decision(…, idempotency_key=key)`, record). Clarifications: identity → CSRF
    → `requester` → key → body → unit (ruling 15). — Why: BS:264 ("an authenticated current session") and BS:301
    (no unauthorized existence leak before the role check). — Cost if wrong: a 401/403 learns nothing either way.
22. **Conversations.** No body; 201 `{conversation_id}`; fingerprint over `{"path": {}, "body": null}`; a replay
    returns the same id. — Why: BS:270, fact sheet §5 Q24. — Cost if wrong: none.
23. **The 202 body keeps its keys.** `conversation_id, message_id, run_id, status, state_version, status_url,
    events_url`; `stream_url` is omitted until the stream route exists (debt → T27); `ask` answers 202 with the same
    body. — Why: BS:299 lists "authorized relative status/stream locations"; a URL that 404s would be a lie. — Cost
    if wrong: T27 adds one key.
24. **Crash before commit (R015, DoD 1) through a test-profile-only fault route.** `POST /internal/faults/{kind}` with
    `{"count": n}`, mirroring incident-sim's; outside `PROFILE=test` the route is not registered (the safe 404).
    The API implements `drop_before_commit` only: the store raises `persistence.PersistenceError("fault:
    drop_before_commit")` after the message and `create_run` and before the record and the commit, so the unit rolls
    back and the client gets 503 `retryable: false`. The live test proves with the superuser that no message, run,
    job or record exists, replays the same key (202: nothing was recorded) and finds the job. — Why: R098 (fault
    hooks are test-harness-only; `core.testing.faults` refuses to exist outside the test profile) and the fact
    sheet's §3.10 (the API had no hook). — Cost if wrong: the fault route lives under `/internal`, never `/api/v1`.
25. **`supersedes_run_id`** stays validated against the tenant and the conversation by `create_run` (no function
    change). — Why: fact sheet §3.5 measured the function's actual rule; a cross-conversation supersede would break
    the slot's meaning. — Cost if wrong: erratum 41 against SA:450's "tenant/asset".
26. **Stored message kinds.** `investigate`, `ask`, `status_question`, `status_answer`, `clarification_question`,
    `clarification_reply` (revision 0006's CHECK); a Python `StrEnum StoredMessageKind` names them in
    `core/src/ops_core/contracts.py`; `build_schemas.py` does not change (the stored vocabulary is not a request
    schema); the request `MessageKind` stays `investigate, ask, status, clarification`. — Why: T12 review note 2 and
    SA:370/SA:372 name the system kinds; neither spec file lists the whole vocabulary (fact sheet §2.8). — Cost if
    wrong: a revision to add a kind (erratum 42).
27. **Settings.** `AdmissionSettings(max_body_bytes, idempotency_ttl_seconds, idempotency_key_min,
    idempotency_key_max, tenant_queue_quota)` and `settings.admission()` read `OPS_MAX_BODY_BYTES`,
    `OPS_IDEMPOTENCY_TTL_SECONDS`, `OPS_TENANT_QUEUE_QUOTA` with the bounds above (the key bounds are constants 8/128,
    not environment), validated like `sessions()`; `create_app(…, admission=…)` (default: the dataclass's defaults;
    `production_app()` passes `settings.admission()`). — Why: BS:542 ("validated configuration and boundary
    tests"). — Cost if wrong: none.
28. **Tests.** Unit tests in `tests/plan_g/` (`test_settings_admission.py`, `test_limits.py`,
    `test_error_surface.py`, `test_migration_0006.py`, `test_routing_admission.py`, `test_idempotency.py`,
    `test_store_units.py`, `test_api_admission.py`, with `fakes.py`); live tests `tests/e2e/test_migration_0006_live.py`
    and `tests/e2e/test_admission_live.py` (R015 fault, R016 replay and conflict, R017 the two-connection race and the
    API-level 409, R018 the clock advance, R129 the six routes with the staged clarification reply, R115 a sample of
    live codes) writing `reports/admission/t12-admission.txt` (header plus one line per proof, responses bound before
    asserting, no ids of another tenant); `tests/plan_b/test_evidence.py` gains the root; R105, `test_auth_live.py` and
    the Plan D/F API unit tests send keys. — Why: Plan D ruling 26's layout. — Cost if wrong: none.
29. **Handoff close-out (Task 7).** T12 → `DONE` with a review note; R015, R016, R017, R018, R115, R129 →
    `IMPLEMENTED_LOCALLY_VERIFIED` / `RECORDED_LOCALLY_LIVE` with evidence paths; `SESSION_STATE.md` (Plan G section:
    rulings made during execution, errata 35-43, the debt lines, the dev database needs 0006); `STATUS.md`;
    `docs/PROJECT_HISTORY.md` §24 (the closing section becomes §25); `api/README.md`;
    `docs/runbooks/walking-skeleton.md` (revision 0006 before `up`); `docs/runbooks/dev-topology.md` (the request flow
    with the key); `handoff/BUILD_BACKLOG.md` (T12 checked); the plan's own checkboxes. Gates: both `check.py` profiles
    GREEN and `verify_handoff.py` exit 0. — Why: the T11 close-out's shape. — Cost if wrong: none.
30. **Comments** follow `docs/CODE_COMMENTS.md` (why, not what; the spec reference on each rule); lines ≤ 120
    characters counted as characters; UTF-8 without BOM, LF; `ruff format`, `ruff check`, mypy strict on `src/`; no
    `noqa: BLE001`. — Why: the project's standard. — Cost if wrong: a review round.

## Declared debt and errata

### Debt list (committed in Task 1 Step 1, before coding)

Appended to `SESSION_STATE.md` as a new section `## Plan G debt list (T12; committed before coding) [R6-B7]`
immediately after the `## Plan F debt list …` section (before `## Environment (observed)`), verbatim:

```markdown
Allowed shortcuts in T12, each with its owning task:
- the global queued-work bound (BS:550 "100 total") is not enforced: `api` can count only its own tenant's runs and
  cannot read `jobs` (Plan G spike §8); a per-tenant quota of QUEUED runs (`OPS_TENANT_QUEUE_QUOTA`) stands in → T13;
- no producer of a model hint exists: the admission router takes `hint` and the API passes `None` → T19;
- the 202 body carries no `stream_url` until the stream route exists → T27;
- the worker finishes a `resume_input` job unhandled and ends an `answer_only` run FAILED (no ANSWERED path yet), so
  the clarification reply and the read-only admission are proved at the API boundary only → T20 (R042, R114);
- nothing in the worker asks for clarification yet, so the live test stages `AWAITING_INPUT` through the worker
  role's `transition_run` → T20;
- the API reads the active run without a lock before a clarification or a status answer: a concurrent
  `investigate` may take the slot between the read and a stored clarification, which the reply then meets as a 409
  (benign; `api` can lock neither `conversations` nor an absent run) → T21, which owns the slot's other doors;
- `api` may INSERT any job type (the column grant cannot restrict `type`, Plan G spike §2); the API inserts
  `resume_input` only, by code → T13/T22;
- the dev database stays at revision 0005 until the owner migrates it to 0006; until then the API and the sweeper
  refuse to start on it → owner input;
- `feedback` (named for T12 in `privileges.py` and the Plan E debt list) is not created: its endpoint (BS:282) is in
  T21's instructions → T21;
- the clarify, status-answer and accepted bodies have no JSON Schema under `schemas/` (no response has one yet) → T26;
- the API's fault route implements `drop_before_commit` only; the other BS:405 faults → T13.
```

### Errata proposed to the owner (numbered on from Plan F's 34)

The spec text stays authoritative until the owner decides; each line names the text it amends.

35. **BS:264** ("Every mutation requires … `Idempotency-Key`"): met for every `/api/v1` mutation; `POST /auth/logout`
    (idempotent by construction) and `POST /auth/backchannel-logout` (Keycloak's, T11 review note 3) are exempt by
    design, and so is the test-profile `POST /internal/faults/{kind}` (ruling 1).
36. **SA:429** (AM-20.2 row `idempotency_request`: `sweeper` "del (expired)"): the sweeper also holds SELECT, because
    a DELETE with a WHERE reads the row (erratum 25 extended; spike §1 measured 42501 without it) (ruling 4).
37. **SA:188** (the lock order): "idempotency scope advisory lock" is the first entry, before the asset guard
    advisory lock; idempotency rows are still written last (ruling 6).
38. **BS:548** ("One state-mutating run per conversation") and **R017** ("Only one active mutating run"): a read-only
    (`answer_only`) run holds the conversation slot too, as SA:145's active states and `create_run` already make it,
    and it needs an asset and an interval like an investigation (ruling 10).
39. **BS:550** ("Queued work | 100 total initially; bounded tenant quotas"): T12 enforces the tenant quota (100 QUEUED
    runs per tenant by default); the global bound needs a cross-tenant count `api` cannot make and moves to T13
    (ruling 18).
40. **SA:369** (AM-16 `clarification_reply` row): the route's entry is BS:273's `POST /api/v1/runs/{id}/clarifications`
    with `ClarificationReply`; on the messages route `kind=clarification` is `reject` (422) (ruling 15).
41. **SA:450** (`create_run`: "`supersedes_run_id` validated against the tenant/asset"): the function validates it
    against the tenant and the conversation, and T12 keeps that rule (ruling 25).
42. **BS:230** ("immutable message sequence … unique `(conversation_id, sequence)`") with **SA:370/SA:372**: the
    sequence is `messages.seq`, one identity over the table (unique per conversation, increasing, gaps allowed); the
    stored kinds are `investigate`, `ask`, `status_question`, `status_answer`, `clarification_question`,
    `clarification_reply`, and `author` is NULL exactly for the two system kinds (rulings 8, 26).
43. **BS:301** (the status mapping): a wrong method keeps 405 with the code `INVALID_INPUT` and the `Allow` header; the
    body limit answers 422, never 413, and it is checked before identity because it runs as middleware, so no route
    or dependency ever reads an oversized body (rulings 17, 19, 21).

## File structure

- `core/src/ops_core/settings.py` (Task 1): `AdmissionSettings`, `admission()`.
- `api/src/ops_api/limits.py` (new, Task 1): `RequestId`, `BodyLimit`, `BodyTooLarge`, `read_bounded`,
  `request_id_of`, `safe_response`.
- `api/src/ops_api/app.py` (Tasks 1, 2, 5): the handlers (1), the 0006 guard (2), the key, the routes and the fault
  route (5).
- `migrations/app/versions/0006_admission_idempotency.py` (new, Task 2): the record table, `messages.seq`, the
  CHECKs.
- `core/src/ops_core/privileges.py` (Task 2): the `idempotency_request` row, `NO_RLS`, the docstring.
- `sweeper/src/ops_sweeper/sync.py`, `main.py` (Task 2): the fourth purge, the startup guard.
- `core/src/ops_core/routing.py` (Task 3): `ADMISSION_RULES`, `REPLY_RULES`, the parser, the templates.
- `core/src/ops_core/contracts.py` (Task 3): `StoredMessageKind`, `SYSTEM_MESSAGE_KINDS`.
- `api/src/ops_api/idempotency.py` (new, Task 4): key, scope, fingerprint, `idempotent()`, verdict rendering.
- `core/src/ops_core/persistence.py` (Task 4): `current_time`, `insert_job_untargeted`, `latest_active_run`,
  `latest_run`, `latest_event`, `queued_count`.
- `api/src/ops_api/store.py` (Tasks 4, 5): `Unit`, `AdmissionStore`, `DbUnit`, `DbStore` (4); the pre-T12 methods go
  (5).
- `tests/plan_g/fakes.py` (new, Task 4): `StubVerifier`, `FakeUnit`, `FakeStore` over the real orchestration.
- `tests/e2e/conftest.py` (Task 6): `PURGE_ORDER` gains the record; `purge_conversation`.

## Task overview

- **Task 1:** the debt list; `AdmissionSettings`; `RequestId` and `BodyLimit`; the safe error surface;
  `tests/plan_g` on `testpaths`. Tests: `test_settings_admission.py` 5, `test_limits.py` 7, `test_error_surface.py` 7.
  Dev gate after: 698 passed, 95 skipped.
- **Task 2:** revision 0006; the matrix row; the sweeper's purge and guard; the API's guard. Tests:
  `test_migration_0006.py` 3, `test_transitions_table.py` +1 (parametrised), `test_sweeper.py` +1; live
  `test_migration_0006_live.py` 3. Dev gate after: 703 passed, 98 skipped.
- **Task 3:** the router table, the parser, `StoredMessageKind`. Tests: `test_routing_admission.py` 26. Dev gate
  after: 729 passed, 98 skipped.
- **Task 4:** `idempotency.py`; the persistence helpers; `AdmissionStore`/`DbUnit`; the shared fake. Tests:
  `test_idempotency.py` 8, `test_store_units.py` 12. Dev gate after: 749 passed, 98 skipped.
- **Task 5:** the key dependency; the routes over the units; the clarifications route; the fault route; the Plan D/F
  unit tests and the two live callers send keys. Tests: `test_api_admission.py` 16. Dev gate after: 765 passed, 98
  skipped.
- **Task 6:** live proof and evidence; the purge helper; the evidence root; R105 re-run. Tests: live
  `test_admission_live.py` 6. Dev gate after: 765 passed, 104 skipped.
- **Task 7:** handoff records, errata, documents, final gates. No tests.

The live gate (`check.py --profile test`) after Tasks 1, 2, 4, 5 and 6: 772/21, 780/21, 826/21, 842/21 and 848/21
passed/skipped (the dev count plus 74 live tests today, 77 after Task 2, 83 after Task 6).

---

### Task 1: Debt before code — admission settings, request ids, the body limit and the safe error surface

**Files:**
- Modify: `SESSION_STATE.md` (new debt section after `## Plan F debt list …`), `pyproject.toml:48-51` (`testpaths`),
  `core/src/ops_core/settings.py:281-282` (insert before `class Urls`), `api/src/ops_api/app.py:6-9`
  (docstring), `:18-20`, `:27-32`, `:34-37` (imports), `:56-62` (`safe`), `:113-116` (`create_app` signature),
  `:140-141` (middlewares), `:211-215`, `:222-227`, `:231-245` (handlers), `:262-264` (readiness), `:603-604`
  (`production_app`)
- Create: `api/src/ops_api/limits.py`, `tests/plan_g/__init__.py`, `tests/plan_g/test_settings_admission.py`,
  `tests/plan_g/test_limits.py`, `tests/plan_g/test_error_surface.py`

**Interfaces:**
- Consumes: `ops_core.contracts.ErrorCode`, `SafeError`; `ops_core.settings.env_int`, `SettingsError`;
  `tests.plan_d.test_api.FakeStore`, `StubVerifier`, `auth`; `tests.plan_f.auth_fakes.fake_auth`.
- Produces: `ops_core.settings.AdmissionSettings(max_body_bytes=65536, idempotency_ttl_seconds=86400,
  idempotency_key_min=8, idempotency_key_max=128, tenant_queue_quota=100)` (frozen dataclass) and
  `settings.admission() -> AdmissionSettings`.
- Produces: `ops_api.limits.REQUEST_ID_HEADER = "X-Request-Id"`, `BodyTooLarge(Exception)`,
  `request_id_of(scope: Scope) -> UUID`, `safe_response(request_id: UUID, status: int, code: ErrorCode, message: str,
  *, retryable: bool = False, headers: dict[str, str] | None = None) -> JSONResponse`, `RequestId(app)`,
  `read_bounded(receive, max_bytes: int) -> bytes`, `BodyLimit(app, max_bytes: int)`.
- Produces: `ops_api.app.safe(request: Request, status: int, code: ErrorCode, message: str, *, retryable: bool =
  False) -> JSONResponse`; `create_app(verifier, store_factory, auth_factory, *, admission: AdmissionSettings | None
  = None)`.

- [ ] **Step 1: Record the baseline and commit the debt list (before any code)**

Run `PYTHONUTF8=1 uv run python scripts/check.py` → `CHECK: GREEN` with pytest `679 passed, 95 skipped`; with the
dev stack up and `uv run python scripts/skeleton.py status` showing every process down, run
`PYTHONUTF8=1 uv run python scripts/check.py --profile test` → `CHECK: GREEN` with `753 passed, 21 skipped`, then
`git checkout -- reports/bootstrap reports/skeleton`. Record both lines in the report (Global Constraints, "Counts").

Append the debt-list block from "Declared debt and errata" to `SESSION_STATE.md` as the section
`## Plan G debt list (T12; committed before coding) [R6-B7]`, immediately after the `## Plan F debt list …` section
and before `## Environment (observed)`. Then:

```bash
git add SESSION_STATE.md
git commit -m "docs: declare Plan G's shortcuts before coding (T12 debt list)"
```

- [ ] **Step 2: Put `tests/plan_g` on the test path**

In `pyproject.toml` replace

```toml
testpaths = [
  "tests/plan_a", "tests/plan_b", "tests/plan_c", "tests/plan_d", "tests/plan_e", "tests/plan_f",
  "tests/e2e",
]
```

with

```toml
testpaths = [
  "tests/plan_a", "tests/plan_b", "tests/plan_c", "tests/plan_d", "tests/plan_e", "tests/plan_f", "tests/plan_g",
  "tests/e2e",
]
```

and create `tests/plan_g/__init__.py` as an empty file.

- [ ] **Step 3: Write the failing settings test**

Create `tests/plan_g/test_settings_admission.py`:

```python
"""The T12 admission settings (Plan G ruling 27): BUILD_SPEC §17's starting defaults, each environment variable read
and held inside its bounds (BS:542 "validated configuration").

Catches: a body limit of zero or a gigabyte, a replay window shorter than a client's retry or longer than a week,
a quota that admits nothing, a non-integer read as a default, and key bounds that drift from the documented 8-128.
"""

import pytest
from ops_core import settings
from ops_core.settings import AdmissionSettings, SettingsError

NAMES = ("OPS_MAX_BODY_BYTES", "OPS_IDEMPOTENCY_TTL_SECONDS", "OPS_TENANT_QUEUE_QUOTA")


@pytest.fixture(autouse=True)
def clean(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in NAMES:
        monkeypatch.delenv(name, raising=False)


def test_defaults_are_the_spec_starting_values() -> None:
    assert settings.admission() == AdmissionSettings(
        max_body_bytes=65536,
        idempotency_ttl_seconds=86400,
        idempotency_key_min=8,
        idempotency_key_max=128,
        tenant_queue_quota=100,
    )
    assert AdmissionSettings() == settings.admission()  # what create_app uses when a test passes nothing


@pytest.mark.parametrize(
    ("name", "field", "low", "high"),
    [
        ("OPS_MAX_BODY_BYTES", "max_body_bytes", 1024, 1048576),
        ("OPS_IDEMPOTENCY_TTL_SECONDS", "idempotency_ttl_seconds", 60, 604800),
        ("OPS_TENANT_QUEUE_QUOTA", "tenant_queue_quota", 1, 10000),
    ],
)
def test_each_variable_is_read_and_bounded(
    monkeypatch: pytest.MonkeyPatch, name: str, field: str, low: int, high: int
) -> None:
    for good in (low, high):
        monkeypatch.setenv(name, str(good))
        assert getattr(settings.admission(), field) == good
    for bad in (low - 1, high + 1):
        monkeypatch.setenv(name, str(bad))
        with pytest.raises(SettingsError) as refused:
            settings.admission()
        assert str(refused.value) == f"{name} must be between {low} and {high}"  # the bounds, never the value


def test_a_non_integer_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPS_MAX_BODY_BYTES", "64KiB")
    with pytest.raises(SettingsError):
        settings.admission()
```

Run: `uv run python -m pytest tests/plan_g/test_settings_admission.py -q`
Expected: `1 error in` (`ImportError: cannot import name 'AdmissionSettings' from 'ops_core.settings'`).

- [ ] **Step 4: Add the admission settings**

In `core/src/ops_core/settings.py` insert, immediately before `@dataclass(frozen=True)` / `class Urls:` (after
`admission_check_timeout()`):

Edit 1 (old lines 281-282), replace:

```python
@dataclass(frozen=True)
class Urls:
```

with:

```python
@dataclass(frozen=True)
class AdmissionSettings:
    """The admission limits (BUILD_SPEC §17: starting defaults in validated configuration, BS:542).

    The key bounds are constants, not environment: they are part of the API contract a client codes against
    (Plan G ruling 1), while the body limit, the replay window and the tenant quota are deployment choices.
    """

    max_body_bytes: int = 65536  # BS:546: 64 KiB inbound body
    idempotency_ttl_seconds: int = 86400  # SA:297: the 24 h request-dedup replay window
    idempotency_key_min: int = 8
    idempotency_key_max: int = 128
    tenant_queue_quota: int = 100  # BS:550: queued work, as a per-tenant bound (ruling 18)


def _bounded(name: str, default: int, low: int, high: int) -> int:
    """An integer variable inside [low, high]; the message names the bounds, never the value."""
    value = env_int(name, default)
    if not low <= value <= high:
        raise SettingsError(f"{name} must be between {low} and {high}")
    return value


def admission() -> AdmissionSettings:
    """`OPS_MAX_BODY_BYTES`, `OPS_IDEMPOTENCY_TTL_SECONDS` and `OPS_TENANT_QUEUE_QUOTA`, each bounded (ruling 27)."""
    return AdmissionSettings(
        max_body_bytes=_bounded("OPS_MAX_BODY_BYTES", 65536, 1024, 1048576),
        idempotency_ttl_seconds=_bounded("OPS_IDEMPOTENCY_TTL_SECONDS", 86400, 60, 604800),
        tenant_queue_quota=_bounded("OPS_TENANT_QUEUE_QUOTA", 100, 1, 10000),
    )


@dataclass(frozen=True)
class Urls:
```

Run: `uv run python -m pytest tests/plan_g/test_settings_admission.py -q`
Expected: `5 passed`.

- [ ] **Step 5: Write the failing middleware and error-surface tests**

Create `tests/plan_g/test_limits.py`:

```python
"""The two ASGI middlewares of Plan G (rulings 17 and 20): the body limit refuses before any route runs, whatever the
client declares, and every response carries a server-made request id.

Catches: Starlette's own limiter shape (a plain-text 413 after the route already ran, spike §5), a chunked body that
is never counted, a `Content-Length` that lies low and smuggles the rest, a malformed length read as "no limit", a
route that sees a truncated body, a request id taken from the client, and an id that repeats.
"""

import asyncio
import json
from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient
from ops_api.app import create_app
from ops_api.limits import REQUEST_ID_HEADER, BodyLimit, RequestId
from ops_core.settings import AdmissionSettings
from starlette.types import Message, Receive, Scope, Send

from tests.plan_d.test_api import FakeStore, StubVerifier
from tests.plan_f.auth_fakes import fake_auth

LIMIT = 1024


class Echo:
    """An inner app that records whether it ran and answers with the length of the body it read."""

    def __init__(self) -> None:
        self.ran = False

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        self.ran = True
        body = b""
        while True:
            message = await receive()
            body += message.get("body", b"")
            if not message.get("more_body", False):
                break
        payload = json.dumps({"received": len(body)}).encode()
        await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": payload})


def call(app: Any, chunks: list[bytes], headers: list[tuple[bytes, bytes]]) -> tuple[int, dict[str, str], Any]:
    """Drive one HTTP request through a raw ASGI app; returns status, headers and the parsed JSON body."""
    scope = {"type": "http", "method": "POST", "path": "/", "headers": headers, "query_string": b""}
    pending = [{"type": "http.request", "body": c, "more_body": i < len(chunks) - 1} for i, c in enumerate(chunks)] or [
        {"type": "http.request", "body": b"", "more_body": False}
    ]
    sent: list[Message] = []

    async def receive() -> Message:
        return pending.pop(0) if pending else {"type": "http.disconnect"}

    async def send(message: Message) -> None:
        sent.append(message)

    asyncio.run(app(scope, receive, send))
    start = next(m for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    found = {k.decode().lower(): v.decode() for k, v in start["headers"]}
    return start["status"], found, json.loads(body)


def test_a_declared_length_over_the_limit_is_refused_unread() -> None:
    inner = Echo()
    status, _, doc = call(BodyLimit(inner, LIMIT), [b"x" * 10], [(b"content-length", str(LIMIT + 1).encode())])
    assert status == 422 and doc["code"] == "INVALID_INPUT" and doc["message"] == f"request body exceeds {LIMIT} bytes"
    assert not inner.ran


def test_a_chunked_body_over_the_limit_is_refused_before_the_route_runs() -> None:
    inner = Echo()
    status, _, doc = call(BodyLimit(inner, LIMIT), [b"x" * 600, b"x" * 600], [])
    assert status == 422 and doc["retryable"] is False and not inner.ran


def test_a_content_length_that_lies_low_is_caught_by_counting() -> None:
    inner = Echo()
    status, _, _ = call(BodyLimit(inner, LIMIT), [b"x" * 2000], [(b"content-length", b"10")])
    assert status == 422 and not inner.ran


def test_a_malformed_content_length_is_refused() -> None:
    for declared in (b"-1", b"1e3", b"", b"12 34"):
        inner = Echo()
        status, _, _ = call(BodyLimit(inner, LIMIT), [b"{}"], [(b"content-length", declared)])
        assert status == 422 and not inner.ran, declared


def test_a_body_at_the_limit_reaches_the_route_intact() -> None:
    inner = Echo()
    status, _, doc = call(BodyLimit(inner, LIMIT), [b"x" * 500, b"x" * 524], [])
    assert status == 200 and doc == {"received": LIMIT} and inner.ran


def test_every_response_carries_a_fresh_server_made_request_id() -> None:
    planted = "00000000-0000-0000-0000-000000000000"
    seen = set()
    for _ in range(3):
        status, headers, _ = call(RequestId(Echo()), [b"{}"], [(b"x-request-id", planted.encode())])
        assert status == 200 and headers[REQUEST_ID_HEADER.lower()] != planted  # the client's value is ignored
        seen.add(UUID(headers[REQUEST_ID_HEADER.lower()]))
    assert len(seen) == 3


def test_a_body_refusal_through_the_app_creates_nothing_and_names_its_request() -> None:
    fake = FakeStore()
    app = create_app(
        StubVerifier(),
        store_factory=lambda: fake,
        auth_factory=fake_auth,
        admission=AdmissionSettings(max_body_bytes=LIMIT),
    )
    with TestClient(app) as c:
        r = c.post("/api/v1/conversations", headers={"Authorization": "Bearer alex"}, content=b" " * (LIMIT + 1))
    assert r.status_code == 422 and r.json()["message"] == f"request body exceeds {LIMIT} bytes"
    assert r.headers[REQUEST_ID_HEADER] == r.json()["request_id"]
    assert fake.conversations == {}  # spike §5: Starlette's limiter let this route run and create one
```

Create `tests/plan_g/test_error_surface.py`:

```python
"""R115's error surface (BUILD_SPEC §7 safe errors, Plan G rulings 19 and 20): every refusal the framework or a
defect produces is the `{code, message, retryable, request_id}` schema, `retryable` is true only for an outage that
may pass, and the id in the body is the id in the `X-Request-Id` header and in the one log line.

Catches: FastAPI's `{"detail": ...}` 404/405 (spike §5), a plain-text 500, a psycopg DETAIL (a 23505 names the
tenant, the subject and the key, spike §1) or an exception's text reaching the client or the log, a server defect
marked retryable (a retry storm on a bug, BS:562), and a lost connection marked final.
"""

import logging
from collections.abc import Iterator
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ops_api.app import create_app
from ops_api.limits import REQUEST_ID_HEADER

from tests.plan_d.test_api import FakeStore, StubVerifier, auth
from tests.plan_f.auth_fakes import fake_auth

CANARY = "canary-3e9d tenant=3ea79c95 key=k-secret"


@pytest.fixture
def app_and_store() -> Iterator[tuple[FastAPI, FakeStore]]:
    fake = FakeStore()
    yield create_app(StubVerifier(), store_factory=lambda: fake, auth_factory=fake_auth), fake


def safe_shape(body: dict[str, object]) -> bool:
    return set(body) == {"code", "message", "retryable", "request_id"} and UUID(str(body["request_id"])) is not None


def test_an_unknown_path_is_a_safe_404(app_and_store) -> None:
    app, _ = app_and_store
    with TestClient(app) as c:
        r = c.get("/nope")
    assert r.status_code == 404 and safe_shape(r.json())
    assert (r.json()["code"], r.json()["message"]) == ("NOT_FOUND", "no such route")


def test_a_wrong_method_is_a_safe_405_that_names_the_allowed_one(app_and_store) -> None:
    app, _ = app_and_store
    with TestClient(app) as c:
        r = c.get("/api/v1/conversations", headers=auth("alex"))
    assert r.status_code == 405 and safe_shape(r.json()) and r.json()["code"] == "INVALID_INPUT"
    assert r.headers["allow"] == "POST"


def test_a_malformed_path_parameter_is_a_safe_422(app_and_store) -> None:
    app, _ = app_and_store
    with TestClient(app) as c:
        r = c.get("/api/v1/runs/not-a-uuid", headers=auth("alex"))
    assert r.status_code == 422 and safe_shape(r.json()) and r.json()["message"] == "request is not valid"


def test_an_unhandled_exception_is_a_non_retryable_503_and_one_log_line(app_and_store, caplog) -> None:
    caplog.set_level(logging.ERROR, logger="ops_api")
    app, _ = app_and_store

    async def boom() -> dict[str, str]:
        raise RuntimeError(CANARY)

    app.add_api_route("/boom", boom, methods=["GET"])
    # Starlette re-raises after the catch-all answers (spike §5); the client must still get the safe body.
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/boom")
    body = r.json()
    assert r.status_code == 503 and safe_shape(body)
    assert (body["code"], body["message"], body["retryable"]) == ("UNAVAILABLE", "service error", False)
    assert CANARY not in r.text and CANARY not in caplog.text
    lines = [rec.getMessage() for rec in caplog.records if rec.name == "ops_api"]
    assert lines == [f"request {body['request_id']} failed: RuntimeError"]


def test_a_unique_violation_is_a_non_retryable_503_without_its_detail(app_and_store, caplog, monkeypatch) -> None:
    caplog.set_level(logging.ERROR, logger="ops_api")
    app, fake = app_and_store

    async def duplicate(tenant_id: UUID, run_id: UUID) -> None:
        raise psycopg.errors.UniqueViolation(f"duplicate key value violates unique constraint: {CANARY}")

    monkeypatch.setattr(fake, "run", duplicate)
    with TestClient(app) as c:
        r = c.get(f"/api/v1/runs/{uuid4()}", headers=auth("alex"))
    assert r.status_code == 503 and r.json()["retryable"] is False and r.json()["message"] == "service error"
    assert CANARY not in r.text and CANARY not in caplog.text and "UniqueViolation" in caplog.text


def test_a_lost_connection_is_a_retryable_503(app_and_store, monkeypatch) -> None:
    app, fake = app_and_store

    async def gone(tenant_id: UUID, run_id: UUID) -> None:
        raise psycopg.OperationalError(CANARY)

    monkeypatch.setattr(fake, "run", gone)
    with TestClient(app) as c:
        r = c.get(f"/api/v1/runs/{uuid4()}", headers=auth("alex"))
    assert r.status_code == 503 and r.json()["retryable"] is True and r.json()["message"] == "database unavailable"
    assert CANARY not in r.text


def test_the_request_id_header_is_the_body_request_id(app_and_store) -> None:
    app, _ = app_and_store
    with TestClient(app) as c:
        refused = c.get("/api/v1/me")
        served = c.get("/api/v1/me", headers=auth("alex"))
    assert refused.status_code == 401 and refused.headers[REQUEST_ID_HEADER] == refused.json()["request_id"]
    assert served.status_code == 200 and UUID(served.headers[REQUEST_ID_HEADER]) != UUID(refused.json()["request_id"])
```

Run: `uv run python -m pytest tests/plan_g/test_limits.py tests/plan_g/test_error_surface.py -q`
Expected: `2 errors in` (both modules: `ModuleNotFoundError: No module named 'ops_api.limits'`).

- [ ] **Step 6: Write the middlewares**

Create `api/src/ops_api/limits.py`:

```python
"""The API's two pure ASGI middlewares and the one SafeError builder they share with the routes (Plan G rulings 17,
19 and 20; BUILD_SPEC §7 safe errors, §17 the 64 KiB body).

`RequestId` gives every request a server-made id: it is echoed as `X-Request-Id`, carried in every error body and
written on every error log line, so an operator can match a client's report to the log. A client-sent
`X-Request-Id` is never trusted (it would let a caller plant ids in the log). `BodyLimit` refuses an oversized body
before any route runs: Starlette's own `RequestBodyLimitMiddleware` answers a plain-text 413 after the route has
already run and never stops a route that reads no body (spike §5: a conversation was created and still got 413), so
this middleware pre-reads up to the limit and replays the bytes, the shape the spike measured clean.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi.responses import JSONResponse
from ops_core.contracts import ErrorCode, SafeError
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-Id"
_STATE_KEY = "request_id"


class BodyTooLarge(Exception):
    """The body grew past the limit while it was being read (a chunked body declares no length)."""


def request_id_of(scope: Scope) -> UUID:
    """The id `RequestId` stored for this request, or a new one when the middleware did not run.

    The id lives in `scope["state"]`, the dict Starlette's `request.state` wraps, so a handler that only has the
    request (the catch-all, which runs outside the user middleware) still finds it.
    """
    state = scope.setdefault("state", {})
    found = state.get(_STATE_KEY)
    if isinstance(found, UUID):
        return found
    made = uuid4()
    state[_STATE_KEY] = made
    return made


def safe_response(
    request_id: UUID,
    status: int,
    code: ErrorCode,
    message: str,
    *,
    retryable: bool = False,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """A SafeError response: `{code, message, retryable, request_id}` and nothing else (BS:301).

    `retryable` is the caller's statement that the same request may succeed later (ruling 19); a 401 also names the
    Bearer scheme. The id travels as a header too, because the catch-all's response bypasses `RequestId`'s send.
    """
    body = SafeError(code=code, message=message, retryable=retryable, request_id=request_id)
    out = {REQUEST_ID_HEADER: str(request_id), **(headers or {})}
    if status == 401:
        out["WWW-Authenticate"] = "Bearer"
    return JSONResponse(status_code=status, content=body.model_dump(mode="json"), headers=out)


class RequestId:
    """Assign each HTTP request a fresh id and echo it on the response (ruling 20)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = uuid4()
        scope.setdefault("state", {})[_STATE_KEY] = request_id
        header = (REQUEST_ID_HEADER.lower().encode("ascii"), str(request_id).encode("ascii"))

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                # Replace rather than add: `safe_response` already set the same value on error responses.
                kept = [h for h in message.get("headers", []) if h[0].lower() != header[0]]
                message = {**message, "headers": [*kept, header]}
            await send(message)

        await self.app(scope, receive, send_with_id)


async def read_bounded(receive: Receive, max_bytes: int) -> bytes:
    """Read the whole request body, raising BodyTooLarge as soon as it passes `max_bytes`.

    Counting the bytes that arrive, not the declared length, is what stops a `Content-Length` that lies low.
    """
    parts: list[bytes] = []
    total = 0
    while True:
        message = await receive()
        if message["type"] != "http.request":
            break  # a disconnect: the route sees what arrived and its own read fails
        chunk = message.get("body", b"")
        total += len(chunk)
        if total > max_bytes:
            raise BodyTooLarge
        parts.append(chunk)
        if not message.get("more_body", False):
            break
    return b"".join(parts)


class BodyLimit:
    """Refuse a request body over `max_bytes` with the 422 SafeError before any route runs (ruling 17; BS:301 puts
    shape and content limits under 422, and 413 is not in the spec's list)."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = dict(scope.get("headers", [])).get(b"content-length")
        if declared is not None and (not declared.isdigit() or int(declared) > self.max_bytes):
            await self._refuse(scope, receive, send)  # refused without reading a byte
            return
        try:
            body = await read_bounded(receive, self.max_bytes)
        except BodyTooLarge:
            await self._refuse(scope, receive, send)
            return
        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()  # after the body: the disconnect, when the server sends one

        await self.app(scope, replay, send)

    async def _refuse(self, scope: Scope, receive: Receive, send: Send) -> None:
        response = safe_response(
            request_id_of(scope), 422, ErrorCode.INVALID_INPUT, f"request body exceeds {self.max_bytes} bytes"
        )
        await response(scope, receive, send)
```

- [ ] **Step 7: Route every refusal through `safe(request, …)` and install the middlewares**

In `api/src/ops_api/app.py` make these edits (each "replace" block is unique in the file; line numbers are today's):

Edit 1 (old lines 6-9), replace:

```python
Browser sessions (T11): server-side rows, the cookie path beside the bearer path, CSRF and origin checks on browser
mutations, the admin-API enabled check on decision-class mutations, back-channel logout. Idempotency-Key stays declared
debt (T12).
"""
```

with:

```python
Browser sessions (T11): server-side rows, the cookie path beside the bearer path, CSRF and origin checks on browser
mutations, the admin-API enabled check on decision-class mutations, back-channel logout. Plan G (T12): every response
carries a server-made request id, every refusal is the SafeError, and no body over the configured limit reaches a
route.
"""
```

Edit 2 (old lines 18-20), replace:

```python
from typing import Annotated, Any, Protocol
from uuid import UUID, uuid4

```

with:

```python
from typing import Annotated, Any, Protocol
from uuid import UUID

```

Edit 3 (old lines 27-32), replace:

```python
from ops_core import keycloak_admin, persistence, settings
from ops_core.contracts import DecisionRequest, DuplicateKey, ErrorCode, MessageKind, MessageRequest, SafeError, load
from ops_core.keycloak_admin import AdminUnavailable
from ops_core.outcomes import EventRuleViolation
from ops_core.settings import Role
from ops_core.states import IllegalTransition
```

with:

```python
from ops_core import keycloak_admin, persistence, settings
from ops_core.contracts import DecisionRequest, DuplicateKey, ErrorCode, MessageKind, MessageRequest, load
from ops_core.keycloak_admin import AdminUnavailable
from ops_core.outcomes import EventRuleViolation
from ops_core.settings import AdmissionSettings, Role
from ops_core.states import IllegalTransition
```

Edit 4 (old lines 34-37), replace:

```python
from pydantic import ValidationError

from ops_api import auth as au
from ops_api import store as st
```

with:

```python
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from ops_api import auth as au
from ops_api import limits
from ops_api import store as st
```

Edit 5 (old lines 56-62), replace:

```python

def safe(status: int, code: ErrorCode, message: str) -> JSONResponse:
    """Build a SafeError response (a 401 also names the Bearer scheme)."""
    body = SafeError(code=code, message=message, retryable=status == 503, request_id=uuid4())
    headers = {"WWW-Authenticate": "Bearer"} if status == 401 else {}
    return JSONResponse(status_code=status, content=body.model_dump(mode="json"), headers=headers)

```

with:

```python

def safe(request: Request, status: int, code: ErrorCode, message: str, *, retryable: bool = False) -> JSONResponse:
    """A SafeError response carrying this request's id (ruling 20); `retryable` only for a transient outage."""
    return limits.safe_response(limits.request_id_of(request.scope), status, code, message, retryable=retryable)

```

Edit 6 (old lines 113-116), replace:

```python
    auth_factory: Callable[[], AuthDeps | Awaitable[AuthDeps]],
) -> FastAPI:
    """Build the application around a verifier, a store factory and an auth-deps factory (the lifespan runs both)."""

```

with:

```python
    auth_factory: Callable[[], AuthDeps | Awaitable[AuthDeps]],
    *,
    admission: AdmissionSettings | None = None,
) -> FastAPI:
    """Build the application around a verifier, a store factory and an auth-deps factory (the lifespan runs both).

    `admission` carries the body limit and the other T12 bounds; tests pass their own, production passes
    `settings.admission()`, and the default is the spec's starting values (BUILD_SPEC §17).
    """
    bounds = admission or AdmissionSettings()

```

Edit 7 (old lines 140-141), replace:

```python
    app = FastAPI(title="ops-api", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    issuer = settings.keycloak().issuer
```

with:

```python
    app = FastAPI(title="ops-api", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(limits.BodyLimit, max_bytes=bounds.max_body_bytes)
    app.add_middleware(limits.RequestId)  # added last, so outermost: the body refusal carries the request id too
    issuer = settings.keycloak().issuer
```

Edit 8 (old lines 211-215), replace:

```python

    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> Response:
        response = safe(exc.status, exc.code, exc.message)
        if exc.clear_session or exc.clear_login:  # the auth deps exist whenever a route that sets these flags runs
```

with:

```python

    def failed(request: Request, exc: BaseException) -> None:
        """Log a server-side failure once, with the request id and the class name only: an exception's text may carry
        SQL, or a psycopg DETAIL naming a tenant, a subject and a key in clear (spike §1)."""
        log.error("request %s failed: %s", limits.request_id_of(request.scope), exc.__class__.__name__)

    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> Response:
        # Every 503 an ApiError carries is an identity-provider outage (admin API, token endpoint, signing keys), the
        # one kind of refusal a client should retry (ruling 19).
        response = safe(request, exc.status, exc.code, exc.message, retryable=exc.status == 503)
        if exc.clear_session or exc.clear_login:  # the auth deps exist whenever a route that sets these flags runs
```

Edit 9 (old lines 222-227), replace:

```python

    @app.exception_handler(persistence.AuthorityViolation)
    async def _authority(_: Request, exc: persistence.AuthorityViolation) -> Response:
        log.error("deployment error: %s", exc)  # the API is connected as a role a function does not accept
        return safe(503, ErrorCode.UNAVAILABLE, "service misconfigured")

```

with:

```python

    @app.exception_handler(psycopg.OperationalError)
    @app.exception_handler(psycopg.InterfaceError)
    async def _database_down(request: Request, exc: psycopg.Error) -> Response:
        # The connection is gone or refused: nothing committed, so the same request may succeed once the database is
        # back (BS:564 "do not acknowledge uncommitted work"). Starlette picks the handler by the exception's MRO, so
        # these two win over the psycopg.Error handler below.
        failed(request, exc)
        return safe(request, 503, ErrorCode.UNAVAILABLE, "database unavailable", retryable=True)

```

Edit 10 (old lines 231-245), replace:

```python
    @app.exception_handler(EventRuleViolation)
    async def _server_defect(_: Request, exc: Exception) -> Response:
        # Messages carry no handle or secret. FastAPI picks the most specific class, so AuthorityViolation keeps
        # its own handler.
        log.error("service error: %r", exc)
        return safe(503, ErrorCode.UNAVAILABLE, "service error")

    @app.exception_handler(psycopg.Error)
    async def _database(_: Request, __: psycopg.Error) -> Response:
        return safe(503, ErrorCode.UNAVAILABLE, "database unavailable")

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, __: RequestValidationError) -> Response:
        return safe(422, ErrorCode.INVALID_INPUT, "request is not valid")

```

with:

```python
    @app.exception_handler(EventRuleViolation)
    @app.exception_handler(psycopg.Error)
    async def _server_defect(request: Request, exc: Exception) -> Response:
        # A defect, a refused deployment (AuthorityViolation is a PersistenceError) or an untranslated SQLSTATE such
        # as a 23505: retrying the same request meets the same defect, so `retryable` is false (ruling 19).
        failed(request, exc)
        return safe(request, 503, ErrorCode.UNAVAILABLE, "service error")

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> Response:
        # Starlette sends this response and then re-raises (spike §5), so uvicorn still logs the traceback through
        # the redaction filter; the client only ever sees the safe schema, never a plain-text 500.
        failed(request, exc)
        return safe(request, 503, ErrorCode.UNAVAILABLE, "service error")

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> Response:
        # The router's own refusals (unknown path, wrong method) answer FastAPI's `{"detail": ...}` otherwise.
        if exc.status_code == 404:
            return safe(request, 404, ErrorCode.NOT_FOUND, "no such route")
        if exc.status_code == 405:
            response = safe(request, 405, ErrorCode.INVALID_INPUT, "method not allowed")
            allow = (exc.headers or {}).get("Allow")
            if allow is not None:
                response.headers["Allow"] = allow  # RFC 9110 §15.5.6: a 405 names the methods that would work
            return response
        return safe(request, 422, ErrorCode.INVALID_INPUT, "request refused")

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, __: RequestValidationError) -> Response:
        return safe(request, 422, ErrorCode.INVALID_INPUT, "request is not valid")

```

Edit 11 (old lines 262-264), replace:

```python
            except (psycopg.Error, OSError):  # readiness reports a database failure as not ready
                return safe(503, ErrorCode.UNAVAILABLE, "database not reachable")
        return JSONResponse({"status": "ready"})
```

with:

```python
            except (psycopg.Error, OSError):  # readiness reports a database failure as not ready
                return safe(request, 503, ErrorCode.UNAVAILABLE, "database not reachable", retryable=True)
        return JSONResponse({"status": "ready"})
```

Edit 12 (old lines 603-604), replace:

```python

    return create_app(verifier, make_store, make_auth)
```

with:

```python

    return create_app(verifier, make_store, make_auth, admission=settings.admission())
```

Run: `uv run python -m pytest tests/plan_g/test_limits.py tests/plan_g/test_error_surface.py -q`
Expected: `14 passed`.

Run: `uv run python -m pytest tests/plan_d/test_api.py tests/plan_f -q`
Expected: `157 passed` (the existing callers of `safe` now pass the request; the 503 of a lost connection stays
`retryable: true`, and a `PersistenceError` 503 is now `retryable: false`, which no existing test pins).

- [ ] **Step 8: Gates and commit**

Format, lint and count characters on the touched files (`ruff format`, `ruff check --fix`, the counting command):
`core/src/ops_core/settings.py api/src/ops_api/limits.py api/src/ops_api/app.py tests/plan_g pyproject.toml`.

Run: `PYTHONUTF8=1 uv run python scripts/check.py`
Expected: `CHECK: GREEN`; pytest `698 passed, 95 skipped` (679 + 5 + 7 + 7).

Run: `PYTHONUTF8=1 uv run python scripts/check.py --profile test`
Expected: `CHECK: GREEN`; pytest `772 passed, 21 skipped` (698 + 74 live). Then
`git checkout -- reports/bootstrap reports/skeleton`.

Run: `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts`
Expected: exit 0.

```bash
git add pyproject.toml core/src/ops_core/settings.py api/src/ops_api/limits.py api/src/ops_api/app.py tests/plan_g
git commit -m "feat(api): safe error surface, request ids and the body limit; admission settings (T12)"
```

---

### Task 2: Revision 0006, the privilege matrix, the sweeper's purge and the startup guards

**Files:**
- Create: `migrations/app/versions/0006_admission_idempotency.py`, `tests/plan_g/test_migration_0006.py`,
  `tests/e2e/test_migration_0006_live.py`
- Modify: `core/src/ops_core/privileges.py:6-15` (docstring), `:81-82` (row), `:154-155` (`NO_RLS`),
  `tests/plan_e/test_transitions_table.py:90-91` (`REVISIONS`), `sweeper/src/ops_sweeper/sync.py:88-91`, `:102-103`,
  `sweeper/src/ops_sweeper/main.py:188-190`, `tests/plan_f/test_sweeper.py:10-11`, `:137-140`,
  `api/src/ops_api/app.py:131-133` (as Task 1 left it)

**Interfaces:**
- Consumes: `ops_core.privileges.Grant`, `grant_statements(tables, grants, *, revokees)`; `scripts.skeleton.migrate`,
  `downgrade`; the e2e fixtures `app_conn`, `role_conn`.
- Produces: the table `app.idempotency_request(tenant_id uuid, subject uuid, route text, key text,
  fingerprint_sha256 text, status_code smallint, response jsonb, created_at timestamptz, expires_at timestamptz,
  PRIMARY KEY (tenant_id, subject, route, key))`; `app.messages.seq bigint` (identity), `messages_kind_check`,
  `messages_author_check`, nullable `author`; `privileges.GRANTS["idempotency_request"] = {"api": sel+ins,
  "sweeper": sel+del}`; the revision's `GRANTS_0006`, `STORED_KINDS_0006`, `SYSTEM_KINDS_0006`, `TABLES`,
  `MAIN_GRANTEES_0006`; `sync.purge_expired(conn) -> dict[str, int]` with the key `"idempotency_request"`.

- [ ] **Step 1: Write the failing revision tests**

Create `tests/plan_g/test_migration_0006.py`:

```python
"""Revision 0006 without a database (Plan G rulings 4, 7 and 8): the record table's frozen cells equal the live
matrix, the statements create what the store relies on, and the downgrade refuses to lose a system message.

Catches: an UPDATE or DELETE cell for `api` (a record must be write-once), a sweeper DELETE without its SELECT
(erratum 25: the purge's WHERE reads the row), a `serial` where an identity column was ruled (spike §6: a serial needs
USAGE on its sequence, which `api` lacks), a nullable `author` without the CHECK that ties it to the system kinds, and
a downgrade that would set NOT NULL over rows it cannot keep.
"""

import importlib.util
from pathlib import Path
from typing import Any

import alembic.op
import pytest
from ops_core import privileges as p

VERSIONS = Path(__file__).resolve().parents[2] / "migrations" / "app" / "versions"


def revision() -> Any:
    """Load revision 0006 by path (the versions directory is not a package)."""
    path = VERSIONS / "0006_admission_idempotency.py"
    spec = importlib.util.spec_from_file_location("rev0006", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def statements(fn: str, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """What upgrade() or downgrade() hands to op.execute, in order."""
    module = revision()
    seen: list[str] = []
    monkeypatch.setattr(alembic.op, "execute", lambda statement, *a, **k: seen.append(str(statement)))
    getattr(module, fn)()
    return seen


def test_the_frozen_cells_are_the_live_matrix_and_the_table_has_no_rls() -> None:
    module = revision()
    assert module.down_revision == "0005_sessions_login_logout"
    assert module.GRANTS_0006 == {t: p.GRANTS[t] for t in module.TABLES}
    assert p.GRANTS["idempotency_request"] == {
        "api": p.Grant(sel=True, ins=True),
        "sweeper": p.Grant(sel=True, dele=True),
    }
    assert "idempotency_request" in p.NO_RLS and "idempotency_request" not in p.RLS_TABLES  # SA:523
    assert set(module.MAIN_GRANTEES_0006) == set(p.MAIN_GRANTEES)


def test_upgrade_creates_the_record_the_sequence_and_the_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = statements("upgrade", monkeypatch)
    table = next(s for s in seen if s.startswith("CREATE TABLE app.idempotency_request"))
    for column in (
        "tenant_id uuid NOT NULL",
        "subject uuid NOT NULL",
        "route text NOT NULL",
        "key text NOT NULL",
        "fingerprint_sha256 text NOT NULL",
        "status_code smallint NOT NULL",
        "response jsonb NOT NULL",
        "expires_at timestamptz NOT NULL",
        "PRIMARY KEY (tenant_id, subject, route, key)",
    ):
        assert column in table, column
    assert "ALTER TABLE app.messages ADD COLUMN seq bigint GENERATED ALWAYS AS IDENTITY NOT NULL" in seen
    assert "ALTER TABLE app.idempotency_request OWNER TO migrator" in seen
    author = next(s for s in seen if "messages_author_check" in s)
    assert "(kind IN ('status_answer', 'clarification_question')) = (author IS NULL)" in author
    grants = [s for s in seen if s.startswith(("GRANT", "REVOKE"))]
    assert grants == [
        "REVOKE ALL ON app.idempotency_request FROM api, worker, sweeper, mcp_read, mcp_exec, operator, app_definer",
        "GRANT INSERT, SELECT ON app.idempotency_request TO api",
        "GRANT SELECT, DELETE ON app.idempotency_request TO sweeper",
    ]


def test_the_downgrade_refuses_system_messages_before_restoring_not_null(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = statements("downgrade", monkeypatch)
    assert seen[0].startswith("DO $do$") and "author IS NULL" in seen[0] and "RAISE EXCEPTION" in seen[0]
    assert seen.index("ALTER TABLE app.messages DROP CONSTRAINT messages_author_check") < seen.index(
        "ALTER TABLE app.messages ALTER COLUMN author SET NOT NULL"
    )
    assert seen[-1] == "DROP TABLE app.idempotency_request"
    assert not any("DELETE" in s for s in seen)  # it deletes nothing (ruling 8)
```

In `tests/plan_e/test_transitions_table.py` add the revision to `REVISIONS` (on-disk Alembic order, before the
`testclock` branch):

Edit 1 (old lines 90-91), replace:

```python
    "0005_sessions_login_logout",
    "tc_0001_test_clock",
```

with:

```python
    "0005_sessions_login_logout",
    "0006_admission_idempotency",
    "tc_0001_test_clock",
```

Run: `uv run python -m pytest tests/plan_g/test_migration_0006.py tests/plan_e/test_transitions_table.py -q`
Expected: `1 error in` (collection stops at the module-level `assert` on `REVISIONS` in the transitions module: the
file `0006_admission_idempotency.py` does not exist yet). The newest-revision check stays red until Step 3; nothing
else is red at any point of this task.

- [ ] **Step 2: Write the revision**

Create `migrations/app/versions/0006_admission_idempotency.py`:

```python
"""The request-dedup record and the message vocabulary admission writes (T12, Plan G rulings 4, 8 and 26).

Revision ID: 0006_admission_idempotency
Revises: 0005_sessions_login_logout

`idempotency_request` is the scoped Idempotency-Key record (BS:244, SA:429): one row per (tenant, subject, route,
key), written last in the unit that did the work (SA:188), holding the status and the body a replay returns. No RLS
(SA:523); the grants are the control: `api` selects and inserts (no UPDATE, so a record is write-once), the sweeper
selects and deletes expired rows (erratum 25 again: a DELETE with a WHERE needs SELECT, spike §1). `messages` gains
`seq`, an identity column, because two rows written in one transaction share `now()` (spike §6: a status question and
its answer would otherwise have no order) and an identity needs only INSERT where a serial needs USAGE on its
sequence; a CHECK on `kind` names the stored vocabulary; `author` becomes nullable for the two system kinds and only
for them. Every cell is frozen here (round-3 finding N1 of Plan E).
"""

from alembic import op
from ops_core import privileges

revision = "0006_admission_idempotency"
down_revision = "0005_sessions_login_logout"
branch_labels = None
depends_on = None

TABLES = ("idempotency_request",)
MAIN_GRANTEES_0006 = ("api", "worker", "sweeper", "mcp_read", "mcp_exec", "operator", "app_definer")
GRANTS_0006: dict[str, dict[str, privileges.Grant]] = {
    "idempotency_request": {
        "api": privileges.Grant(sel=True, ins=True),
        "sweeper": privileges.Grant(sel=True, dele=True),
    },
}
# The stored `messages.kind` vocabulary (ruling 26) and its two system kinds, frozen here; a unit test compares them
# with ops_core.contracts.StoredMessageKind.
STORED_KINDS_0006 = (
    "investigate",
    "ask",
    "clarification_reply",
    "status_question",
    "status_answer",
    "clarification_question",
)
SYSTEM_KINDS_0006 = ("status_answer", "clarification_question")
KINDS = ", ".join(f"'{kind}'" for kind in STORED_KINDS_0006)
SYSTEM_KINDS = ", ".join(f"'{kind}'" for kind in SYSTEM_KINDS_0006)

SCHEMA_CHANGES = (
    (
        "CREATE TABLE app.idempotency_request ("
        " tenant_id uuid NOT NULL,"
        " subject uuid NOT NULL,"
        " route text NOT NULL,"
        " key text NOT NULL,"
        " fingerprint_sha256 text NOT NULL,"
        " status_code smallint NOT NULL,"
        " response jsonb NOT NULL,"
        " created_at timestamptz NOT NULL DEFAULT clock_timestamp(),"
        " expires_at timestamptz NOT NULL,"
        " PRIMARY KEY (tenant_id, subject, route, key))"
    ),
    "CREATE INDEX idempotency_request_expires_idx ON app.idempotency_request (expires_at)",
    "ALTER TABLE app.idempotency_request OWNER TO migrator",
    "ALTER TABLE app.messages ADD COLUMN seq bigint GENERATED ALWAYS AS IDENTITY NOT NULL",
    "ALTER TABLE app.messages ADD CONSTRAINT messages_conversation_seq_key UNIQUE (conversation_id, seq)",
    f"ALTER TABLE app.messages ADD CONSTRAINT messages_kind_check CHECK (kind IN ({KINDS}))",
    "ALTER TABLE app.messages ALTER COLUMN author DROP NOT NULL",
    (
        "ALTER TABLE app.messages ADD CONSTRAINT messages_author_check"
        f" CHECK ((kind IN ({SYSTEM_KINDS})) = (author IS NULL))"
    ),
)

DOWNGRADE = (
    # 0005 has no row without an author; deleting system messages silently would lose conversation history, so a
    # database that holds any refuses the downgrade with a message instead (ruling 8).
    (
        "DO $do$ BEGIN"
        " IF EXISTS (SELECT 1 FROM app.messages WHERE author IS NULL) THEN"
        " RAISE EXCEPTION 'system messages exist; delete them before downgrading revision 0006';"
        " END IF;"
        " END $do$"
    ),
    "ALTER TABLE app.messages DROP CONSTRAINT messages_author_check",
    "ALTER TABLE app.messages ALTER COLUMN author SET NOT NULL",
    "ALTER TABLE app.messages DROP CONSTRAINT messages_kind_check",
    "ALTER TABLE app.messages DROP CONSTRAINT messages_conversation_seq_key",
    "ALTER TABLE app.messages DROP COLUMN seq",
    f"REVOKE ALL ON app.idempotency_request FROM {', '.join(MAIN_GRANTEES_0006)}",
    "DROP TABLE app.idempotency_request",
)


def upgrade() -> None:
    """The table and the message changes first, then the frozen grants (REVOKE ALL lands on the new table)."""
    for statement in SCHEMA_CHANGES:
        op.execute(statement)
    for statement in privileges.grant_statements(TABLES, GRANTS_0006, revokees=MAIN_GRANTEES_0006):
        op.execute(statement)


def downgrade() -> None:
    """Back to 0005's messages and no record table; refused while a system message exists."""
    for statement in DOWNGRADE:
        op.execute(statement)
```

Then `uv run ruff check --select ISC004 --fix --unsafe-fixes migrations/app/versions/0006_admission_idempotency.py`
(no change expected: every implicit concatenation is already inside its own parentheses).

Run: `uv run python -m pytest tests/plan_g/test_migration_0006.py tests/plan_e/test_transitions_table.py -q`
Expected: `2 failed, 12 passed`: `test_the_frozen_cells_are_the_live_matrix_and_the_table_has_no_rls` and
`test_the_newest_revision_of_every_cell_equals_the_live_matrix` fail with `KeyError: 'idempotency_request'` (the
matrix has no row yet).

- [ ] **Step 3: The matrix row**

In `core/src/ops_core/privileges.py`:

Edit 1 (old lines 6-15), replace:

```python
added here), and the R124/R106 tests enumerate the catalogs against it, so an extra or missing grant fails a test
instead of hiding. Rows exist only for tables that exist; the owners of later tables (outbox → T14, feedback and
idempotency_request → T12, operator_resolutions → T22, documents/chunks/embeddings → T17, model_permit → T13) add
their rows. Six departures from the printed table, each a proposed erratum (Plan E rulings 6, 10, 17, 23; Plan F
rulings 2, 3 and 17 with erratum 25): the worker (not the sweeper) may UPDATE jobs.available_at (re-queue after a
transport failure), app_definer may UPDATE runs.updated_at, the `transitions` table (the T07 table mirrored in SQL)
is readable by app_definer only, no definer function takes a row lock on proposals, decisions, memberships or
execution_grant (a lock needs UPDATE, which the matrix withholds), the sweeper holds SELECT beside its DELETE on
sessions, login_state and logout_jti (a DELETE with a WHERE reads the row), and login_state and logout_jti are rows
the printed table lacks. `test_harness` exists only in the test profile: the main-line revisions grant it nothing;
```

with:

```python
added here), and the R124/R106 tests enumerate the catalogs against it, so an extra or missing grant fails a test
instead of hiding. Rows exist only for tables that exist; the owners of later tables (outbox → T14, feedback → T21,
operator_resolutions → T22, documents/chunks/embeddings → T17, model_permit → T13) add their rows. Six departures
from the printed table, each a proposed erratum (Plan E rulings 6, 10, 17, 23; Plan F rulings 2, 3 and 17 with
erratum 25; Plan G ruling 4): the worker (not the sweeper) may UPDATE jobs.available_at (re-queue after a transport
failure), app_definer may UPDATE runs.updated_at, the `transitions` table (the T07 table mirrored in SQL) is readable
by app_definer only, no definer function takes a row lock on proposals, decisions, memberships or execution_grant (a
lock needs UPDATE, which the matrix withholds), the sweeper holds SELECT beside its DELETE on sessions, login_state,
logout_jti and idempotency_request (a DELETE with a WHERE reads the row), and login_state and logout_jti are rows
the printed table lacks. `test_harness` exists only in the test profile: the main-line revisions grant it nothing;
```

Edit 2 (old lines 81-82), replace:

```python
    "logout_jti": {"api": _INS, "sweeper": Grant(sel=True, dele=True)},
    "conversations": {"api": _SI, "worker": _S, DEFINER_ROLE: _S},
```

with:

```python
    "logout_jti": {"api": _INS, "sweeper": Grant(sel=True, dele=True)},
    # T12 (Plan G ruling 4): the scoped Idempotency-Key record; write-once for api (no UPDATE), purged by the sweeper.
    "idempotency_request": {"api": _SI, "sweeper": Grant(sel=True, dele=True)},
    "conversations": {"api": _SI, "worker": _S, DEFINER_ROLE: _S},
```

Edit 3 (old lines 154-155), replace:

```python
    "logout_jti",
)
```

with:

```python
    "logout_jti",
    "idempotency_request",
)
```

Run:

```bash
uv run python -m pytest tests/plan_g/test_migration_0006.py tests/plan_e/test_transitions_table.py \
  tests/plan_f/test_privileges_f.py -q
```

Expected: `16 passed` (3 new, the transitions module's 11 with one more parametrised revision, Plan F's 2).

- [ ] **Step 4: The sweeper purges the records, and both services refuse a database without them**

Write the failing purge test first, in `tests/plan_f/test_sweeper.py`:

Edit 1 (old lines 10-11), replace:

```python
import logging
from dataclasses import dataclass, field
```

with:

```python
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
```

Edit 2 (old lines 137-140), replace:

```python


@pytest.mark.asyncio
async def test_the_override_covers_the_first_successful_sync_only(
```

with:

```python


class PurgeConn:
    """A connection that records the purge's statements and answers each DELETE with a fixed rowcount."""

    def __init__(self) -> None:
        self.statements: list[str] = []
        self.in_transaction = False

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        self.in_transaction = True
        yield
        self.in_transaction = False

    async def execute(self, statement: str) -> Any:
        assert self.in_transaction  # the four deletes commit together
        self.statements.append(statement)
        return type("Cursor", (), {"rowcount": len(self.statements)})()


@pytest.mark.asyncio
async def test_the_purge_covers_the_idempotency_records() -> None:
    """Plan G ruling 7: expired records leave with the other three tables, on the application clock."""
    conn = PurgeConn()
    as_conn: Any = conn  # the purge needs only transaction() and execute()
    counts = await sync.purge_expired(as_conn)
    assert counts == {"sessions": 1, "login_state": 2, "logout_jti": 3, "idempotency_request": 4}
    assert conn.statements[-1] == "DELETE FROM app.idempotency_request WHERE expires_at < app.current_time()"


@pytest.mark.asyncio
async def test_the_override_covers_the_first_successful_sync_only(
```

Run: `uv run python -m pytest tests/plan_f/test_sweeper.py -q`
Expected: `1 failed, 8 passed` (`test_the_purge_covers_the_idempotency_records`: the counts have three keys).

In `sweeper/src/ops_sweeper/sync.py`:

Edit 1 (old lines 88-91), replace:

```python
async def purge_expired(conn: persistence.Conn) -> dict[str, int]:
    """Delete what nothing can use any more: sessions a day past their end, expired login state, old jti
    rows (erratum 25: the sweeper holds SELECT with its DELETE on all three)."""
    counts: dict[str, int] = {}
```

with:

```python
async def purge_expired(conn: persistence.Conn) -> dict[str, int]:
    """Delete what nothing can use any more: sessions a day past their end, expired login state, old jti rows and
    idempotency records past their replay window (erratum 25: the sweeper holds SELECT with its DELETE on all four;
    Plan G ruling 7: no job type, the purge rides the tick like the other three)."""
    counts: dict[str, int] = {}
```

Edit 2 (old lines 102-103), replace:

```python
            ("logout_jti", "expires_at < app.current_time()"),
        ):
```

with:

```python
            ("logout_jti", "expires_at < app.current_time()"),
            ("idempotency_request", "expires_at < app.current_time()"),
        ):
```

In `sweeper/src/ops_sweeper/main.py`:

Edit 1 (old lines 188-190), replace:

```python
        await persistence.assert_clock_profile(probe, settings.profile())
        await persistence.assert_relation(probe, "app.logout_jti")  # revision 0005 (the purge touches all 3 tables)
    except BaseException:  # close what was built before the tasks exist (a refused start must not leak sockets)
```

with:

```python
        await persistence.assert_clock_profile(probe, settings.profile())
        await persistence.assert_relation(probe, "app.idempotency_request")  # revision 0006: the newest purged table
    except BaseException:  # close what was built before the tasks exist (a refused start must not leak sockets)
```

In `api/src/ops_api/app.py` (line numbers as Task 1 left the file):

Edit 1 (old lines 131-133), replace:

```python
                await persistence.assert_clock_profile(app.state.store.session.conn, settings.profile())
                await persistence.assert_relation(app.state.store.session.conn, "app.login_state")  # revision 0005
            if not verifier.ready:
```

with:

```python
                await persistence.assert_clock_profile(app.state.store.session.conn, settings.profile())
                # Revision 0006: admission writes the record table and the message columns it adds.
                await persistence.assert_relation(app.state.store.session.conn, "app.idempotency_request")
            if not verifier.ready:
```

Run: `uv run python -m pytest tests/plan_f/test_sweeper.py -q`
Expected: `9 passed`.

- [ ] **Step 5: The live revision test**

Create `tests/e2e/test_migration_0006_live.py`:

```python
"""Revision 0006 against the per-session test database (OPS_LIVE=1; Plan G rulings 4 and 8).

Catches: an upgrade that fails on a database already holding messages (the identity column must number them), a
downgrade/upgrade round trip that does not restore the 0005 shape, a record table `api` could update or delete (a
replay would then not be the original answer), a sweeper that cannot purge, and a `messages` insert by the
INSERT-only `api` role that the identity column or the new CHECKs refuse when they should not, or accept when they
should not.
"""

from collections.abc import Awaitable, Callable
from uuid import UUID, uuid4

import psycopg
import pytest
import sqlalchemy.exc
from ops_core import persistence, settings
from ops_core.settings import Profile, Role
from psycopg.types.json import Jsonb

pytestmark = pytest.mark.asyncio

RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
ALPHA = UUID("3ea79c95-914c-52cb-9d10-c4e19dda8ff7")
ALEX = UUID("2fc05986-c7ec-544c-b628-fdb112bbf18a")
INSERT_MESSAGE = (
    "INSERT INTO app.messages (message_id, tenant_id, conversation_id, kind, text, author)"
    " VALUES (%s, %s, %s, %s, 'x', %s)"
)


async def has_column(conn: persistence.Conn, table: str, column: str) -> bool:
    cur = await conn.execute(
        "SELECT count(*) AS n FROM information_schema.columns WHERE table_schema = 'app' AND table_name = %s"
        " AND column_name = %s",
        (table, column),
    )
    return bool((await cur.fetchone())["n"])


async def conversation(conn: persistence.Conn) -> UUID:
    conv = uuid4()
    await conn.execute(
        "INSERT INTO app.conversations (conversation_id, tenant_id, created_by) VALUES (%s, %s, %s)",
        (conv, ALPHA, ALEX),
    )
    return conv


async def forget(conn: persistence.Conn, conv: UUID) -> None:
    await conn.execute("DELETE FROM app.messages WHERE conversation_id = %s", (conv,))
    await conn.execute("DELETE FROM app.conversations WHERE conversation_id = %s", (conv,))


async def test_upgrade_numbers_existing_messages_and_the_round_trip_restores_0005(app_conn: persistence.Conn) -> None:
    from scripts.skeleton import downgrade, migrate

    superuser = settings.superuser_postgres()
    downgrade("app", superuser, "0005_sessions_login_logout")
    conv = await conversation(app_conn)
    try:
        assert not await has_column(app_conn, "messages", "seq")
        older = uuid4()
        await app_conn.execute(INSERT_MESSAGE, (older, ALPHA, conv, "investigate", ALEX))
        assert migrate(Profile.TEST) == 0  # 0005 -> 0006 on a database that already holds a message
        cur = await app_conn.execute("SELECT seq FROM app.messages WHERE message_id = %s", (older,))
        first = (await cur.fetchone())["seq"]
        newer = uuid4()
        await app_conn.execute(INSERT_MESSAGE, (newer, ALPHA, conv, "status_question", ALEX))
        cur = await app_conn.execute("SELECT seq FROM app.messages WHERE message_id = %s", (newer,))
        assert first is not None and (await cur.fetchone())["seq"] > first
        # A system message blocks the downgrade with the revision's own message, and nothing changes.
        await app_conn.execute(INSERT_MESSAGE, (uuid4(), ALPHA, conv, "status_answer", None))
        with pytest.raises(sqlalchemy.exc.DBAPIError, match="system messages exist"):
            downgrade("app", superuser, "0005_sessions_login_logout")
        assert await has_column(app_conn, "messages", "seq")
        await app_conn.execute("DELETE FROM app.messages WHERE author IS NULL AND conversation_id = %s", (conv,))
        downgrade("app", superuser, "0005_sessions_login_logout")
        assert not await has_column(app_conn, "messages", "seq")
        cur = await app_conn.execute("SELECT to_regclass('app.idempotency_request') IS NULL AS gone")
        assert (await cur.fetchone())["gone"]
        cur = await app_conn.execute(
            "SELECT is_nullable FROM information_schema.columns WHERE table_schema = 'app'"
            " AND table_name = 'messages' AND column_name = 'author'"
        )
        assert (await cur.fetchone())["is_nullable"] == "NO"
    finally:
        assert migrate(Profile.TEST) == 0  # every later test needs the head
        await forget(app_conn, conv)
    assert await has_column(app_conn, "messages", "seq")


async def test_the_record_is_write_once_for_api_and_purgeable_by_the_sweeper(role_conn: RoleConn) -> None:
    api, sweeper, worker = await role_conn(Role.API), await role_conn(Role.SWEEPER), await role_conn(Role.WORKER)
    key = f"live-{uuid4()}"
    scope = (ALPHA, ALEX, "POST /api/v1/conversations", key)
    await api.execute(
        "INSERT INTO app.idempotency_request (tenant_id, subject, route, key, fingerprint_sha256, status_code,"
        " response, expires_at) VALUES (%s, %s, %s, %s, %s, 201, %s, app.current_time() - interval '1 second')",
        (*scope, "0" * 64, Jsonb({"conversation_id": str(uuid4())})),
    )
    where = " WHERE tenant_id = %s AND subject = %s AND route = %s AND key = %s"
    cur = await api.execute("SELECT status_code FROM app.idempotency_request" + where, scope)
    assert (await cur.fetchone())["status_code"] == 201
    for statement in (
        "UPDATE app.idempotency_request SET status_code = 200" + where,
        "DELETE FROM app.idempotency_request" + where,
    ):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            await api.execute(statement, scope)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        await worker.execute("SELECT 1 FROM app.idempotency_request LIMIT 1")
    cur = await sweeper.execute("DELETE FROM app.idempotency_request WHERE expires_at < app.current_time()")
    assert cur.rowcount >= 1
    cur = await sweeper.execute("SELECT count(*) AS n FROM app.idempotency_request" + where, scope)
    assert (await cur.fetchone())["n"] == 0


async def test_api_inserts_numbered_messages_and_the_checks_hold(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    api = await role_conn(Role.API)
    conv = await conversation(app_conn)
    try:
        question, answer = uuid4(), uuid4()
        async with api.transaction():
            await persistence.set_tenant(api, ALPHA)
            await api.execute(INSERT_MESSAGE, (question, ALPHA, conv, "status_question", ALEX))
            await api.execute(INSERT_MESSAGE, (answer, ALPHA, conv, "status_answer", None))
        cur = await app_conn.execute(
            "SELECT message_id FROM app.messages WHERE conversation_id = %s ORDER BY seq", (conv,)
        )
        assert [r["message_id"] for r in await cur.fetchall()] == [question, answer]  # one transaction, ordered
        for kind, author in (("bogus", ALEX), ("investigate", None), ("status_answer", ALEX)):
            with pytest.raises(psycopg.errors.CheckViolation):
                async with api.transaction():
                    await persistence.set_tenant(api, ALPHA)
                    await api.execute(INSERT_MESSAGE, (uuid4(), ALPHA, conv, kind, author))
    finally:
        await forget(app_conn, conv)
```

Run (dev stack up, no skeleton process running):
`OPS_LIVE=1 PYTHONUTF8=1 uv run python -m pytest tests/e2e/test_migration_0006_live.py -q`
Expected: `3 passed` (the `migrated` fixture recreates `ops_test` at 0006 first).

- [ ] **Step 6: Gates and commit**

Format, lint and count characters on every file of this task.

Run: `PYTHONUTF8=1 uv run python scripts/check.py`
Expected: `CHECK: GREEN`; pytest `703 passed, 98 skipped` (698 + 3 + 1 parametrised revision + 1 purge; the 3 new
live tests skip without `OPS_LIVE`).

Run: `PYTHONUTF8=1 uv run python scripts/check.py --profile test`
Expected: `CHECK: GREEN`; pytest `780 passed, 21 skipped` (703 + 77 live: R006's downgrade now passes through 0006,
whose guard finds no system message because nothing writes one before Task 5). Then
`git checkout -- reports/bootstrap reports/skeleton`.

Run: `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts`
Expected: exit 0.

```bash
git add migrations/app/versions/0006_admission_idempotency.py core/src/ops_core/privileges.py sweeper/src
git add api/src/ops_api/app.py tests/plan_g/test_migration_0006.py tests/plan_e/test_transitions_table.py
git add tests/plan_f/test_sweeper.py tests/e2e/test_migration_0006_live.py
git commit -m "feat(migrations): revision 0006, the idempotency record and typed, numbered messages (T12)"
```

---

### Task 3: The admission router table, the text-versus-fields parser and the stored message kinds

**Files:**
- Modify: `core/src/ops_core/routing.py` (whole file), `core/src/ops_core/contracts.py:148-149` (after `MessageKind`)
- Create: `tests/plan_g/test_routing_admission.py`
- Unchanged and still green: `tests/plan_c/test_jobs_routes_outcomes.py` (pins the `AdmissionRoute` values),
  `tests/plan_c/test_schemas_generated.py` (no schema changes: `StoredMessageKind` is not a request schema)

**Interfaces:**
- Consumes: `ops_core.contracts.MessageKind`; revision 0006's `STORED_KINDS_0006`, `SYSTEM_KINDS_0006` (Task 2).
- Produces: `ops_core.contracts.StoredMessageKind` (`INVESTIGATE`, `ASK`, `CLARIFICATION_REPLY`, `STATUS_QUESTION`,
  `STATUS_ANSWER`, `CLARIFICATION_QUESTION`), `SYSTEM_MESSAGE_KINDS: frozenset[StoredMessageKind]`.
- Produces: `ops_core.routing.ClarifyCause` (`missing_asset`, `asset_ambiguous`, `asset_conflict`,
  `missing_interval`, `interval_out_of_range`, `interval_conflict`, `hint`), `RejectCause`
  (`use_clarifications_route`, `slot_occupied`), `HOURS_MIN = 1`, `HOURS_MAX = 168`, `TEXT_ASSET`, `ASSET_ID`,
  `TEXT_WINDOW`, `TEXT_WINDOW_WORD`, `QUESTIONS: dict[ClarifyCause, str]`, `text_assets(text) -> tuple[str, ...]`,
  `text_window(text) -> int | None`, `AdmissionFacts(kind, text, asset_id, hours, active_run, hint=None)`,
  `Resolution(asset_id, hours, cause=None, question=None)`, `resolve(facts) -> Resolution`,
  `AdmissionDecision(route, cause=None, asset_id=None, hours=None, question=None)`, `AdmissionRule(name, predicate,
  route, cause=None)`, `ADMISSION_RULES`, `REPLY_RULES`, `route_admission(facts) -> AdmissionDecision`,
  `route_reply(facts) -> AdmissionDecision` (raises `LookupError` when no row matches).

- [ ] **Step 1: Write the failing router test**

Create `tests/plan_g/test_routing_admission.py`:

```python
"""The admission router as a table (AM-16, R129; Plan G rulings 12, 16 and 26): every row is reachable and is the first
to match its sample, the six routes are all reachable, the text-versus-fields parser clarifies instead of guessing
(R018), the slot check precedes every question, and a model hint can only produce a clarification.

Catches: a row shadowed by an earlier one (dead routing), a route no input reaches, a text naming another asset
than the form starting work anyway, a "last 200 hours" window accepted, an acronym (UTC) or a lower-case id read as
an asset, a busy conversation answered with a question instead of 409, a status question refused while a run is
active (R017 says it must not start work, not that it must be refused), a hint that starts or rejects work, and a
stored-kind vocabulary that drifts from revision 0006's CHECK.
"""

import importlib.util
from pathlib import Path
from typing import Any

import pytest
from ops_core.contracts import SYSTEM_MESSAGE_KINDS, MessageKind, StoredMessageKind
from ops_core.routing import (
    ADMISSION_RULES,
    REPLY_RULES,
    AdmissionFacts,
    AdmissionRoute,
    ClarifyCause,
    RejectCause,
    Resolution,
    resolve,
    route_admission,
    route_reply,
)

SAMPLE = "Investigate the alerts on Asset A17 over the last 24 hours."  # BS:287-295


def facts(
    text: str = SAMPLE,
    *,
    kind: MessageKind = MessageKind.INVESTIGATE,
    asset_id: str | None = None,
    hours: int | None = None,
    active_run: bool = False,
    hint: AdmissionRoute | None = None,
) -> AdmissionFacts:
    return AdmissionFacts(kind=kind, text=text, asset_id=asset_id, hours=hours, active_run=active_run, hint=hint)


# One input per row that the row, and no earlier row, decides.
ROW_SAMPLES = {
    "status": facts("Where is my run?", kind=MessageKind.STATUS, active_run=True),
    "clarification_kind": facts("A17, 24 hours", kind=MessageKind.CLARIFICATION),
    "slot_occupied": facts(active_run=True),
    "text_and_fields": facts("Investigate something."),
    "hint": facts(asset_id="A17", hours=24, hint=AdmissionRoute.CLARIFY),
    "investigate": facts(asset_id="A17", hours=24),
    "ask": facts("What did A17 log in the last 24 hours?", kind=MessageKind.ASK),
    "bound_reply": facts("Clarification: asset A17, hours 24", kind=MessageKind.CLARIFICATION, asset_id="A17"),
}


def first_rule(sample: AdmissionFacts, rules: Any) -> str:
    """The name of the first row whose predicate holds, computed the way route_admission computes it."""
    runs = (MessageKind.INVESTIGATE, MessageKind.ASK)
    resolution = resolve(sample) if sample.kind in runs else Resolution(sample.asset_id, sample.hours)
    return str(next(rule.name for rule in rules if rule.predicate(sample, resolution)))


def test_every_row_is_reachable_first_and_the_six_routes_are_all_reachable() -> None:
    reached = set()
    for rules, router in ((ADMISSION_RULES, route_admission), (REPLY_RULES, route_reply)):
        for rule in rules:
            sample = ROW_SAMPLES[rule.name]
            assert first_rule(sample, rules) == rule.name, rule.name
            decision = router(sample)
            assert decision.route is rule.route, rule.name
            reached.add(decision.route)
    assert reached == set(AdmissionRoute)
    assert len(ROW_SAMPLES) == len(ADMISSION_RULES) + len(REPLY_RULES)


@pytest.mark.parametrize(
    ("text", "asset_id", "hours", "kind", "expected"),
    [
        (SAMPLE, "A17", 24, MessageKind.INVESTIGATE, ("investigate", None, "A17", 24)),
        (SAMPLE, None, None, MessageKind.INVESTIGATE, ("investigate", None, "A17", 24)),
        ("Investigate A17 over the last day.", None, None, MessageKind.INVESTIGATE, ("investigate", None, "A17", 24)),
        (
            "Investigate A17 over the past 3 days.",
            None,
            None,
            MessageKind.INVESTIGATE,
            ("investigate", None, "A17", 72),
        ),
        ("Look at PUMP-2 for the last hour.", None, None, MessageKind.INVESTIGATE, ("investigate", None, "PUMP-2", 1)),
        ("Check A17, past 6h.", None, None, MessageKind.INVESTIGATE, ("investigate", None, "A17", 6)),
        ("Investigate A17.", "A17", 12, MessageKind.INVESTIGATE, ("investigate", None, "A17", 12)),
        ("Compare B22 with A17, last 24 hours.", "A17", 24, MessageKind.INVESTIGATE, ("investigate", None, "A17", 24)),
        ("What did A17 log in the last 24 hours?", None, None, MessageKind.ASK, ("readonly_answer", None, "A17", 24)),
        (
            "Investigate A17 over the last 200 hours.",
            None,
            None,
            MessageKind.INVESTIGATE,
            ("clarify", "interval_out_of_range", None, None),
        ),
        (
            "Investigate A17 over the last 0 hours.",
            None,
            None,
            MessageKind.INVESTIGATE,
            ("clarify", "interval_out_of_range", None, None),
        ),
        (
            "Compare A17 and B22 over the last 24 hours.",
            None,
            None,
            MessageKind.INVESTIGATE,
            ("clarify", "asset_ambiguous", None, None),
        ),
        (
            "Check the UTC alerts over the last 24 hours.",
            None,
            None,
            MessageKind.INVESTIGATE,
            ("clarify", "missing_asset", None, None),
        ),
        (
            "Check a17 over the last 24 hours.",
            None,
            None,
            MessageKind.INVESTIGATE,
            ("clarify", "missing_asset", None, None),
        ),
        (
            "Investigate B22 over the last 24 hours.",
            "A17",
            24,
            MessageKind.INVESTIGATE,
            ("clarify", "asset_conflict", None, None),
        ),
        (
            "Investigate A17 over the last 2 days.",
            "A17",
            24,
            MessageKind.INVESTIGATE,
            ("clarify", "interval_conflict", None, None),
        ),
        ("Investigate A17.", None, None, MessageKind.INVESTIGATE, ("clarify", "missing_interval", None, None)),
        ("What happened recently?", None, None, MessageKind.ASK, ("clarify", "missing_asset", None, None)),
    ],
)
def test_text_and_fields(
    text: str, asset_id: str | None, hours: int | None, kind: MessageKind, expected: tuple[str, Any, Any, Any]
) -> None:
    decision = route_admission(facts(text, kind=kind, asset_id=asset_id, hours=hours))
    assert (decision.route.value, decision.cause, decision.asset_id, decision.hours) == expected
    assert (decision.question is not None) == (decision.route is AdmissionRoute.CLARIFY)


def test_questions_name_what_disagreed() -> None:
    asked = {
        ClarifyCause.ASSET_CONFLICT: facts("Investigate B22 and C3 now.", asset_id="A17", hours=24),
        ClarifyCause.ASSET_AMBIGUOUS: facts("Compare A17 and B22 over the last 24 hours."),
        ClarifyCause.INTERVAL_OUT_OF_RANGE: facts("Investigate A17 over the past 10 days."),
        ClarifyCause.INTERVAL_CONFLICT: facts("Investigate A17 over the last 2 days.", asset_id="A17", hours=24),
    }
    expected = {
        ClarifyCause.ASSET_CONFLICT: "The form names asset A17 but the text names B22, C3; which one is meant?",
        ClarifyCause.ASSET_AMBIGUOUS: "The request names more than one asset (A17, B22); name the one to investigate.",
        ClarifyCause.INTERVAL_OUT_OF_RANGE: "The window must be between 1 and 168 hours; 240 hours was given.",
        ClarifyCause.INTERVAL_CONFLICT: "The form says 24 hours but the text says 48 hours; which is meant?",
    }
    for cause, sample in asked.items():
        decision = route_admission(sample)
        assert (decision.cause, decision.question) == (cause, expected[cause])


def test_a_busy_conversation_is_rejected_before_any_question() -> None:
    decision = route_admission(facts("Investigate something.", active_run=True))  # would clarify if idle
    assert (decision.route, decision.cause, decision.question) == (
        AdmissionRoute.REJECT,
        RejectCause.SLOT_OCCUPIED,
        None,
    )


def test_a_status_question_skips_the_parser_and_is_answered_while_busy() -> None:
    decision = route_admission(facts("B22 or A17? last 900 hours", kind=MessageKind.STATUS, active_run=True))
    assert (decision.route, decision.cause) == (AdmissionRoute.STATUS_QUESTION, None)


def test_a_clarification_sent_as_a_message_is_rejected_toward_its_own_route() -> None:
    decision = route_admission(facts(kind=MessageKind.CLARIFICATION, asset_id="A17", hours=24))
    assert (decision.route, decision.cause) == (AdmissionRoute.REJECT, RejectCause.USE_CLARIFICATIONS_ROUTE)


def test_a_hint_can_only_turn_a_run_into_a_clarification() -> None:
    for hint in AdmissionRoute:
        for kind, run_route in (
            (MessageKind.INVESTIGATE, AdmissionRoute.INVESTIGATE),
            (MessageKind.ASK, AdmissionRoute.READONLY_ANSWER),
        ):
            decision = route_admission(facts(kind=kind, asset_id="A17", hours=24, hint=hint))
            if hint is AdmissionRoute.CLARIFY:
                assert (decision.route, decision.cause) == (AdmissionRoute.CLARIFY, ClarifyCause.HINT)
                assert decision.question == "Please confirm the asset and the window for this request."
            else:
                assert decision.route is run_route, hint  # any other hint value is ignored
        busy = route_admission(facts(asset_id="A17", hours=24, active_run=True, hint=hint))
        status = route_admission(facts(kind=MessageKind.STATUS, hint=hint))
        assert busy.route is AdmissionRoute.REJECT and status.route is AdmissionRoute.STATUS_QUESTION, hint


def test_the_reply_table_routes_only_a_bound_reply() -> None:
    assert route_reply(facts(kind=MessageKind.CLARIFICATION, hours=24)).route is AdmissionRoute.CLARIFICATION_REPLY
    with pytest.raises(LookupError):
        route_reply(facts(kind=MessageKind.INVESTIGATE))


def test_the_stored_vocabulary_is_revision_0006s_and_the_request_kinds_are_unchanged() -> None:
    path = Path(__file__).resolve().parents[2] / "migrations" / "app" / "versions" / "0006_admission_idempotency.py"
    spec = importlib.util.spec_from_file_location("rev0006_kinds", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert set(module.STORED_KINDS_0006) == {k.value for k in StoredMessageKind}
    assert set(module.SYSTEM_KINDS_0006) == {k.value for k in SYSTEM_MESSAGE_KINDS}
    assert {k.value for k in MessageKind} == {"investigate", "ask", "status", "clarification"}  # the schema's enum
```

Run: `uv run python -m pytest tests/plan_g/test_routing_admission.py -q`
Expected: `1 error in` (`ImportError: cannot import name 'SYSTEM_MESSAGE_KINDS' from 'ops_core.contracts'`).

- [ ] **Step 2: The stored message kinds**

In `core/src/ops_core/contracts.py`, after `class MessageKind`:

Edit 1 (old lines 148-149), replace:

```python
    CLARIFICATION = "clarification"

```

with:

```python
    CLARIFICATION = "clarification"


class StoredMessageKind(StrEnum):
    """What a `messages` row is (revision 0006's CHECK; Plan G ruling 26): the request kinds that start or ask for a
    run keep their name, a status request is stored as its question, and the API writes the two system kinds itself.

    Not a request schema: `MessageKind` is what a client may send; this is what the table holds (AM-16, T12 review
    note 2: status answers and conversation-level clarifications are messages, not events).
    """

    INVESTIGATE = "investigate"
    ASK = "ask"
    CLARIFICATION_REPLY = "clarification_reply"
    STATUS_QUESTION = "status_question"
    STATUS_ANSWER = "status_answer"
    CLARIFICATION_QUESTION = "clarification_question"


# The kinds the API writes on its own behalf: the only rows whose `author` is NULL (revision 0006's second CHECK).
SYSTEM_MESSAGE_KINDS: Final = frozenset({StoredMessageKind.STATUS_ANSWER, StoredMessageKind.CLARIFICATION_QUESTION})

```

Run: `uv run python -m pytest tests/plan_g/test_routing_admission.py -q`
Expected: `1 error in` (`ImportError: cannot import name 'ADMISSION_RULES' from 'ops_core.routing'`).

- [ ] **Step 3: The table and the parser**

Replace `core/src/ops_core/routing.py` with:

```python
"""The three routers' enumerable routes (AM-16, ADR-0003), the admission router's table, and the per-run manifest.

Routing is deterministic-first: model output may hint, never select (SA:362, SA:375). The admission table (T12) is
`ADMISSION_RULES`, evaluated first match wins over facts the API gathered inside its admission unit; it is pure, so
a test walks every row (R129). The graph table arrives with T20 and the model table with T19; this module fixes the
vocabularies so every table, schema and event spells them the same way.

Text versus fields (BS:297, Plan G ruling 12): structured fields win only when the text agrees with them, so a
small deterministic parser reads an asset id and a "last N hours/days" window from the text; a disagreement, a
missing field the text cannot fill, or an ambiguous text becomes a stored clarification, never a guess (R018).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ops_core.contracts import MessageKind


class AdmissionRoute(StrEnum):
    """Where the admission router sends a message (AM-16; table owned by T12)."""

    INVESTIGATE = "investigate"
    CLARIFICATION_REPLY = "clarification_reply"
    STATUS_QUESTION = "status_question"
    READONLY_ANSWER = "readonly_answer"
    CLARIFY = "clarify"
    REJECT = "reject"


class GraphRoute(StrEnum):
    """The worker graph's next node (AM-16; table owned by T20)."""

    CLARIFY = "clarify"
    RETRIEVE = "retrieve"
    DRAFT = "draft"
    ANSWER_ONLY = "answer_only"
    ABSTAIN = "abstain"
    FREEZE = "freeze"
    AWAIT_DECISION = "await_decision"
    EXECUTE = "execute"
    RECOVER = "recover"
    PUBLISH = "publish"


class ModelRoute(StrEnum):
    """Which drafting model runs (AM-16, AM-31; table owned by T19)."""

    FAKE = "fake"
    QWEN3_8B = "qwen3:8b"


class ClarifyCause(StrEnum):
    """Why admission asked instead of starting work (Plan G ruling 12); each has one question template."""

    MISSING_ASSET = "missing_asset"
    ASSET_AMBIGUOUS = "asset_ambiguous"
    ASSET_CONFLICT = "asset_conflict"
    MISSING_INTERVAL = "missing_interval"
    INTERVAL_OUT_OF_RANGE = "interval_out_of_range"
    INTERVAL_CONFLICT = "interval_conflict"
    HINT = "hint"


class RejectCause(StrEnum):
    """Why admission refused (AM-16 `reject`): the API turns each into its own status and code."""

    USE_CLARIFICATIONS_ROUTE = "use_clarifications_route"  # 422 INVALID_INPUT
    SLOT_OCCUPIED = "slot_occupied"  # 409 SLOT_OCCUPIED


HOURS_MIN: Final = 1  # BS:547: 1-168 hours
HOURS_MAX: Final = 168
# An upper-case token that contains a digit (A17, PUMP-2): prose words and acronyms such as UTC never match, and a
# lower-case "a17" is not an asset id (contracts.AssetId requires the upper case too).
TEXT_ASSET: Final = re.compile(r"\b([A-Z][A-Z0-9_-]*[0-9][A-Z0-9_-]*)\b")
ASSET_ID: Final = re.compile(r"^[A-Z][A-Z0-9_-]{0,31}$")  # the same bound as contracts.AssetId
TEXT_WINDOW: Final = re.compile(r"\b(?:last|past)\s+(\d{1,3})\s*(hours?|hrs?|h|days?|d)\b", re.IGNORECASE)
TEXT_WINDOW_WORD: Final = re.compile(r"\b(?:last|past)\s+(hour|day)\b", re.IGNORECASE)
QUESTIONS: Final[dict[ClarifyCause, str]] = {
    ClarifyCause.MISSING_ASSET: "Which asset should be investigated? Name one asset id (for example A17).",
    ClarifyCause.ASSET_AMBIGUOUS: "The request names more than one asset ({ids}); name the one to investigate.",
    ClarifyCause.ASSET_CONFLICT: "The form names asset {field} but the text names {ids}; which one is meant?",
    ClarifyCause.MISSING_INTERVAL: (
        'Over which window? Give a number of hours between 1 and 168 (for example "last 24 hours").'
    ),
    ClarifyCause.INTERVAL_OUT_OF_RANGE: "The window must be between 1 and 168 hours; {n} hours was given.",
    ClarifyCause.INTERVAL_CONFLICT: "The form says {field} hours but the text says {n} hours; which is meant?",
    ClarifyCause.HINT: "Please confirm the asset and the window for this request.",
}


def text_assets(text: str) -> tuple[str, ...]:
    """The asset ids a text names, first mention first, each once; tokens longer than an AssetId are not ids."""
    return tuple(dict.fromkeys(m for m in TEXT_ASSET.findall(text) if ASSET_ID.fullmatch(m)))


def text_window(text: str) -> int | None:
    """The first look-back window the text names, in hours ("last 24 hours", "past 3 days", "last day"), or None."""
    found: list[tuple[int, int]] = []
    for match in TEXT_WINDOW.finditer(text):
        n = int(match.group(1))
        found.append((match.start(), n * 24 if match.group(2).lower().startswith("d") else n))
    for match in TEXT_WINDOW_WORD.finditer(text):
        found.append((match.start(), 24 if match.group(1).lower() == "day" else 1))
    return min(found)[1] if found else None


@dataclass(frozen=True)
class AdmissionFacts:
    """What the router sees: the request's kind, text and fields, whether the conversation holds a run, and an
    optional model hint (no producer exists yet; TODO(T19))."""

    kind: MessageKind
    text: str
    asset_id: str | None
    hours: int | None
    active_run: bool
    hint: AdmissionRoute | None = None


@dataclass(frozen=True)
class Resolution:
    """The text-versus-fields verdict: the agreed asset and window, or the first cause that needs a question."""

    asset_id: str | None
    hours: int | None
    cause: ClarifyCause | None = None
    question: str | None = None


def _ask(cause: ClarifyCause, **values: object) -> Resolution:
    return Resolution(None, None, cause, QUESTIONS[cause].format(**values))


def resolve(facts: AdmissionFacts) -> Resolution:
    """Ruling 12's table, asset rules before interval rules; the first disagreement names the one cause asked."""
    ids = text_assets(facts.text)
    asset = facts.asset_id
    if asset is not None:
        if ids and asset not in ids:
            return _ask(ClarifyCause.ASSET_CONFLICT, field=asset, ids=", ".join(ids))
    elif len(ids) == 1:
        asset = ids[0]
    elif not ids:
        return _ask(ClarifyCause.MISSING_ASSET)
    else:
        return _ask(ClarifyCause.ASSET_AMBIGUOUS, ids=", ".join(ids))
    window = text_window(facts.text)
    hours = facts.hours
    if hours is not None:
        if window is not None and window != hours:
            return _ask(ClarifyCause.INTERVAL_CONFLICT, field=hours, n=window)
    elif window is None:
        return _ask(ClarifyCause.MISSING_INTERVAL)
    elif not HOURS_MIN <= window <= HOURS_MAX:
        return _ask(ClarifyCause.INTERVAL_OUT_OF_RANGE, n=window)
    else:
        hours = window
    return Resolution(asset, hours)


@dataclass(frozen=True)
class AdmissionDecision:
    """The route, its cause for a clarify or a reject, the resolved asset and window for a run, the question asked."""

    route: AdmissionRoute
    cause: str | None = None
    asset_id: str | None = None
    hours: int | None = None
    question: str | None = None


@dataclass(frozen=True)
class AdmissionRule:
    """One row: the first rule whose predicate holds decides the route (`cause` fixed for reject and hint rows)."""

    name: str
    predicate: Callable[[AdmissionFacts, Resolution], bool]
    route: AdmissionRoute
    cause: str | None = None


_RUNS: Final = frozenset({MessageKind.INVESTIGATE, MessageKind.ASK})

# AM-16's table in evaluation order (Plan G ruling 16). The slot check precedes the clarify rows, so a busy
# conversation gets 409 before any question (1.3.6, T12 review note 2); the hint row can only turn a run into a
# clarification, never the reverse (SA:375); after the first three rows only investigate and ask remain, and the last
# two rows cover both.
ADMISSION_RULES: Final[tuple[AdmissionRule, ...]] = (
    AdmissionRule("status", lambda f, _: f.kind is MessageKind.STATUS, AdmissionRoute.STATUS_QUESTION),
    AdmissionRule(
        "clarification_kind",
        lambda f, _: f.kind is MessageKind.CLARIFICATION,
        AdmissionRoute.REJECT,
        RejectCause.USE_CLARIFICATIONS_ROUTE,
    ),
    AdmissionRule("slot_occupied", lambda f, _: f.active_run, AdmissionRoute.REJECT, RejectCause.SLOT_OCCUPIED),
    AdmissionRule("text_and_fields", lambda _, r: r.cause is not None, AdmissionRoute.CLARIFY),
    AdmissionRule("hint", lambda f, _: f.hint is AdmissionRoute.CLARIFY, AdmissionRoute.CLARIFY, ClarifyCause.HINT),
    AdmissionRule("investigate", lambda f, _: f.kind is MessageKind.INVESTIGATE, AdmissionRoute.INVESTIGATE),
    AdmissionRule("ask", lambda f, _: f.kind is MessageKind.ASK, AdmissionRoute.READONLY_ANSWER),
)
# BS:273's route is the clarification_reply entry (ruling 15): a reply bound to a question by id and version never
# passes through the message table, so it has a table of one row of its own and R129's walk covers both tables.
REPLY_RULES: Final[tuple[AdmissionRule, ...]] = (
    AdmissionRule("bound_reply", lambda f, _: f.kind is MessageKind.CLARIFICATION, AdmissionRoute.CLARIFICATION_REPLY),
)


def _first(rules: tuple[AdmissionRule, ...], facts: AdmissionFacts, resolution: Resolution) -> AdmissionDecision:
    for rule in rules:
        if not rule.predicate(facts, resolution):
            continue
        if rule.route is AdmissionRoute.CLARIFY:
            if rule.cause is None:  # the text-and-fields row carries the parser's own cause and question
                return AdmissionDecision(rule.route, resolution.cause, question=resolution.question)
            return AdmissionDecision(rule.route, rule.cause, question=QUESTIONS[ClarifyCause(rule.cause)])
        if rule.route in (AdmissionRoute.INVESTIGATE, AdmissionRoute.READONLY_ANSWER):
            return AdmissionDecision(rule.route, asset_id=resolution.asset_id, hours=resolution.hours)
        return AdmissionDecision(rule.route, rule.cause)
    raise LookupError(f"no admission rule matched kind {facts.kind.value}")  # the tables are total; a test walks them


def route_admission(facts: AdmissionFacts) -> AdmissionDecision:
    """The messages route's decision (AM-16). The parser runs only for kinds that would start a run."""
    if facts.kind in _RUNS:
        resolution = resolve(facts)
    else:
        resolution = Resolution(facts.asset_id, facts.hours)  # kind=status and kind=clarification skip the parser
    return _first(ADMISSION_RULES, facts, resolution)


def route_reply(facts: AdmissionFacts) -> AdmissionDecision:
    """The clarifications route's decision: a bound reply is the clarification_reply route."""
    return _first(REPLY_RULES, facts, Resolution(facts.asset_id, facts.hours))


class RunManifest(BaseModel):
    """What produced a run's draft: route, model digest, prompt and corpus versions (AM-80; written by T19)."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    run_id: UUID
    model_route: ModelRoute
    model_digest: str | None = Field(pattern=r"^[0-9a-f]{64}$")  # bare hex, as data/model-pins.json
    prompt_version: str = Field(min_length=1, max_length=60)
    corpus_version: str = Field(min_length=1, max_length=100)
    # Plan ruling 3: the externally visible mode keeps the delivered `vector_exact`, which says what the search
    # guarantees (exact, not approximate, vector search); AM-20.3's `mode=vector` is the SQL function's argument value.
    # TODO(T15): mcp-read, the caller of `search_procedures_scoped`, translates `vector_exact` to `mode=vector`.
    retrieval_mode: Literal["lexical", "vector_exact"]

    @model_validator(mode="after")
    def _real_models_carry_a_digest(self) -> RunManifest:
        # The fake route has nothing to pin; every real model route records the digest the worker verified (AM-31).
        if self.model_route is not ModelRoute.FAKE and self.model_digest is None:
            raise ValueError("model_digest is required for a real model route")
        return self
```

Run: `uv run python -m pytest tests/plan_g/test_routing_admission.py tests/plan_c/test_jobs_routes_outcomes.py -q`
Expected: `44 passed` (26 new, 18 of Plan C's route and job vocabulary tests unchanged).

- [ ] **Step 4: Gates and commit**

Format, lint and count characters on the three files. `routing.py` now imports `ops_core.contracts`, which imports
nothing from `routing`, so no cycle exists (check: `uv run python -c "import ops_core.routing"` prints nothing).

Run: `PYTHONUTF8=1 uv run python scripts/check.py`
Expected: `CHECK: GREEN`; pytest `729 passed, 98 skipped` (703 + 26).

Run: `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts`
Expected: exit 0 (no schema or example changed).

The live gate is not required here (no migration, service or live test changed; no service imports the new names
until Task 4).

```bash
git add core/src/ops_core/routing.py core/src/ops_core/contracts.py tests/plan_g/test_routing_admission.py
git commit -m "feat(core): the AM-16 admission router table and the text-versus-fields parser (T12)"
```

---

### Task 4: The store — the scoped key, the admission units, status answers, clarifications, the quota, the fault hook

**Files:**
- Create: `api/src/ops_api/idempotency.py`, `tests/plan_g/fakes.py`, `tests/plan_g/test_idempotency.py`,
  `tests/plan_g/test_store_units.py`
- Modify: `core/src/ops_core/persistence.py:466-468` (the `insert_job` comment), `:472-477` (five helpers before
  `claim_job`),
  `api/src/ops_api/store.py` (whole file; the three pre-T12 mutations stay until Task 5)

**Interfaces:**
- Consumes: `ops_core.routing.route_admission`, `route_reply`, `AdmissionFacts`, `AdmissionDecision`,
  `AdmissionRoute`, `RejectCause` (Task 3); `ops_core.contracts.StoredMessageKind` (Task 3);
  `ops_core.settings.AdmissionSettings` (Task 1); `ops_core.canonical.canonical_sha256`;
  `ops_core.testing.faults.Faults`, `FaultKind`; `ops_core.jobs.dedup_key`, `JobType`; the 0006 schema (Task 2).
- Produces (`ops_api.idempotency`): `HEADER = "Idempotency-Key"`, `KEY_REFUSAL` (ruling 1's message),
  `KeyInvalid(ValueError)`, `IdempotencyConflict(message=…)` with `.message`, `RecordRace`,
  `validate_key(raw: str | None, bounds: AdmissionSettings | None = None) -> str`,
  `Scope(tenant_id: UUID, subject: UUID, route: str, key: str)` with `.lock_key`, `scope_lock_key(scope) -> str`,
  `fingerprint(path: Mapping[str, str], body: Mapping[str, Any] | None) -> str`,
  `Verdict(status: int, body: dict[str, Any], replayed: bool = False)`, `Record(fingerprint, status, body)`,
  `Idem(scope, fingerprint, ttl_seconds, request_id)`, `RecordUnit` (protocol: `lock_scope`, `find_record`,
  `save_record`), `idempotent(unit, idem, work) -> Verdict`, `error_verdict(status, code, message, request_id) ->
  Verdict`, `render(body) -> bytes`, `VerdictResponse`, `response(verdict) -> VerdictResponse`.
- Produces (`ops_core.persistence`): `insert_job_untargeted(conn, *, job_type, tenant_id, run_id, key) -> bool`,
  `current_time(conn) -> datetime`, `latest_active_run(conn, conversation_id) -> DictRow | None`,
  `latest_run(conn, conversation_id) -> DictRow | None`, `latest_event(conn, run_id) -> DictRow | None`,
  `queued_count(conn) -> int`.
- Produces (`ops_api.store`): `Unit` (protocol over `RecordUnit`), `AdmissionStore` with `faults: Faults | None`,
  `unit(tenant_id)`, `open_conversation(*, idem, tenant_id, created_by) -> Verdict`, `admit_message(*, idem,
  tenant_id, conversation_id, requester, request, quota) -> Verdict`, `status_answer(unit, *, conversation_id,
  requester, request) -> Verdict`, `clarify(unit, *, conversation_id, requester, request, decision) -> Verdict`,
  `reply_clarification(*, idem, tenant_id, run_id, requester, reply) -> Verdict`, `decide_once(*, idem, tenant_id,
  proposal_id, reviewer, roles, request) -> Verdict`; `DbUnit(conn, tenant_id)`; `DbStore(AdmissionStore)`;
  `stamp`, `accepted_body`, `status_text`, `reply_text`, `STORED_KIND`, `NO_RUNS`, `CLARIFICATIONS_HINT`. The names
  `open_conversation`/`admit_message`/`decide_once` differ from the pre-T12 `create_conversation`/`admit`/`decide`
  on purpose: both sets live in `DbStore` for this one task, so Task 2's routes keep working (no interim red).
- Produces (`tests.plan_g.fakes`): `ISSUER`, `ALPHA`, `BETA`, `ALEX`, `SAM`, `LEE`, `JORDAN`, `DUAL`, `PERSONAS`,
  `ROWS`, `StubVerifier`, `FakeUnit`, `FakeStore` (tables `conversations`, `messages`, `runs`, `jobs`, `event_log`,
  `records`, `proposals`, `decided`, `decision_keys`; `locks`, `slot_occupied`, `clock`; `seed_question(run_id)`;
  T11's session methods).

- [ ] **Step 1: Write the failing key-and-unit test**

Create `tests/plan_g/test_idempotency.py`:

```python
"""The scoped Idempotency-Key without a database (BS:264, BS:299; Plan G rulings 1-6): the key's shape, the scope,
the fingerprint, and the lock-lookup-work-record order of one unit.

Catches: a key with a space, a control character or non-ASCII accepted (a proxy may rewrite it and the replay would
miss), a scope without the route template (one key reusable across routes), a fingerprint that a reformatted retry
changes or that ignores the conversation id (one key replaying another conversation's answer), work run before the
lock or the lookup, a replay that runs the work again, a conflict that records anything, and a record whose replay
renders different bytes from the first answer.
"""

import asyncio
from typing import Any
from uuid import UUID, uuid4

import pytest
from ops_api.idempotency import (
    Idem,
    IdempotencyConflict,
    KeyInvalid,
    Record,
    RecordRace,
    Scope,
    Verdict,
    error_verdict,
    fingerprint,
    idempotent,
    render,
    response,
    scope_lock_key,
    validate_key,
)
from ops_core.contracts import ErrorCode

ALPHA = UUID("3ea79c95-914c-52cb-9d10-c4e19dda8ff7")
ALEX = UUID("2fc05986-c7ec-544c-b628-fdb112bbf18a")
ROUTE = "POST /api/v1/conversations/{conversation_id}/messages"
SCOPE = Scope(ALPHA, ALEX, ROUTE, "key-0001")


def test_a_key_is_8_to_128_visible_ascii_characters() -> None:
    for good in ("a" * 8, "~" * 128, str(uuid4()), "!#$%&'()*+,-./:;<=>?@[]^_`{|}"):
        assert validate_key(good) == good
    for bad in (None, "", "a" * 7, "a" * 129, "has space", "tab\tkey12", "ключ-ключ", "a" * 8 + "\x7f", "a" * 8 + "\n"):
        with pytest.raises(KeyInvalid):
            validate_key(bad)


def test_the_scope_is_tenant_subject_route_template_and_key() -> None:
    assert SCOPE.lock_key == f"{ALPHA}|{ALEX}|{ROUTE}|key-0001" == scope_lock_key(SCOPE)
    other_route = Scope(ALPHA, ALEX, "POST /api/v1/conversations", "key-0001")
    assert other_route != SCOPE and other_route.lock_key != SCOPE.lock_key


def test_the_fingerprint_ignores_layout_but_not_the_path_or_the_body() -> None:
    conv = str(uuid4())
    body = {"kind": "investigate", "text": "Investigate A17.", "context": {"asset_id": "A17", "hours": 24}}
    reordered = {"context": {"hours": 24, "asset_id": "A17"}, "text": "Investigate A17.", "kind": "investigate"}
    same = fingerprint({"conversation_id": conv}, body)
    assert fingerprint({"conversation_id": conv}, reordered) == same
    assert fingerprint({"conversation_id": str(uuid4())}, body) != same  # a key reused on another conversation
    assert fingerprint({"conversation_id": conv}, {**body, "text": "Investigate A18."}) != same
    assert fingerprint({}, None) != fingerprint({}, {})


class Unit:
    """A RecordUnit that records the order of calls; `existing` is what the lookup finds, `full` makes save fail."""

    def __init__(self, existing: Record | None = None, *, full: bool = False) -> None:
        self.calls: list[str] = []
        self.existing = existing
        self.full = full
        self.saved: list[tuple[str, Verdict, int]] = []

    async def lock_scope(self, lock_key: str) -> None:
        self.calls.append(f"lock {lock_key}")

    async def find_record(self, scope: Scope) -> Record | None:
        self.calls.append("find")
        return self.existing

    async def save_record(self, scope: Scope, fingerprint: str, verdict: Verdict, ttl_seconds: int) -> bool:
        self.calls.append("save")
        if self.full:
            return False
        self.saved.append((fingerprint, verdict, ttl_seconds))
        return True


def run(unit: Unit, fp: str = "f" * 64) -> tuple[Verdict, list[str]]:
    worked: list[str] = []

    async def work() -> Verdict:
        unit.calls.append("work")
        worked.append("once")
        return Verdict(202, {"run_id": "r1"})

    verdict = asyncio.run(idempotent(unit, Idem(SCOPE, fp, 86400, uuid4()), work))
    return verdict, worked


def test_a_miss_locks_first_runs_the_work_once_and_records_last() -> None:
    unit = Unit()
    verdict, worked = run(unit)
    assert unit.calls == [f"lock {SCOPE.lock_key}", "find", "work", "save"]  # SA:188: the record is written last
    assert verdict == Verdict(202, {"run_id": "r1"}) and not verdict.replayed and worked == ["once"]
    assert unit.saved == [("f" * 64, Verdict(202, {"run_id": "r1"}), 86400)]


def test_a_hit_with_the_same_fingerprint_replays_without_running_the_work() -> None:
    unit = Unit(Record("f" * 64, 202, {"run_id": "r0"}))
    verdict, worked = run(unit)
    assert verdict.replayed and verdict == Verdict(202, {"run_id": "r0"}) and not worked
    assert "save" not in unit.calls


def test_a_hit_with_another_fingerprint_is_a_conflict_that_records_nothing() -> None:
    unit = Unit(Record("e" * 64, 202, {"run_id": "r0"}))
    with pytest.raises(IdempotencyConflict) as refused:
        run(unit)
    assert refused.value.message == "Idempotency-Key was already used with a different request"
    assert unit.calls == [f"lock {SCOPE.lock_key}", "find"]


def test_a_save_that_meets_an_existing_row_is_a_record_race() -> None:
    with pytest.raises(RecordRace):
        run(Unit(full=True))


def test_a_verdict_renders_the_same_bytes_whatever_its_key_order() -> None:
    assert render({"b": 1, "a": "é"}) == render({"a": "é", "b": 1}) == '{"a":"é","b":1}'.encode()
    limited = response(error_verdict(429, ErrorCode.RATE_LIMITED, "tenant queue is full", uuid4()))
    assert limited.status_code == 429 and limited.headers["retry-after"] == "5"
    body: dict[str, Any] = error_verdict(409, ErrorCode.SLOT_OCCUPIED, "busy", ALEX).body
    assert body == {"code": "SLOT_OCCUPIED", "message": "busy", "retryable": False, "request_id": str(ALEX)}
```

Run: `uv run python -m pytest tests/plan_g/test_idempotency.py -q`
Expected: `1 error in` (`ModuleNotFoundError: No module named 'ops_api.idempotency'`).

- [ ] **Step 2: The scoped key**

Create `api/src/ops_api/idempotency.py`:

```python
"""The scoped Idempotency-Key (BUILD_SPEC §7 BS:264, BS:299; SA:188, SA:297, SA:429; Plan G rulings 1-7).

A mutation's key is scoped to the tenant, the subject, the route template and the key itself, and its record is the
response: status and JSON body, written last in the unit that did the work, so a replay is the same answer and a
crash before commit leaves no record (R015, R016). Inside the unit the first statement is an advisory lock on the
scope: a second request with the same key waits for the first to commit and then replays its record, where a plain
unique index would hand it a 23505 whose DETAIL prints the tenant, the subject and the key (spike §1).

Two answers are never recorded because nothing was decided: a key reused for another request (409
IDEMPOTENCY_CONFLICT; recording it would turn a client bug into a permanent answer) and anything raised before or
outside the router's verdict (401, 403, the header and body shape refusals, 503). The rule of thumb in the code:
the router's verdict is recorded; everything before the router is not.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID

from fastapi.responses import JSONResponse
from ops_core.canonical import canonical_sha256
from ops_core.contracts import ErrorCode, SafeError
from ops_core.settings import AdmissionSettings

HEADER = "Idempotency-Key"
KEY_REFUSAL = "Idempotency-Key header is required (8–128 visible ASCII characters)"


class KeyInvalid(ValueError):
    """The Idempotency-Key header is missing or not 8-128 visible ASCII characters."""


class IdempotencyConflict(Exception):
    """The key was used before for a different request (or its expired record is not purged yet): never recorded."""

    def __init__(self, message: str = "Idempotency-Key was already used with a different request") -> None:
        super().__init__(message)
        self.message = message


class RecordRace(Exception):
    """The final record insert found a row the lookup did not see: the unit rolls back and the store re-reads."""


def validate_key(raw: str | None, bounds: AdmissionSettings | None = None) -> str:
    """The key if it is 8-128 characters in 0x21-0x7E (printable ASCII without space), else KeyInvalid (ruling 1).

    A key is an opaque client token: anything outside visible ASCII would compare differently after a proxy
    normalised it, and a space invites a header-folding ambiguity.
    """
    low, high = (bounds.idempotency_key_min, bounds.idempotency_key_max) if bounds else (8, 128)
    if raw is None or not low <= len(raw) <= high or any(not 0x21 <= ord(ch) <= 0x7E for ch in raw):
        raise KeyInvalid(KEY_REFUSAL)
    return raw


@dataclass(frozen=True)
class Scope:
    """Whose key this is and for which route (ruling 2): the route is the method and the path template, so the same
    key reused on another conversation is the same scope with a different fingerprint, a 409."""

    tenant_id: UUID
    subject: UUID
    route: str
    key: str

    @property
    def lock_key(self) -> str:
        """The string the unit's advisory lock hashes (`hashtextextended`, ruling 6)."""
        return f"{self.tenant_id}|{self.subject}|{self.route}|{self.key}"


def scope_lock_key(scope: Scope) -> str:
    """The advisory-lock string of a scope (the same as `Scope.lock_key`; named for the store and the tests)."""
    return scope.lock_key


def fingerprint(path: Mapping[str, str], body: Mapping[str, Any] | None) -> str:
    """What makes two requests "the same" (ruling 3): the path parameters and the validated body, canonical JSON v1,
    so whitespace and key order do not matter and a semantically equal retry replays."""
    return canonical_sha256({"path": dict(path), "body": None if body is None else dict(body)})


@dataclass(frozen=True)
class Verdict:
    """A recorded (or recordable) answer: the status and the JSON body a replay returns unchanged."""

    status: int
    body: dict[str, Any]
    replayed: bool = field(default=False, compare=False)


@dataclass(frozen=True)
class Record:
    """A live record as the lookup returns it."""

    fingerprint: str
    status: int
    body: dict[str, Any]


@dataclass(frozen=True)
class Idem:
    """Everything a unit needs to look up, decide and record: the scope, the fingerprint, the replay window, and the
    request id that error bodies carry (a replayed error keeps the first request's id, by design)."""

    scope: Scope
    fingerprint: str
    ttl_seconds: int
    request_id: UUID


class RecordUnit(Protocol):
    """The three record operations one transaction offers (`DbUnit` in SQL, the unit-test fake in memory)."""

    async def lock_scope(self, lock_key: str) -> None:
        """Take the transaction-scoped advisory lock on the scope (before any table lock: erratum on SA:188)."""
        ...

    async def find_record(self, scope: Scope) -> Record | None:
        """The live record of the scope, or None (an expired row is not a record: ruling 7)."""
        ...

    async def save_record(self, scope: Scope, fingerprint: str, verdict: Verdict, ttl_seconds: int) -> bool:
        """Insert the record; False when a row for the scope already exists (rowcount 0)."""
        ...


async def idempotent(unit: RecordUnit, idem: Idem, work: Callable[[], Awaitable[Verdict]]) -> Verdict:
    """Lock, look up, then replay, refuse or run `work` and record its verdict last (SA:188), all in the caller's
    transaction.

    Raises:
        IdempotencyConflict: the scope's record has another fingerprint.
        RecordRace: the insert met a row the lookup did not see; the caller rolls back and re-reads.
    """
    await unit.lock_scope(idem.scope.lock_key)
    found = await unit.find_record(idem.scope)
    if found is not None:
        if found.fingerprint != idem.fingerprint:
            raise IdempotencyConflict
        return Verdict(found.status, found.body, replayed=True)
    verdict = await work()
    if not await unit.save_record(idem.scope, idem.fingerprint, verdict, idem.ttl_seconds):
        # Impossible while every writer takes the lock first; an expired row the sweeper has not purged yet is the one
        # real case (the lookup skips it, the primary key does not), and the store's re-read answers it.
        raise RecordRace
    return verdict


def error_verdict(status: int, code: ErrorCode, message: str, request_id: UUID) -> Verdict:
    """A recorded refusal: the SafeError body (BS:301), never retryable, since the router decided it."""
    body = SafeError(code=code, message=message, retryable=False, request_id=request_id)
    return Verdict(status, body.model_dump(mode="json"))


def render(body: Mapping[str, Any]) -> bytes:
    """The one serialisation of a verdict's body: sorted keys and compact separators, so the first answer and every
    replay are the same bytes although jsonb stores keys in its own order."""
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


class VerdictResponse(JSONResponse):
    """A JSON response rendered by `render`, for first answers and replays alike (ruling 4)."""

    def render(self, content: Any) -> bytes:
        return render(content)


def response(verdict: Verdict) -> VerdictResponse:
    """The HTTP response of a verdict; a recorded 429 keeps its Retry-After on every replay (ruling 18)."""
    headers = {"Retry-After": "5"} if verdict.status == 429 else None
    return VerdictResponse(content=verdict.body, status_code=verdict.status, headers=headers)
```

Run: `uv run python -m pytest tests/plan_g/test_idempotency.py -q`
Expected: `8 passed`.

- [ ] **Step 3: The persistence helpers the units read and write through**

In `core/src/ops_core/persistence.py` (the comment in `insert_job` names its replacement; the five helpers go before
`claim_job`):

Edit 1 (old lines 466-468), replace:

```python
    # ON CONFLICT (target) and RETURNING need SELECT (spike §3): this helper serves the tests and the superuser;
    # the API's `resume_input` insert (T12) goes through a definer function or a target-less ON CONFLICT DO NOTHING.
    cur = await conn.execute(
```

with:

```python
    # ON CONFLICT (target) and RETURNING need SELECT (spike §3): this helper serves the tests and the superuser;
    # the API's `resume_input` insert goes through `insert_job_untargeted` (Plan G ruling 15).
    cur = await conn.execute(
```

Edit 2 (old lines 472-477), replace:

```python
    )
    row = await cur.fetchone()
    return None if row is None else UUID(str(row["id"]))


async def claim_job(conn: Conn, *, worker_name: str, tenant_ids: Sequence[UUID]) -> DictRow | None:
```

with:

```python
    )
    row = await cur.fetchone()
    return None if row is None else UUID(str(row["id"]))


async def insert_job_untargeted(conn: Conn, *, job_type: JobType, tenant_id: UUID, run_id: UUID, key: str) -> bool:
    """A wake-up inserted by a role that holds INSERT only on `jobs` (the api's `resume_input`, SA:419): a target-less
    ON CONFLICT DO NOTHING needs no SELECT, and the rowcount is the verdict, False for a dedup key already queued
    (Plan G spike §2; the same shape as the logout jti store)."""
    cur = await conn.execute(
        "INSERT INTO app.jobs (id, type, tenant_id, run_id, dedup_key, available_at)"
        " VALUES (%s, %s, %s, %s, %s, app.current_time()) ON CONFLICT DO NOTHING",
        (uuid4(), job_type.value, tenant_id, run_id, key),
    )
    return cur.rowcount == 1


async def current_time(conn: Conn) -> datetime:
    """The application clock (SA:157-158): `clock_timestamp()` plus the test offset when the testclock branch exists.

    Admission resolves "last N hours" against this, inside its unit, so a test that moves the clock moves the window
    the same way it moves the run's history and job rows (Plan G ruling 11; spike §7 measured the two clocks apart).
    """
    cur = await conn.execute("SELECT app.current_time() AS now")
    row = await cur.fetchone()
    if row is None:
        raise PersistenceError("app.current_time() returned nothing")
    now: datetime = row["now"]
    return now


async def latest_active_run(conn: Conn, conversation_id: UUID) -> DictRow | None:
    """The run holding the conversation's slot, under the caller's tenant unit (Plan G ruling 9: read, not locked)."""
    cur = await conn.execute(
        "SELECT run_id, state, state_version FROM app.runs WHERE conversation_id = %s AND slot_held"
        " ORDER BY created_at DESC LIMIT 1",
        (conversation_id,),
    )
    return await cur.fetchone()


async def latest_run(conn: Conn, conversation_id: UUID) -> DictRow | None:
    """The conversation's newest run of any state, the one a status question describes (ruling 14)."""
    cur = await conn.execute(
        "SELECT run_id, state, state_version FROM app.runs WHERE conversation_id = %s"
        " ORDER BY created_at DESC, run_id DESC LIMIT 1",
        (conversation_id,),
    )
    return await cur.fetchone()


async def latest_event(conn: Conn, run_id: UUID) -> DictRow | None:
    """A run's newest event by its gap-free sequence (`type`, `occurred_at`)."""
    cur = await conn.execute(
        "SELECT type, occurred_at FROM app.events WHERE run_id = %s ORDER BY sequence DESC LIMIT 1", (run_id,)
    )
    return await cur.fetchone()


async def queued_count(conn: Conn) -> int:
    """QUEUED runs of the unit's tenant: RLS scopes the count (spike §8), which is why the bound is per tenant."""
    cur = await conn.execute("SELECT count(*) AS n FROM app.runs WHERE state = 'QUEUED'")
    row = await cur.fetchone()
    return 0 if row is None else int(row["n"])


async def claim_job(conn: Conn, *, worker_name: str, tenant_ids: Sequence[UUID]) -> DictRow | None:
```

These are thin SQL with no branch of their own; the live tests of Tasks 2 and 6 run every one of them as `api`.

- [ ] **Step 4: Write the shared fake and the failing unit tests**

Create `tests/plan_g/fakes.py` (it inherits the real orchestration, so it fails to import until Step 5):

```python
"""In-memory stand-ins for the API's database, shared by the Plan G unit tests and (through a thin subclass) the
Plan D and Plan F API tests.

`FakeStore` inherits the real orchestration (`ops_api.store.AdmissionStore`: the advisory-lock-lookup-work-record
order, the router call, the quota, the clarify and status branches, the fault hook) and supplies only the primitive
operations, so the API tests exercise the code that runs against PostgreSQL, not a re-implementation of it. A unit
is atomic like a transaction: every table is copied at entry and restored when the unit raises, and the two
"savepoint" primitives check before they write. The persona constants mirror `data/seed-ids.json`.
"""

from __future__ import annotations

import copy
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from ops_api import store
from ops_api.idempotency import Record, Scope, Verdict
from ops_api.store import Accepted, Conflict, Decided, LoginState, NotFound, SessionRow
from ops_core.contracts import DecisionRequest, StoredMessageKind
from ops_core.states import ACTIVE_STATES, Intent
from ops_core.tokens import Principal, TokenRejected

ISSUER = "http://localhost:18080/realms/ops-dev"
ALPHA, BETA = UUID("3ea79c95-914c-52cb-9d10-c4e19dda8ff7"), UUID("5ab45c2c-1e12-5a0c-a2b9-66cd2ff05201")
ALEX = UUID("2fc05986-c7ec-544c-b628-fdb112bbf18a")
SAM = UUID("03f7eb09-e18d-5f33-bf75-12c57d5aaa54")
LEE = UUID("abcc1200-6791-57ab-87b5-9392d356b512")
JORDAN = UUID("cb551e64-83ec-582b-9047-8dadf20e151a")
DUAL = UUID("11111111-2222-5333-8444-555555555555")  # a subject seeded in two tenants
PERSONAS = {"alex": ALEX, "sam": SAM, "lee": LEE, "jordan": JORDAN, "dual": DUAL}
ROWS = {
    ALEX: [(ALPHA, "requester")],
    SAM: [(ALPHA, "reviewer")],
    LEE: [(ALPHA, "reader")],
    JORDAN: [(BETA, "reviewer")],
    DUAL: [(ALPHA, "requester"), (BETA, "reviewer")],
}
ACTIVE = {state.value for state in ACTIVE_STATES}
TABLES = ("conversations", "messages", "runs", "jobs", "event_log", "records", "proposals", "decided", "decision_keys")


class StubVerifier:
    """A bearer token is a persona's name; anything else is rejected (the real verifier is tested in Plan F)."""

    @property
    def ready(self) -> bool:
        return True

    async def load_keys(self) -> None:
        return None

    async def verify_async(self, token: str) -> Principal:
        if token not in PERSONAS:
            raise TokenRejected("unit test")
        return Principal(
            subject=str(PERSONAS[token]),
            azp="ops-dev-direct",
            audiences=("ops-api",),
            expires_at=2**31,
            claims={"preferred_username": token},
        )


class FakeUnit:
    """`ops_api.store.Unit` over the fake's tables, under one tenant."""

    def __init__(self, fake: FakeStore, tenant_id: UUID) -> None:
        self.fake = fake
        self.tenant_id = tenant_id

    async def lock_scope(self, lock_key: str) -> None:
        self.fake.locks.append(lock_key)  # one process: the lock is a record that it was taken first

    async def find_record(self, scope: Scope) -> Record | None:
        row = self.fake.records.get(scope)
        if row is None or row["expires"] <= self.fake.clock():
            return None
        return Record(row["fingerprint"], row["status"], copy.deepcopy(row["body"]))

    async def save_record(self, scope: Scope, fingerprint: str, verdict: Verdict, ttl_seconds: int) -> bool:
        if scope in self.fake.records:  # the primary key, expired or not
            return False
        self.fake.records[scope] = {
            "fingerprint": fingerprint,
            "status": verdict.status,
            "body": copy.deepcopy(verdict.body),
            "expires": self.fake.clock() + ttl_seconds,
        }
        return True

    async def now(self) -> datetime:
        return datetime.fromtimestamp(self.fake.clock(), UTC)

    async def conversation_exists(self, conversation_id: UUID) -> bool:
        return self.fake.conversations.get(conversation_id) == self.tenant_id

    async def insert_conversation(self, created_by: UUID) -> UUID:
        cid = uuid4()
        self.fake.conversations[cid] = self.tenant_id
        return cid

    async def queued_count(self) -> int:
        return sum(1 for r in self.fake.runs.values() if r["tenant_id"] == self.tenant_id and r["state"] == "QUEUED")

    def _runs_of(self, conversation_id: UUID) -> list[dict[str, Any]]:
        return [r for r in self.fake.runs.values() if r["conversation_id"] == conversation_id]

    async def active_run(self, conversation_id: UUID) -> bool:
        return any(r["state"] in ACTIVE for r in self._runs_of(conversation_id))

    async def latest_run(self, conversation_id: UUID) -> dict[str, Any] | None:
        runs = self._runs_of(conversation_id)
        if not runs:
            return None
        row = max(runs, key=lambda r: r["created_at"])
        return {"run_id": row["run_id"], "state": row["state"], "state_version": row["state_version"]}

    async def latest_event(self, run_id: UUID) -> dict[str, Any] | None:
        events = [e for e in self.fake.event_log if e["run_id"] == run_id]
        return None if not events else {"type": events[-1]["type"], "occurred_at": events[-1]["occurred_at"]}

    async def insert_message(
        self,
        *,
        conversation_id: UUID,
        kind: StoredMessageKind,
        text: str,
        context: dict[str, Any] | None,
        author: UUID | None,
    ) -> UUID:
        if (author is None) != (kind in (StoredMessageKind.STATUS_ANSWER, StoredMessageKind.CLARIFICATION_QUESTION)):
            raise AssertionError(f"revision 0006's author CHECK would refuse a {kind.value} row")
        message_id = uuid4()
        self.fake.messages.append(
            {
                "message_id": message_id,
                "tenant_id": self.tenant_id,
                "conversation_id": conversation_id,
                "kind": kind.value,
                "text": text,
                "context": copy.deepcopy(context),
                "author": author,
            }
        )
        return message_id

    async def start_run(
        self,
        *,
        conversation_id: UUID,
        requester: UUID,
        kind: StoredMessageKind,
        text: str,
        context: dict[str, Any],
        intent: Intent,
        asset_id: str,
        start_at: datetime,
        end_at: datetime,
        supersedes_run_id: UUID | None,
    ) -> Accepted:
        # The checks create_run makes, before anything is written (the savepoint's effect in DbUnit).
        sup = supersedes_run_id
        if sup is not None and (sup not in self.fake.runs or self.fake.runs[sup]["conversation_id"] != conversation_id):
            raise NotFound
        if self.fake.slot_occupied or await self.active_run(conversation_id):
            raise Conflict("SLOT_OCCUPIED")
        message_id = await self.insert_message(
            conversation_id=conversation_id, kind=kind, text=text, context=context, author=requester
        )
        run_id = uuid4()
        now = datetime.fromtimestamp(self.fake.clock(), UTC)
        self.fake.runs[run_id] = {
            "run_id": run_id,
            "tenant_id": self.tenant_id,
            "conversation_id": conversation_id,
            "message_id": message_id,
            "requester": requester,
            "intent": intent.value,
            "state": "QUEUED",
            "state_version": 1,
            "active_proposal_id": None,
            "asset_id": asset_id,
            "start_at": start_at,
            "end_at": end_at,
            "created_at": now + timedelta(microseconds=len(self.fake.runs)),  # strictly increasing per run
        }
        self.fake.jobs.append({"type": "investigate", "run_id": run_id, "dedup_key": f"{run_id}:1"})
        self.fake.event_log.append({"run_id": run_id, "type": "run.accepted", "occurred_at": now, "payload": {}})
        return Accepted(conversation_id, message_id, run_id, "QUEUED", 1)

    async def run(self, run_id: UUID) -> dict[str, Any] | None:
        row = self.fake.runs.get(run_id)
        if row is None or row["tenant_id"] != self.tenant_id:
            return None
        return {k: row[k] for k in ("run_id", "conversation_id", "state", "state_version")}

    async def latest_clarification(self, run_id: UUID) -> UUID | None:
        asked = [e for e in self.fake.event_log if e["run_id"] == run_id and e["type"] == "clarification.requested"]
        return None if not asked else UUID(str(asked[-1]["event_id"]))

    async def record_reply(
        self,
        *,
        run_id: UUID,
        conversation_id: UUID,
        question_id: UUID,
        text: str,
        context: dict[str, Any],
        author: UUID,
    ) -> UUID:
        key = f"{run_id}:{question_id}"
        if any(j["dedup_key"] == key for j in self.fake.jobs):
            raise Conflict("VERSION_CONFLICT")
        message_id = await self.insert_message(
            conversation_id=conversation_id,
            kind=StoredMessageKind.CLARIFICATION_REPLY,
            text=text,
            context=context,
            author=author,
        )
        self.fake.jobs.append({"type": "resume_input", "run_id": run_id, "dedup_key": key})
        self.fake.event_log.append(
            {
                "run_id": run_id,
                "type": "clarification.received",
                "occurred_at": datetime.fromtimestamp(self.fake.clock(), UTC),
                "payload": {"question_id": str(question_id), "message_id": str(message_id)},
            }
        )
        return message_id

    async def proposal(self, proposal_id: UUID) -> dict[str, Any] | None:
        row = self.fake.proposals.get(proposal_id)
        return row if row and row["tenant_id"] == self.tenant_id else None

    async def record_decision(
        self, *, proposal_id: UUID, reviewer: UUID, request: DecisionRequest, key: str
    ) -> Decided:
        row = await self.proposal(proposal_id)
        if row is None:
            raise NotFound
        if row["payload_sha256"] != request.expected_payload_sha256 or proposal_id in self.fake.decided:
            raise Conflict("VERSION_CONFLICT")  # a stale hash, or the first decision already won
        self.fake.decided.add(proposal_id)
        self.fake.decision_keys[proposal_id] = key
        status = "APPROVED" if request.decision == "approve" else "REJECTED"
        return Decided(proposal_id, row["run_id"], request.decision, status, 5)


class FakeStore(store.AdmissionStore):
    """The API's store in memory: the real orchestration over `FakeUnit`, plus the reads and T11's sessions."""

    def __init__(self) -> None:
        self.conversations: dict[UUID, UUID] = {}  # conversation -> tenant
        self.messages: list[dict[str, Any]] = []
        self.runs: dict[UUID, dict[str, Any]] = {}
        self.jobs: list[dict[str, Any]] = []
        self.event_log: list[dict[str, Any]] = []  # app.events rows (`events` is the read method)
        self.records: dict[Scope, dict[str, Any]] = {}
        self.proposals: dict[UUID, dict[str, Any]] = {}
        self.decided: set[UUID] = set()
        self.decision_keys: dict[UUID, str] = {}
        self.locks: list[str] = []
        self.slot_occupied = False  # force create_run's own refusal, as a concurrent admission would
        self.logins: dict[str, tuple[LoginState, float]] = {}  # login hash -> (state, expiry)
        self.sessions: dict[str, dict[str, Any]] = {}  # session hash -> row fields + last_seen, expires, revoked
        self.jtis: set[str] = set()
        self.clock = time.time  # tests replace it to age sessions and records

    @asynccontextmanager
    async def unit(self, tenant_id: UUID) -> AsyncIterator[store.Unit]:
        """All-or-nothing like a transaction: the tables are restored when the unit raises."""
        saved = {name: copy.deepcopy(getattr(self, name)) for name in TABLES}
        try:
            yield FakeUnit(self, tenant_id)
        except BaseException:
            for name, value in saved.items():
                setattr(self, name, value)
            raise

    def seed_question(self, run_id: UUID) -> UUID:
        """Put a run where the worker would (AWAITING_INPUT with a `clarification.requested` event); the event id."""
        event_id = uuid4()
        run = self.runs[run_id]
        run["state"], run["state_version"] = "AWAITING_INPUT", run["state_version"] + 2
        self.event_log.append(
            {
                "event_id": event_id,
                "run_id": run_id,
                "type": "clarification.requested",
                "occurred_at": datetime.fromtimestamp(self.clock(), UTC),
                "payload": {},
            }
        )
        return event_id

    async def membership(self, issuer: str, subject: UUID) -> store.Membership | None:
        return store.single_tenant(ROWS.get(subject, [])) if issuer == ISSUER else None

    async def run(self, tenant_id: UUID, run_id: UUID) -> dict[str, Any] | None:
        row = self.runs.get(run_id)
        return row if row and row["tenant_id"] == tenant_id else None

    async def proposal(self, tenant_id: UUID, proposal_id: UUID) -> dict[str, Any] | None:
        row = self.proposals.get(proposal_id)
        return row if row and row["tenant_id"] == tenant_id else None

    async def events(self, tenant_id: UUID, run_id: UUID, *, after: int, limit: int) -> list[dict[str, Any]]:
        return [] if await self.run(tenant_id, run_id) is None else [{"sequence": 1, "type": "run.accepted"}]

    async def begin_login(
        self, *, login_sha256: str, state_sha256: str, nonce_sha256: str, code_verifier: str, ttl_seconds: int
    ) -> None:
        self.logins[login_sha256] = (LoginState(state_sha256, nonce_sha256, code_verifier), self.clock() + ttl_seconds)

    async def take_login(self, login_sha256: str) -> LoginState | None:
        entry = self.logins.pop(login_sha256, None)
        return None if entry is None or entry[1] <= self.clock() else entry[0]

    async def create_session(
        self,
        *,
        session_sha256: str,
        issuer: str,
        subject: UUID,
        tenant_id: UUID,
        sid: str,
        username: str,
        csrf_secret_sha256: str,
        refresh_token_enc: bytes,
        absolute_seconds: int,
    ) -> None:
        self.sessions[session_sha256] = {
            "row": SessionRow(
                session_sha256, issuer, subject, tenant_id, sid, username, csrf_secret_sha256, refresh_token_enc
            ),
            "last_seen": self.clock(),
            "expires": self.clock() + absolute_seconds,
            "revoked": False,
        }

    async def live_session(self, session_sha256: str, *, idle_seconds: int) -> SessionRow | None:
        entry = self.sessions.get(session_sha256)
        now = self.clock()
        if entry is None or entry["revoked"] or entry["expires"] <= now or entry["last_seen"] <= now - idle_seconds:
            return None
        entry["last_seen"] = now
        row: SessionRow = entry["row"]
        return row

    async def revoke_session(self, session_sha256: str) -> SessionRow | None:
        entry = self.sessions.get(session_sha256)
        if entry is None or entry["revoked"]:
            return None
        entry["revoked"] = True
        row: SessionRow = entry["row"]
        return row

    async def expire_session(self, session_sha256: str, *, idle_seconds: int) -> SessionRow | None:
        entry = self.sessions.get(session_sha256)
        now = self.clock()
        if entry is None or entry["revoked"]:
            return None
        if entry["expires"] > now and entry["last_seen"] > now - idle_seconds:
            return None  # still live: not this method's to revoke
        entry["revoked"] = True
        row: SessionRow = entry["row"]
        return row

    async def record_logout(self, jti: str, *, expires_at: datetime, sid: str) -> int | None:
        if jti in self.jtis:
            return None
        self.jtis.add(jti)
        hit = [e for e in self.sessions.values() if e["row"].sid == sid and not e["revoked"]]
        for entry in hit:
            entry["revoked"] = True
        return len(hit)
```

Create `tests/plan_g/test_store_units.py`:

```python
"""The admission units of `ops_api.store.AdmissionStore` over the in-memory `Unit` (Plan G rulings 4-7, 9-15, 18,
24): what each route writes in one unit, what it records, and what it leaves behind when it fails.

Catches: a 202 whose record was not written in the same unit (a replay would start a second run), a changed body
replayed instead of refused, a quota that refuses status questions, a status answer or a clarification that starts a
run, writes a job or an event (R017, R018), a lost slot race that leaves the loser's message behind, a fault before
commit that keeps anything (R015), an expired unpurged key that replays its old answer, a clarification reply bound to
a stale version or another question, and a reviewer refusal that gets recorded.
"""

import asyncio
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from ops_api.idempotency import Idem, IdempotencyConflict, Scope, Verdict, fingerprint
from ops_api.store import Forbidden, resolve_interval
from ops_core import persistence
from ops_core.contracts import ClarificationReply, DecisionRequest, MessageRequest, load
from ops_core.settings import Profile
from ops_core.testing.faults import FaultKind, Faults

from tests.plan_g.fakes import ALEX, ALPHA, SAM, FakeStore

MESSAGES = "POST /api/v1/conversations/{conversation_id}/messages"
SAMPLE = {
    "kind": "investigate",
    "text": "Investigate the alerts on Asset A17 over the last 24 hours.",
    "context": {"asset_id": "A17", "hours": 24},
}


def idem(route: str, key: str, path: dict[str, str], body: dict[str, Any] | None, subject: UUID = ALEX) -> Idem:
    return Idem(Scope(ALPHA, subject, route, key), fingerprint(path, body), 86400, uuid4())


def conversation(fake: FakeStore) -> UUID:
    cid = uuid4()
    fake.conversations[cid] = ALPHA
    return cid


def admit(fake: FakeStore, cid: UUID, body: dict[str, Any], key: str, quota: int = 100) -> Verdict:
    request = load(MessageRequest, json.dumps(body))  # the API's own strict JSON parse
    return asyncio.run(
        fake.admit_message(
            idem=idem(MESSAGES, key, {"conversation_id": str(cid)}, request.model_dump(mode="json")),
            tenant_id=ALPHA,
            conversation_id=cid,
            requester=ALEX,
            request=request,
            quota=quota,
        )
    )


def test_a_run_and_its_record_commit_together_and_a_replay_returns_the_record() -> None:
    fake = FakeStore()
    cid = conversation(fake)
    first = admit(fake, cid, SAMPLE, "key-0001")
    assert first.status == 202 and not first.replayed and len(fake.runs) == 1 and len(fake.records) == 1
    again = admit(fake, cid, {**SAMPLE, "text": " " + SAMPLE["text"]}, "key-0001")  # stripped: the same request
    assert again.replayed and again == first and len(fake.runs) == 1 and len(fake.messages) == 1
    assert fake.locks == [next(iter(fake.records)).lock_key] * 2  # each unit locked the scope first


def test_a_changed_body_under_the_same_key_is_a_conflict_and_writes_nothing() -> None:
    fake = FakeStore()
    cid = conversation(fake)
    admit(fake, cid, SAMPLE, "key-0001")
    with pytest.raises(IdempotencyConflict):
        admit(fake, cid, {**SAMPLE, "context": {"asset_id": "A17", "hours": 12}}, "key-0001")
    assert len(fake.runs) == 1 and len(fake.records) == 1


def test_the_quota_refuses_only_what_would_start_a_run() -> None:
    fake = FakeStore()
    busy, idle = conversation(fake), conversation(fake)
    admit(fake, busy, SAMPLE, "key-0001")  # one QUEUED run in the tenant
    limited = admit(fake, idle, SAMPLE, "key-0002", quota=1)
    assert limited.status == 429 and limited.body["code"] == "RATE_LIMITED" and len(fake.runs) == 1
    status = admit(fake, idle, {"kind": "status", "text": "Anything running?"}, "key-0003", quota=1)
    assert status.status == 200


def test_a_status_question_writes_two_messages_and_nothing_else_even_while_busy() -> None:
    fake = FakeStore()
    cid = conversation(fake)
    accepted = admit(fake, cid, SAMPLE, "key-0001")
    jobs, events = len(fake.jobs), len(fake.event_log)
    answered = admit(fake, cid, {"kind": "status", "text": "Where is it?"}, "key-0002")
    run_id = accepted.body["run_id"]
    assert answered.status == 200 and answered.body["run_id"] == run_id and answered.body["status"] == "QUEUED"
    assert answered.body["answer"].startswith(f"Run {run_id} is QUEUED (version 1); the last recorded event is")
    question, answer = fake.messages[-2:]
    assert (question["kind"], question["author"]) == ("status_question", ALEX)
    assert (answer["kind"], answer["author"]) == ("status_answer", None)
    assert answer["context"] == {"run_id": run_id, "reply_to": str(question["message_id"])}
    assert (len(fake.runs), len(fake.jobs), len(fake.event_log)) == (1, jobs, events)  # R017: no run, job or event


def test_a_status_question_in_an_empty_conversation_says_so() -> None:
    fake = FakeStore()
    answered = admit(fake, conversation(fake), {"kind": "status", "text": "Anything?"}, "key-0001")
    assert answered.body["answer"] == "This conversation has no runs yet." and answered.body["run_id"] is None


def test_a_clarification_stores_the_request_and_the_question_and_starts_nothing() -> None:
    fake = FakeStore()
    cid = conversation(fake)
    body = {"kind": "investigate", "text": "Investigate B22 over the last 24 hours.", "context": {"asset_id": "A17"}}
    asked = admit(fake, cid, body, "key-0001")
    assert asked.status == 200 and asked.body["status"] == "clarification_needed"
    assert asked.body["cause"] == "asset_conflict" and "A17" in asked.body["question"]
    request, question = fake.messages
    assert (request["kind"], request["author"], request["context"]) == (
        "investigate",
        ALEX,
        {"asset_id": "A17", "hours": None},
    )
    assert (question["kind"], question["author"], question["text"]) == (
        "clarification_question",
        None,
        asked.body["question"],
    )
    assert question["context"] == {"cause": "asset_conflict", "reply_to": str(request["message_id"])}
    assert not fake.runs and not fake.jobs and not fake.event_log  # R018: a stored clarification, never a job


def test_a_lost_slot_race_is_a_recorded_409_that_leaves_no_message() -> None:
    fake = FakeStore()
    cid = conversation(fake)
    fake.slot_occupied = True  # create_run's own index refusal, as a concurrent admission would cause
    lost = admit(fake, cid, SAMPLE, "key-0001")
    assert lost.status == 409 and lost.body["code"] == "SLOT_OCCUPIED"
    assert not fake.messages and not fake.runs and len(fake.records) == 1  # AM-16: only the record is written


def test_a_fault_before_commit_leaves_no_message_no_run_and_no_record() -> None:
    fake = FakeStore()
    fake.faults = Faults(Profile.TEST)
    fake.faults.arm(FaultKind.DROP_BEFORE_COMMIT)
    cid = conversation(fake)
    with pytest.raises(persistence.PersistenceError):
        admit(fake, cid, SAMPLE, "key-0001")
    assert not fake.messages and not fake.runs and not fake.jobs and not fake.records  # R015
    retried = admit(fake, cid, SAMPLE, "key-0001")  # nothing was recorded, so the same key does the work now
    assert retried.status == 202 and not retried.replayed and len(fake.jobs) == 1


def test_an_expired_record_the_sweeper_has_not_purged_blocks_its_key() -> None:
    fake = FakeStore()
    cid = conversation(fake)
    admit(fake, cid, SAMPLE, "key-0001")
    clock = fake.clock()
    fake.clock = lambda: clock + 86401  # past the replay window, before any purge
    other = conversation(fake)
    with pytest.raises(IdempotencyConflict) as refused:
        admit(fake, other, SAMPLE, "key-0001")  # the lookup misses, the insert meets the old row: the re-read path
    assert refused.value.message == "Idempotency-Key is not reusable yet; use a new key"
    assert not any(r["conversation_id"] == other for r in fake.runs.values())  # the work was rolled back


def test_the_interval_is_resolved_once_on_the_units_clock() -> None:
    fake = FakeStore()
    fixed = datetime(2026, 10, 10, 8, 30, 15, 987654, tzinfo=UTC)
    fake.clock = fixed.timestamp
    accepted = admit(fake, conversation(fake), SAMPLE, "key-0001")
    run = fake.runs[UUID(accepted.body["run_id"])]
    assert (run["start_at"], run["end_at"]) == resolve_interval(24, fixed)
    assert run["end_at"] == datetime(2026, 10, 10, 8, 30, 15, tzinfo=UTC)


def reply(fake: FakeStore, run_id: UUID, question_id: UUID, version: int, key: str) -> Verdict:
    body = load(
        ClarificationReply,
        json.dumps({"question_id": str(question_id), "expected_version": version, "context": {"hours": 12}}),
    )
    return asyncio.run(
        fake.reply_clarification(
            idem=idem(
                "POST /api/v1/runs/{run_id}/clarifications", key, {"run_id": str(run_id)}, body.model_dump(mode="json")
            ),
            tenant_id=ALPHA,
            run_id=run_id,
            requester=ALEX,
            reply=body,
        )
    )


def test_a_reply_binds_to_the_outstanding_question_and_its_version() -> None:
    fake = FakeStore()
    run_id = UUID(admit(fake, conversation(fake), SAMPLE, "key-0001").body["run_id"])
    assert reply(fake, run_id, uuid4(), 1, "key-0002").status == 409  # QUEUED: no question is outstanding
    question = fake.seed_question(run_id)
    assert reply(fake, run_id, question, 1, "key-0003").body["code"] == "VERSION_CONFLICT"
    assert reply(fake, run_id, uuid4(), 3, "key-0004").body["message"] == "no outstanding clarification"
    assert reply(fake, uuid4(), question, 3, "key-0005").body["message"] == "no such run"
    accepted = reply(fake, run_id, question, 3, "key-0006")
    assert (
        accepted.status == 202 and accepted.body["status"] == "AWAITING_INPUT" and accepted.body["state_version"] == 3
    )
    assert fake.jobs[-1] == {"type": "resume_input", "run_id": run_id, "dedup_key": f"{run_id}:{question}"}
    assert fake.event_log[-1]["type"] == "clarification.received"
    assert (
        fake.messages[-1]["kind"] == "clarification_reply"
        and fake.messages[-1]["text"] == "Clarification: asset -, hours 12"
    )
    again = reply(fake, run_id, question, 3, "key-0007")  # a second answer under a new key
    assert again.status == 409 and again.body["message"] == "the clarification was already answered"


def decide(fake: FakeStore, proposal_id: UUID, subject: UUID, roles: frozenset[str], key: str) -> Verdict:
    body = DecisionRequest(expected_revision=1, expected_payload_sha256="9" * 64, decision="approve")
    return asyncio.run(
        fake.decide_once(
            idem=idem(
                "POST /api/v1/proposals/{proposal_id}/decisions",
                key,
                {"proposal_id": str(proposal_id)},
                body.model_dump(mode="json"),
                subject,
            ),
            tenant_id=ALPHA,
            proposal_id=proposal_id,
            reviewer=subject,
            roles=roles,
            request=body,
        )
    )


def test_a_decision_carries_its_key_and_a_reviewer_refusal_is_never_recorded() -> None:
    fake = FakeStore()
    pid, rid = uuid4(), uuid4()
    fake.proposals[pid] = {
        "proposal_id": pid,
        "tenant_id": ALPHA,
        "run_id": rid,
        "revision": 1,
        "payload_sha256": "9" * 64,
        "authored_by": [ALEX],
        "requester": ALEX,
    }
    with pytest.raises(Forbidden):
        decide(fake, pid, ALEX, frozenset({"requester"}), "key-0001")
    assert not fake.records and not fake.decided
    decided = decide(fake, pid, SAM, frozenset({"reviewer"}), "key-0002")
    assert decided.status == 200 and decided.body["status"] == "APPROVED" and fake.decision_keys[pid] == "key-0002"
    assert decide(fake, pid, SAM, frozenset({"reviewer"}), "key-0003").status == 409  # the first decision won
```

Run: `uv run python -m pytest tests/plan_g/test_store_units.py -q`
Expected: `1 error in` (`AttributeError: module 'ops_api.store' has no attribute 'AdmissionStore'`).

- [ ] **Step 5: The admission units**

Replace `api/src/ops_api/store.py` with:

```python
"""The API's door to the database as role `api`: identity through `resolve_identity`, admission through the AM-16
router and `create_run`, clarification replies, decisions through `record_decision`; reads under the tenant's unit,
which RLS scopes. T11: the session store (login_state, sessions, logout_jti).

Every mutation is one idempotent unit (Plan G rulings 4-6, 21): advisory lock on the key's scope, record lookup,
the route's own checks and the router's verdict, the effect, and the record written last (SA:188), committed
together, so the response a client gets is exactly what a replay of the same key returns, and a crash before commit
leaves neither (R015). The record is the response, which is why the units build HTTP status codes and bodies: the
row must hold them before the commit. The orchestration (`AdmissionStore`) runs over a `Unit` of primitive
operations; `DbUnit` is their SQL, and the unit-test fake supplies an in-memory `Unit` to the same orchestration.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID, uuid4

from ops_core import persistence
from ops_core.contracts import (
    ClarificationReply,
    DecisionRequest,
    ErrorCode,
    MessageKind,
    MessageRequest,
    StoredMessageKind,
)
from ops_core.jobs import JobType, dedup_key
from ops_core.outcomes import EventType
from ops_core.routing import (
    AdmissionDecision,
    AdmissionFacts,
    AdmissionRoute,
    RejectCause,
    route_admission,
    route_reply,
)
from ops_core.states import Intent, RunState
from ops_core.testing.faults import FaultKind, Faults
from psycopg.types.json import Jsonb

from ops_api.idempotency import (
    Idem,
    IdempotencyConflict,
    Record,
    RecordRace,
    RecordUnit,
    Scope,
    Verdict,
    error_verdict,
    idempotent,
)


class Forbidden(Exception):
    """The caller is authenticated but may not do this (maps to 403; never recorded)."""


class NotFound(Exception):
    """The row does not exist in the caller's tenant (maps to 404)."""


class Conflict(Exception):
    """The request lost a race or names a stale version (maps to 409); `code` is the ErrorCode value."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class Internal(Exception):
    """A definer function refused input the API already validated, or returned nothing: a server defect, never the
    client's (maps to 503)."""


@dataclass(frozen=True)
class Membership:
    """A subject's tenant and roles, resolved from the seeded memberships."""

    tenant_id: UUID
    roles: frozenset[str]


@dataclass(frozen=True)
class Accepted:
    """What a started run returns after the message, run, job and `run.accepted` are written."""

    conversation_id: UUID
    message_id: UUID
    run_id: UUID
    status: str
    state_version: int


@dataclass(frozen=True)
class Decided:
    """What a recorded decision returns after the transition."""

    proposal_id: UUID
    run_id: UUID
    decision: str
    status: str
    state_version: int


@dataclass(frozen=True)
class LoginState:
    """One authorization request in flight: the hashes the callback compares and the PKCE verifier it spends."""

    state_sha256: str
    nonce_sha256: str
    code_verifier: str = field(repr=False)


@dataclass(frozen=True)
class SessionRow:
    """A live session as the identity dependency sees it; `refresh_token_enc` is opened only at logout."""

    session_sha256: str
    issuer: str
    subject: UUID
    tenant_id: UUID
    sid: str
    username: str
    csrf_secret_sha256: str = field(repr=False)
    refresh_token_enc: bytes = field(repr=False)


def resolve_interval(hours: int, now: datetime) -> tuple[datetime, datetime]:
    """ "Last N hours" resolved once, at admission, to whole seconds (BUILD_SPEC §7: retries keep the window)."""
    end = now.replace(microsecond=0)
    return end - timedelta(hours=hours), end


def check_reviewer(membership: Membership, *, requester: UUID, authored_by: list[UUID], reviewer: UUID) -> None:
    """Independence (BUILD_SPEC §9, SA:539): a current reviewer who is neither the requester nor a content author."""
    if "reviewer" not in membership.roles:
        raise Forbidden
    if reviewer == requester or reviewer in authored_by:
        raise Forbidden


def single_tenant(rows: list[tuple[UUID, str]]) -> Membership | None:
    """Fold (tenant, role) rows into one Membership; None when there are none or they span tenants."""
    tenants = {tenant for tenant, _ in rows}
    if len(tenants) != 1:
        # TODO(T11): explicit tenant selection; until then a multi-tenant subject cannot act, and roles never merge.
        return None
    return Membership(next(iter(tenants)), frozenset(role for _, role in rows))


def map_refusal(exc: persistence.Refused) -> Exception:
    """A function's DETAIL code → the HTTP class BUILD_SPEC §7 names; the code itself never reaches the client."""
    if exc.code in ("NOT_REVIEWER", "SELF_REVIEW", "MEMBERSHIP_INACTIVE"):
        return Forbidden()
    if exc.code == "SLOT_OCCUPIED":
        return Conflict("SLOT_OCCUPIED")
    if exc.code == "INVALID_ARGUMENT":
        return Internal()  # the API's own validation makes this unreachable; a 409 would be a false message
    return Conflict("VERSION_CONFLICT")


def stamp(value: datetime) -> str:
    """A timestamp as UTC `...Z` with whole seconds, the API's one spelling."""
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


STORED_KIND = {
    MessageKind.INVESTIGATE: StoredMessageKind.INVESTIGATE,
    MessageKind.ASK: StoredMessageKind.ASK,
    MessageKind.STATUS: StoredMessageKind.STATUS_QUESTION,
}  # the requester's own row (ruling 26); a clarification reply is stored by its own route
NO_RUNS = "This conversation has no runs yet."
CLARIFICATIONS_HINT = "clarification replies go to /api/v1/runs/{run_id}/clarifications"


def accepted_body(conversation_id: UUID, message_id: UUID, run_id: UUID, status: str, version: int) -> dict[str, Any]:
    """BS:299's accepted response; `stream_url` waits for the stream route (TODO(T27))."""
    return {
        "conversation_id": str(conversation_id),
        "message_id": str(message_id),
        "run_id": str(run_id),
        "status": status,
        "state_version": version,
        "status_url": f"/api/v1/runs/{run_id}",
        "events_url": f"/api/v1/runs/{run_id}/events",
    }


def status_text(run: dict[str, Any] | None, event: dict[str, Any] | None) -> str:
    """The status answer, from recorded state and events only (AM-16 status_question; ruling 14)."""
    if run is None:
        return NO_RUNS
    head = f"Run {run['run_id']} is {run['state']} (version {run['state_version']})"
    if event is None:
        return f"{head}; no event is recorded yet."
    return f"{head}; the last recorded event is {event['type']} at {stamp(event['occurred_at'])}."


def reply_text(reply: ClarificationReply) -> str:
    """The stored text of a clarification reply: the fields it supplies, rendered (ruling 15)."""
    asset = reply.context.asset_id or "-"
    hours = "-" if reply.context.hours is None else str(reply.context.hours)
    return f"Clarification: asset {asset}, hours {hours}"


class Unit(RecordUnit, Protocol):
    """The primitive operations of one admission transaction under one tenant (Plan G ruling 21)."""

    async def now(self) -> datetime:
        """The application clock, read inside the unit (ruling 11)."""
        ...

    async def conversation_exists(self, conversation_id: UUID) -> bool:
        """Whether the conversation is the tenant's."""
        ...

    async def insert_conversation(self, created_by: UUID) -> UUID:
        """Create an empty conversation."""
        ...

    async def queued_count(self) -> int:
        """QUEUED runs of the tenant (ruling 18)."""
        ...

    async def active_run(self, conversation_id: UUID) -> bool:
        """Whether a run holds the conversation's slot (read, not locked: ruling 9)."""
        ...

    async def latest_run(self, conversation_id: UUID) -> dict[str, Any] | None:
        """The newest run: `run_id`, `state`, `state_version`."""
        ...

    async def latest_event(self, run_id: UUID) -> dict[str, Any] | None:
        """The run's newest event: `type`, `occurred_at`."""
        ...

    async def insert_message(
        self,
        *,
        conversation_id: UUID,
        kind: StoredMessageKind,
        text: str,
        context: dict[str, Any] | None,
        author: UUID | None,
    ) -> UUID:
        """Insert one message; `author` is None for the system kinds only (revision 0006's CHECK)."""
        ...

    async def start_run(
        self,
        *,
        conversation_id: UUID,
        requester: UUID,
        kind: StoredMessageKind,
        text: str,
        context: dict[str, Any],
        intent: Intent,
        asset_id: str,
        start_at: datetime,
        end_at: datetime,
        supersedes_run_id: UUID | None,
    ) -> Accepted:
        """Message plus `create_run`, atomically within the unit: Conflict (slot) or NotFound (supersedes) leave
        neither, and the unit stays usable for the record."""
        ...

    async def run(self, run_id: UUID) -> dict[str, Any] | None:
        """A run of the tenant: `run_id`, `conversation_id`, `state`, `state_version`."""
        ...

    async def latest_clarification(self, run_id: UUID) -> UUID | None:
        """The event id of the run's newest `clarification.requested`, or None."""
        ...

    async def record_reply(
        self,
        *,
        run_id: UUID,
        conversation_id: UUID,
        question_id: UUID,
        text: str,
        context: dict[str, Any],
        author: UUID,
    ) -> UUID:
        """Message, `resume_input` job and `clarification.received`, atomically within the unit; Conflict when the
        question was already answered (the job's dedup key exists)."""
        ...

    async def proposal(self, proposal_id: UUID) -> dict[str, Any] | None:
        """A proposal with its run's requester (`revision`, `authored_by`, `requester`, ...)."""
        ...

    async def record_decision(
        self, *, proposal_id: UUID, reviewer: UUID, request: DecisionRequest, key: str
    ) -> Decided:
        """`record_decision` within the unit; Conflict or NotFound leave the unit usable, Forbidden ends it."""
        ...


Work = Callable[[Unit], Awaitable[Verdict]]


class AdmissionStore:
    """The idempotent mutations of T12, written once over `Unit` (rulings 13-15, 21-25)."""

    faults: Faults | None = None  # set by create_app under PROFILE=test only (ruling 24)

    def unit(self, tenant_id: UUID) -> AbstractAsyncContextManager[Unit]:
        """One transaction under the tenant; implementations roll back on any exception."""
        raise NotImplementedError

    async def _idempotent(self, tenant_id: UUID, idem: Idem, work: Work) -> Verdict:
        try:
            async with self.unit(tenant_id) as unit:
                return await idempotent(unit, idem, lambda: work(unit))
        except RecordRace:
            pass  # the unit rolled back; the re-read below answers from whatever row blocked the insert
        async with self.unit(tenant_id) as unit:
            await unit.lock_scope(idem.scope.lock_key)
            found = await unit.find_record(idem.scope)
        if found is None:
            # The row that blocked the insert is an expired record the sweeper has not purged yet (ruling 7).
            raise IdempotencyConflict("Idempotency-Key is not reusable yet; use a new key")
        if found.fingerprint != idem.fingerprint:
            raise IdempotencyConflict
        return Verdict(found.status, found.body, replayed=True)

    async def open_conversation(self, *, idem: Idem, tenant_id: UUID, created_by: UUID) -> Verdict:
        """201 `{conversation_id}`; a replay returns the same id (ruling 22)."""

        async def work(unit: Unit) -> Verdict:
            cid = await unit.insert_conversation(created_by)
            return Verdict(201, {"conversation_id": str(cid)})

        return await self._idempotent(tenant_id, idem, work)

    async def admit_message(
        self,
        *,
        idem: Idem,
        tenant_id: UUID,
        conversation_id: UUID,
        requester: UUID,
        request: MessageRequest,
        quota: int,
    ) -> Verdict:
        """The messages route's unit in ruling 21's order: conversation, quota count, active run, router, effect."""
        rid = idem.request_id

        async def work(unit: Unit) -> Verdict:
            if not await unit.conversation_exists(conversation_id):
                return error_verdict(404, ErrorCode.NOT_FOUND, "no such conversation", rid)
            queued = await unit.queued_count()
            context = request.context
            decision = route_admission(
                AdmissionFacts(
                    kind=request.kind,
                    text=request.text,
                    asset_id=None if context is None else context.asset_id,
                    hours=None if context is None else context.hours,
                    active_run=await unit.active_run(conversation_id),
                    hint=None,  # TODO(T19): the model router may supply a hint; it can only produce clarify
                )
            )
            if decision.route is AdmissionRoute.REJECT:
                if decision.cause == RejectCause.SLOT_OCCUPIED:
                    return error_verdict(
                        409, ErrorCode.SLOT_OCCUPIED, "the conversation already has an active run", rid
                    )
                return error_verdict(422, ErrorCode.INVALID_INPUT, CLARIFICATIONS_HINT, rid)
            if decision.route is AdmissionRoute.STATUS_QUESTION:
                return await self.status_answer(
                    unit, conversation_id=conversation_id, requester=requester, request=request
                )
            if decision.route is AdmissionRoute.CLARIFY:
                return await self.clarify(
                    unit, conversation_id=conversation_id, requester=requester, request=request, decision=decision
                )
            # Ruling 18: the quota bounds what would start a run; a status question or a clarification adds nothing
            # to the queue, so the count read above refuses only here.
            if queued >= quota:
                return error_verdict(429, ErrorCode.RATE_LIMITED, "tenant queue is full", rid)
            return await self._start(
                unit,
                idem=idem,
                conversation_id=conversation_id,
                requester=requester,
                request=request,
                decision=decision,
            )

        return await self._idempotent(tenant_id, idem, work)

    async def status_answer(
        self, unit: Unit, *, conversation_id: UUID, requester: UUID, request: MessageRequest
    ) -> Verdict:
        """The status_question route: the question and its answer as two messages, no run, no job, no event."""
        question_id = await unit.insert_message(
            conversation_id=conversation_id,
            kind=StoredMessageKind.STATUS_QUESTION,
            text=request.text,
            context=None if request.context is None else request.context.model_dump(mode="json"),
            author=requester,
        )
        run = await unit.latest_run(conversation_id)
        event = None if run is None else await unit.latest_event(run["run_id"])
        answer = status_text(run, event)
        answer_id = await unit.insert_message(
            conversation_id=conversation_id,
            kind=StoredMessageKind.STATUS_ANSWER,
            text=answer,
            context={"run_id": None if run is None else str(run["run_id"]), "reply_to": str(question_id)},
            author=None,
        )
        return Verdict(
            200,
            {
                "conversation_id": str(conversation_id),
                "question_id": str(question_id),
                "answer_id": str(answer_id),
                "answer": answer,
                "run_id": None if run is None else str(run["run_id"]),
                "status": None if run is None else run["state"],
                "state_version": None if run is None else run["state_version"],
            },
        )

    async def clarify(
        self,
        unit: Unit,
        *,
        conversation_id: UUID,
        requester: UUID,
        request: MessageRequest,
        decision: AdmissionDecision,
    ) -> Verdict:
        """The clarify route: the request and the stored question as two messages, no run (R018: never a guess)."""
        message_id = await unit.insert_message(
            conversation_id=conversation_id,
            kind=STORED_KIND[request.kind],
            text=request.text,
            context=None if request.context is None else request.context.model_dump(mode="json"),
            author=requester,
        )
        question = decision.question or ""
        question_id = await unit.insert_message(
            conversation_id=conversation_id,
            kind=StoredMessageKind.CLARIFICATION_QUESTION,
            text=question,
            context={"cause": decision.cause, "reply_to": str(message_id)},
            author=None,
        )
        return Verdict(
            200,
            {
                "conversation_id": str(conversation_id),
                "message_id": str(message_id),
                "question_id": str(question_id),
                "cause": decision.cause,
                "question": question,
                "status": "clarification_needed",
            },
        )

    async def _start(
        self,
        unit: Unit,
        *,
        idem: Idem,
        conversation_id: UUID,
        requester: UUID,
        request: MessageRequest,
        decision: AdmissionDecision,
    ) -> Verdict:
        """The investigate and readonly_answer routes: the interval resolved once on the database clock, then message
        and run together (R015); the record keeps the interval, so a replay never moves it (R018)."""
        if decision.asset_id is None or decision.hours is None:
            raise Internal("the router admitted a run without an asset or a window")
        start_at, end_at = resolve_interval(decision.hours, await unit.now())
        intent = Intent.INVESTIGATE if decision.route is AdmissionRoute.INVESTIGATE else Intent.ANSWER_ONLY
        try:
            accepted = await unit.start_run(
                conversation_id=conversation_id,
                requester=requester,
                kind=STORED_KIND[request.kind],
                text=request.text,
                context={"asset_id": decision.asset_id, "hours": decision.hours},
                intent=intent,
                asset_id=decision.asset_id,
                start_at=start_at,
                end_at=end_at,
                supersedes_run_id=request.supersedes_run_id,
            )
        except NotFound:
            return error_verdict(404, ErrorCode.NOT_FOUND, "no such superseded run", idem.request_id)
        except Conflict:
            # A concurrent admission took the slot after the active-run read: the index is the backstop (ruling 9).
            return error_verdict(
                409, ErrorCode.SLOT_OCCUPIED, "the conversation already has an active run", idem.request_id
            )
        if self.faults is not None and self.faults.take(FaultKind.DROP_BEFORE_COMMIT):
            # R015's crash: the message and the run exist inside the transaction, the record and the commit do not.
            raise persistence.PersistenceError("fault: drop_before_commit")
        return Verdict(
            202,
            accepted_body(
                conversation_id, accepted.message_id, accepted.run_id, accepted.status, accepted.state_version
            ),
        )

    async def reply_clarification(
        self, *, idem: Idem, tenant_id: UUID, run_id: UUID, requester: UUID, reply: ClarificationReply
    ) -> Verdict:
        """BS:273's route, the clarification_reply entry (ruling 15): bound to the run's outstanding question and its
        expected version; message, `resume_input` job and `clarification.received` together, then 202."""
        rid = idem.request_id

        async def work(unit: Unit) -> Verdict:
            run = await unit.run(run_id)
            if run is None:
                return error_verdict(404, ErrorCode.NOT_FOUND, "no such run", rid)
            if run["state"] != RunState.AWAITING_INPUT.value or run["state_version"] != reply.expected_version:
                return error_verdict(409, ErrorCode.VERSION_CONFLICT, "the run is not waiting at that version", rid)
            if await unit.latest_clarification(run_id) != reply.question_id:
                return error_verdict(404, ErrorCode.NOT_FOUND, "no outstanding clarification", rid)
            text = reply_text(reply)
            decision = route_reply(
                AdmissionFacts(
                    kind=MessageKind.CLARIFICATION,
                    text=text,
                    asset_id=reply.context.asset_id,
                    hours=reply.context.hours,
                    active_run=True,
                )
            )
            if decision.route is not AdmissionRoute.CLARIFICATION_REPLY:
                raise Internal("a bound reply did not route to clarification_reply")
            try:
                message_id = await unit.record_reply(
                    run_id=run_id,
                    conversation_id=run["conversation_id"],
                    question_id=reply.question_id,
                    text=text,
                    context=reply.context.model_dump(mode="json"),
                    author=requester,
                )
            except Conflict:
                return error_verdict(409, ErrorCode.VERSION_CONFLICT, "the clarification was already answered", rid)
            return Verdict(
                202, accepted_body(run["conversation_id"], message_id, run_id, run["state"], run["state_version"])
            )

        return await self._idempotent(tenant_id, idem, work)

    async def decide_once(
        self,
        *,
        idem: Idem,
        tenant_id: UUID,
        proposal_id: UUID,
        reviewer: UUID,
        roles: frozenset[str],
        request: DecisionRequest,
    ) -> Verdict:
        """The first decision on the exact revision and hash by an independent current reviewer (SA:454); the key
        is also stored on the decision row (ruling 21). A reviewer refusal raises Forbidden: never recorded."""
        rid = idem.request_id

        async def work(unit: Unit) -> Verdict:
            row = await unit.proposal(proposal_id)
            if row is None:
                return error_verdict(404, ErrorCode.NOT_FOUND, "no such proposal", rid)
            check_reviewer(
                Membership(tenant_id, roles),
                requester=row["requester"],
                authored_by=list(row["authored_by"]),
                reviewer=reviewer,
            )
            stale = "the proposal is not the active, undecided revision"
            if row["revision"] != request.expected_revision:
                return error_verdict(409, ErrorCode.VERSION_CONFLICT, stale, rid)
            try:
                decided = await unit.record_decision(
                    proposal_id=proposal_id, reviewer=reviewer, request=request, key=idem.scope.key
                )
            except NotFound:
                return error_verdict(404, ErrorCode.NOT_FOUND, "no such proposal", rid)
            except Conflict as exc:
                return error_verdict(409, ErrorCode(exc.code), stale, rid)
            return Verdict(
                200,
                {
                    "proposal_id": str(decided.proposal_id),
                    "run_id": str(decided.run_id),
                    "decision": decided.decision,
                    "status": decided.status,
                    "state_version": decided.state_version,
                },
            )

        return await self._idempotent(tenant_id, idem, work)


class Store(Protocol):
    """What the routes use: T12's idempotent mutations, the reads, and T11's seven session operations; the unit tests
    fake it on top of `AdmissionStore`, `DbStore` implements it."""

    faults: Faults | None

    async def membership(self, issuer: str, subject: UUID) -> Membership | None:
        """Resolve a verified subject to its active tenant membership, or None."""
        ...

    async def open_conversation(self, *, idem: Idem, tenant_id: UUID, created_by: UUID) -> Verdict:
        """Create an empty conversation in the tenant (idempotent)."""
        ...

    async def admit_message(
        self,
        *,
        idem: Idem,
        tenant_id: UUID,
        conversation_id: UUID,
        requester: UUID,
        request: MessageRequest,
        quota: int,
    ) -> Verdict:
        """Route and commit one message (idempotent)."""
        ...

    async def reply_clarification(
        self, *, idem: Idem, tenant_id: UUID, run_id: UUID, requester: UUID, reply: ClarificationReply
    ) -> Verdict:
        """Bind a reply to the run's outstanding question (idempotent)."""
        ...

    async def decide_once(
        self,
        *,
        idem: Idem,
        tenant_id: UUID,
        proposal_id: UUID,
        reviewer: UUID,
        roles: frozenset[str],
        request: DecisionRequest,
    ) -> Verdict:
        """Record the first decision (idempotent)."""
        ...

    # TODO(T12): the three pre-Plan-G mutations below serve the routes until Plan G Task 5 moves them to the
    # idempotent units above; Task 5 deletes them.
    async def create_conversation(self, tenant_id: UUID, created_by: UUID) -> UUID:
        """Create an empty conversation in the tenant."""
        ...

    async def admit(
        self,
        *,
        tenant_id: UUID,
        conversation_id: UUID,
        requester: UUID,
        request: MessageRequest,
        start_at: datetime,
        end_at: datetime,
    ) -> Accepted:
        """Commit message, run, job and `run.accepted` together."""
        ...

    async def decide(self, *, tenant_id: UUID, proposal_id: UUID, reviewer: UUID, request: DecisionRequest) -> Decided:
        """Record the first decision on the exact revision and hash, or raise Conflict."""
        ...

    async def run(self, tenant_id: UUID, run_id: UUID) -> dict[str, Any] | None:
        """Read one run row in the tenant."""
        ...

    async def proposal(self, tenant_id: UUID, proposal_id: UUID) -> dict[str, Any] | None:
        """Read one proposal with its run's requester and state."""
        ...

    async def events(self, tenant_id: UUID, run_id: UUID, *, after: int, limit: int) -> list[dict[str, Any]]:
        """List a run's events after a sequence number."""
        ...

    async def begin_login(
        self, *, login_sha256: str, state_sha256: str, nonce_sha256: str, code_verifier: str, ttl_seconds: int
    ) -> None:
        """Store one authorization request under the login cookie's hash."""
        ...

    async def take_login(self, login_sha256: str) -> LoginState | None:
        """Consume the request (one shot): its state, or None when absent or expired."""
        ...

    async def create_session(
        self,
        *,
        session_sha256: str,
        issuer: str,
        subject: UUID,
        tenant_id: UUID,
        sid: str,
        username: str,
        csrf_secret_sha256: str,
        refresh_token_enc: bytes,
        absolute_seconds: int,
    ) -> None:
        """Insert a session row with its absolute expiry."""
        ...

    async def live_session(self, session_sha256: str, *, idle_seconds: int) -> SessionRow | None:
        """The row if live (not revoked, inside both limits), touching `last_seen_at`; else None."""
        ...

    async def revoke_session(self, session_sha256: str) -> SessionRow | None:
        """Revoke one session; the row it was (for the sealed refresh token), or None if none was live."""
        ...

    async def expire_session(self, session_sha256: str, *, idle_seconds: int) -> SessionRow | None:
        """Revoke a session that is past either limit; the row it was (for the sealed refresh token), or None."""
        ...

    async def record_logout(self, jti: str, *, expires_at: datetime, sid: str) -> int | None:
        """Record a logout token's jti and revoke every session with its sid, atomically; None on a replay."""
        ...


class DbUnit:
    """`Unit` in SQL over the transaction a `persistence.Session` unit opened, as role `api` under one tenant."""

    def __init__(self, conn: persistence.Conn, tenant_id: UUID) -> None:
        self.conn = conn
        self.tenant_id = tenant_id

    async def lock_scope(self, lock_key: str) -> None:
        """Ruling 6: first statement of the unit, before every table lock; no grant needed (spike §6)."""
        await self.conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s::text, 0))", (lock_key,))

    async def find_record(self, scope: Scope) -> Record | None:
        """The live record of the scope; an expired row is ignored here and purged by the sweeper."""
        cur = await self.conn.execute(
            "SELECT fingerprint_sha256, status_code, response FROM app.idempotency_request"
            " WHERE tenant_id = %s AND subject = %s AND route = %s AND key = %s AND expires_at > app.current_time()",
            (scope.tenant_id, scope.subject, scope.route, scope.key),
        )
        row = await cur.fetchone()
        if row is None:
            return None
        return Record(str(row["fingerprint_sha256"]), int(row["status_code"]), dict(row["response"]))

    async def save_record(self, scope: Scope, fingerprint: str, verdict: Verdict, ttl_seconds: int) -> bool:
        """Insert the record last in the unit (SA:188); False when a row for the scope already exists."""
        # Target-less ON CONFLICT DO NOTHING: `api` holds INSERT and SELECT, and a 23505 here would print the scope
        # in its DETAIL (spike §1); rowcount 0 is the verdict.
        cur = await self.conn.execute(
            "INSERT INTO app.idempotency_request (tenant_id, subject, route, key, fingerprint_sha256, status_code,"
            " response, expires_at) VALUES (%s, %s, %s, %s, %s, %s, %s,"
            " app.current_time() + make_interval(secs => %s)) ON CONFLICT DO NOTHING",
            (
                scope.tenant_id,
                scope.subject,
                scope.route,
                scope.key,
                fingerprint,
                verdict.status,
                Jsonb(verdict.body),
                ttl_seconds,
            ),
        )
        return cur.rowcount == 1

    async def now(self) -> datetime:
        """`app.current_time()` inside the unit: the clock the interval and the record expiry share."""
        return await persistence.current_time(self.conn)

    async def conversation_exists(self, conversation_id: UUID) -> bool:
        """Whether the conversation is this tenant's (RLS scopes it; the WHERE is belt and braces)."""
        cur = await self.conn.execute(
            "SELECT 1 FROM app.conversations WHERE conversation_id = %s AND tenant_id = %s",
            (conversation_id, self.tenant_id),
        )
        return await cur.fetchone() is not None

    async def insert_conversation(self, created_by: UUID) -> UUID:
        """A plain INSERT under the tenant: `api` holds INSERT on conversations (SA:414)."""
        cid = uuid4()
        await self.conn.execute(
            "INSERT INTO app.conversations (conversation_id, tenant_id, created_by) VALUES (%s, %s, %s)",
            (cid, self.tenant_id, created_by),
        )
        return cid

    async def queued_count(self) -> int:
        """QUEUED runs of the tenant (ruling 18)."""
        return await persistence.queued_count(self.conn)

    async def active_run(self, conversation_id: UUID) -> bool:
        """Whether a run holds the slot; a read, not a lock (ruling 9: `api` cannot lock conversations)."""
        return await persistence.latest_active_run(self.conn, conversation_id) is not None

    async def latest_run(self, conversation_id: UUID) -> dict[str, Any] | None:
        """The newest run of the conversation, for a status answer."""
        row = await persistence.latest_run(self.conn, conversation_id)
        return None if row is None else dict(row)

    async def latest_event(self, run_id: UUID) -> dict[str, Any] | None:
        """The run's newest event, for a status answer."""
        row = await persistence.latest_event(self.conn, run_id)
        return None if row is None else dict(row)

    async def insert_message(
        self,
        *,
        conversation_id: UUID,
        kind: StoredMessageKind,
        text: str,
        context: dict[str, Any] | None,
        author: UUID | None,
    ) -> UUID:
        """One `messages` row under the tenant; `seq` comes from revision 0006's identity column."""
        message_id = uuid4()
        await self.conn.execute(
            "INSERT INTO app.messages (message_id, tenant_id, conversation_id, kind, text, context, author)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (
                message_id,
                self.tenant_id,
                conversation_id,
                kind.value,
                text,
                None if context is None else Jsonb(context),
                author,
            ),
        )
        return message_id

    async def start_run(
        self,
        *,
        conversation_id: UUID,
        requester: UUID,
        kind: StoredMessageKind,
        text: str,
        context: dict[str, Any],
        intent: Intent,
        asset_id: str,
        start_at: datetime,
        end_at: datetime,
        supersedes_run_id: UUID | None,
    ) -> Accepted:
        """Message plus `create_run` inside a savepoint, mapping the function's refusals."""
        try:
            # A savepoint: a refusal inside create_run aborts only these two statements, so the unit can still
            # write the 409 or 404 record (AM-16 reject: nothing written except the idempotency record).
            async with self.conn.transaction():
                message_id = await self.insert_message(
                    conversation_id=conversation_id, kind=kind, text=text, context=context, author=requester
                )
                # The function validates the supersedes target against tenant and conversation (SA:450, erratum).
                run_id, version = await persistence.create_run(
                    self.conn,
                    tenant_id=self.tenant_id,
                    conversation_id=conversation_id,
                    message_id=message_id,
                    requester=requester,
                    intent=intent,
                    asset_id=asset_id,
                    start_at=start_at,
                    end_at=end_at,
                    supersedes_run_id=supersedes_run_id,
                )
        except persistence.NotFound as exc:
            raise NotFound from exc
        except persistence.Refused as exc:
            raise map_refusal(exc) from exc
        return Accepted(conversation_id, message_id, run_id, RunState.QUEUED.value, version)

    async def run(self, run_id: UUID) -> dict[str, Any] | None:
        """The run's id, conversation, state and version, if it is this tenant's."""
        cur = await self.conn.execute(
            "SELECT run_id, conversation_id, state, state_version FROM app.runs WHERE run_id = %s AND tenant_id = %s",
            (run_id, self.tenant_id),
        )
        row = await cur.fetchone()
        return None if row is None else dict(row)

    async def latest_clarification(self, run_id: UUID) -> UUID | None:
        """The newest `clarification.requested` event of the run (the outstanding question)."""
        cur = await self.conn.execute(
            "SELECT event_id FROM app.events WHERE run_id = %s AND type = %s ORDER BY sequence DESC LIMIT 1",
            (run_id, EventType.CLARIFICATION_REQUESTED.value),
        )
        row = await cur.fetchone()
        return None if row is None else UUID(str(row["event_id"]))

    async def record_reply(
        self,
        *,
        run_id: UUID,
        conversation_id: UUID,
        question_id: UUID,
        text: str,
        context: dict[str, Any],
        author: UUID,
    ) -> UUID:
        """Message, `resume_input` job and `clarification.received` inside a savepoint (ruling 15)."""
        async with self.conn.transaction():  # a savepoint, as in start_run
            message_id = await self.insert_message(
                conversation_id=conversation_id,
                kind=StoredMessageKind.CLARIFICATION_REPLY,
                text=text,
                context=context,
                author=author,
            )
            key = dedup_key(JobType.RESUME_INPUT, run_id=run_id, clarification_event_id=question_id)
            queued = await persistence.insert_job_untargeted(
                self.conn, job_type=JobType.RESUME_INPUT, tenant_id=self.tenant_id, run_id=run_id, key=key
            )
            if not queued:
                raise Conflict("VERSION_CONFLICT")  # the savepoint rolls the message back
            await persistence.append_event(
                self.conn,
                run_id=run_id,
                type=EventType.CLARIFICATION_RECEIVED,
                payload={"question_id": str(question_id), "message_id": str(message_id)},
            )
        return message_id

    async def proposal(self, proposal_id: UUID) -> dict[str, Any] | None:
        """A proposal with its run's requester and state, as the reviewer check needs it."""
        cur = await self.conn.execute(
            "SELECT p.*, r.requester, r.state AS run_state FROM app.proposals p"
            " JOIN app.runs r ON r.run_id = p.run_id"
            " WHERE p.proposal_id = %s AND p.tenant_id = %s",
            (proposal_id, self.tenant_id),
        )
        row = await cur.fetchone()
        return None if row is None else dict(row)

    async def record_decision(
        self, *, proposal_id: UUID, reviewer: UUID, request: DecisionRequest, key: str
    ) -> Decided:
        """`record_decision` with the key stored on the decision row, inside a savepoint."""
        try:
            async with self.conn.transaction():  # a savepoint, so a lost race still leaves the unit able to record
                decided = await persistence.record_decision(
                    self.conn,
                    tenant_id=self.tenant_id,
                    proposal_id=proposal_id,
                    reviewer=reviewer,
                    expected_payload_sha256=request.expected_payload_sha256,
                    decision=request.decision,
                    reason=request.reason,
                    idempotency_key=key,
                )
        except persistence.NotFound as exc:
            raise NotFound from exc
        except persistence.VersionConflict as exc:
            raise Conflict("VERSION_CONFLICT") from exc
        except persistence.Refused as exc:
            raise map_refusal(exc) from exc
        return Decided(proposal_id, decided.run_id, request.decision, decided.state.value, decided.state_version)


class DbStore(AdmissionStore):
    """The PostgreSQL implementation of `Store` over one autocommit connection as role `api`."""

    def __init__(self, conn: persistence.Conn) -> None:
        self.session = persistence.Session(conn)  # ruling 24: one unit of work at a time, each a real transaction

    @asynccontextmanager
    async def unit(self, tenant_id: UUID) -> AsyncIterator[Unit]:
        """The tenant unit of `persistence.Session`, as a `DbUnit`."""
        async with self.session.unit(tenant_id) as conn:
            yield DbUnit(conn, tenant_id)

    async def membership(self, issuer: str, subject: UUID) -> Membership | None:
        """Resolve a verified subject to its active tenant membership, or None."""
        async with self.session.unit() as conn:  # the function walks the tenants itself (Plan E ruling 4)
            rows = await persistence.resolve_identity(conn, issuer=issuer, subject=subject)
        return single_tenant(rows)

    # TODO(T12): the three pre-Plan-G mutations below serve the routes until Plan G Task 5 moves them to the
    # idempotent units; Task 5 deletes them.
    async def create_conversation(self, tenant_id: UUID, created_by: UUID) -> UUID:
        """Create an empty conversation in the tenant."""
        cid = uuid4()
        async with self.session.unit(tenant_id) as conn:
            await conn.execute(
                "INSERT INTO app.conversations (conversation_id, tenant_id, created_by) VALUES (%s, %s, %s)",
                (cid, tenant_id, created_by),
            )
        return cid

    async def admit(
        self,
        *,
        tenant_id: UUID,
        conversation_id: UUID,
        requester: UUID,
        request: MessageRequest,
        start_at: datetime,
        end_at: datetime,
    ) -> Accepted:
        """Commit message, run, job and `run.accepted` together."""
        if request.context is None or request.context.asset_id is None:  # app.py checked the route
            raise ValueError("admit requires an investigate request with asset_id")
        message_id = uuid4()
        try:
            async with self.session.unit(tenant_id) as conn:
                cur = await conn.execute(
                    "SELECT 1 FROM app.conversations WHERE conversation_id = %s AND tenant_id = %s",
                    (conversation_id, tenant_id),
                )
                if await cur.fetchone() is None:
                    raise NotFound
                await conn.execute(
                    "INSERT INTO app.messages (message_id, tenant_id, conversation_id, kind, text, context, author)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (
                        message_id,
                        tenant_id,
                        conversation_id,
                        request.kind.value,
                        request.text,
                        Jsonb(request.context.model_dump(mode="json")),
                        requester,
                    ),
                )
                # The function validates the supersedes target against tenant and conversation (SA:450).
                run_id, version = await persistence.create_run(
                    conn,
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                    message_id=message_id,
                    requester=requester,
                    intent=Intent.INVESTIGATE,
                    asset_id=request.context.asset_id,
                    start_at=start_at,
                    end_at=end_at,
                    supersedes_run_id=request.supersedes_run_id,
                )
        except persistence.NotFound as exc:
            raise NotFound from exc
        except persistence.Refused as exc:
            raise map_refusal(exc) from exc
        return Accepted(conversation_id, message_id, run_id, RunState.QUEUED.value, version)

    async def decide(self, *, tenant_id: UUID, proposal_id: UUID, reviewer: UUID, request: DecisionRequest) -> Decided:
        """Record the first decision on the exact revision and hash, or raise Conflict / Forbidden / NotFound."""
        try:
            async with self.session.unit(tenant_id) as conn:
                cur = await conn.execute(
                    "SELECT revision FROM app.proposals WHERE proposal_id = %s AND tenant_id = %s",
                    (proposal_id, tenant_id),
                )
                proposal = await cur.fetchone()
                if proposal is None:
                    raise NotFound
                if proposal["revision"] != request.expected_revision:
                    raise Conflict("VERSION_CONFLICT")  # the hash is the function's check; the revision is ours
                decided = await persistence.record_decision(
                    conn,
                    tenant_id=tenant_id,
                    proposal_id=proposal_id,
                    reviewer=reviewer,
                    expected_payload_sha256=request.expected_payload_sha256,
                    decision=request.decision,
                    reason=request.reason,
                )
        except persistence.NotFound as exc:
            raise NotFound from exc
        except persistence.VersionConflict as exc:
            raise Conflict("VERSION_CONFLICT") from exc
        except persistence.Refused as exc:
            raise map_refusal(exc) from exc
        return Decided(proposal_id, decided.run_id, request.decision, decided.state.value, decided.state_version)

    async def run(self, tenant_id: UUID, run_id: UUID) -> dict[str, Any] | None:
        """Read one run row in the tenant (RLS scopes the unit; the WHERE is belt and braces)."""
        async with self.session.unit(tenant_id) as conn:
            cur = await conn.execute("SELECT * FROM app.runs WHERE run_id = %s AND tenant_id = %s", (run_id, tenant_id))
            row = await cur.fetchone()
        return None if row is None else dict(row)

    async def proposal(self, tenant_id: UUID, proposal_id: UUID) -> dict[str, Any] | None:
        """Read one proposal with its run's requester and state."""
        async with self.unit(tenant_id) as unit:
            return await unit.proposal(proposal_id)

    async def events(self, tenant_id: UUID, run_id: UUID, *, after: int, limit: int) -> list[dict[str, Any]]:
        """List a run's events after a sequence number."""
        async with self.session.unit(tenant_id) as conn:
            cur = await conn.execute(
                "SELECT sequence, type, source, occurred_at, payload FROM app.events"
                " WHERE run_id = %s AND tenant_id = %s AND sequence > %s ORDER BY sequence LIMIT %s",
                (run_id, tenant_id, after, limit),
            )
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def begin_login(
        self, *, login_sha256: str, state_sha256: str, nonce_sha256: str, code_verifier: str, ttl_seconds: int
    ) -> None:
        """Store one authorization request under the login cookie's hash."""
        async with self.session.unit() as conn:
            await conn.execute(
                "INSERT INTO app.login_state (login_sha256, state_sha256, nonce_sha256, code_verifier, expires_at)"
                " VALUES (%s, %s, %s, %s, app.current_time() + make_interval(secs => %s))",
                (login_sha256, state_sha256, nonce_sha256, code_verifier, ttl_seconds),
            )

    async def take_login(self, login_sha256: str) -> LoginState | None:
        """Consume the request (one shot): its state, or None when absent or expired."""
        async with self.session.unit() as conn:
            cur = await conn.execute(
                "DELETE FROM app.login_state WHERE login_sha256 = %s"
                " RETURNING state_sha256, nonce_sha256, code_verifier, expires_at > app.current_time() AS live",
                (login_sha256,),
            )
            row = await cur.fetchone()
        if row is None or not row["live"]:
            return None
        return LoginState(str(row["state_sha256"]), str(row["nonce_sha256"]), str(row["code_verifier"]))

    async def create_session(
        self,
        *,
        session_sha256: str,
        issuer: str,
        subject: UUID,
        tenant_id: UUID,
        sid: str,
        username: str,
        csrf_secret_sha256: str,
        refresh_token_enc: bytes,
        absolute_seconds: int,
    ) -> None:
        """Insert a session row with its absolute expiry (every timestamp from app.current_time(), R126)."""
        async with self.session.unit() as conn:
            await conn.execute(
                "INSERT INTO app.sessions (session_sha256, issuer, subject, tenant_id, sid, username,"
                " csrf_secret_sha256, refresh_token_enc, created_at, last_seen_at, expires_at)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, app.current_time(), app.current_time(),"
                " app.current_time() + make_interval(secs => %s))",
                (
                    session_sha256,
                    issuer,
                    subject,
                    tenant_id,
                    sid,
                    username,
                    csrf_secret_sha256,
                    refresh_token_enc,
                    absolute_seconds,
                ),
            )

    async def live_session(self, session_sha256: str, *, idle_seconds: int) -> SessionRow | None:
        """The row if live, touching `last_seen_at` in the same statement: one UPDATE … RETURNING decides liveness
        (BUILD_SPEC §9 idle and absolute limits), so Python compares no clocks."""
        async with self.session.unit() as conn:
            cur = await conn.execute(
                "UPDATE app.sessions SET last_seen_at = app.current_time()"
                " WHERE session_sha256 = %s AND revoked_at IS NULL AND expires_at > app.current_time()"
                " AND last_seen_at > app.current_time() - make_interval(secs => %s)"
                " RETURNING session_sha256, issuer, subject, tenant_id, sid, username, csrf_secret_sha256,"
                " refresh_token_enc",
                (session_sha256, idle_seconds),
            )
            row = await cur.fetchone()
        return None if row is None else _session_row(row)

    async def revoke_session(self, session_sha256: str) -> SessionRow | None:
        """Revoke one session; the row it was, or None if none was live."""
        async with self.session.unit() as conn:
            cur = await conn.execute(
                "UPDATE app.sessions SET revoked_at = app.current_time()"
                " WHERE session_sha256 = %s AND revoked_at IS NULL"
                " RETURNING session_sha256, issuer, subject, tenant_id, sid, username, csrf_secret_sha256,"
                " refresh_token_enc",
                (session_sha256,),
            )
            row = await cur.fetchone()
        return None if row is None else _session_row(row)

    async def expire_session(self, session_sha256: str, *, idle_seconds: int) -> SessionRow | None:
        """Revoke a session the limits have ended (final review I1): the same clock as `live_session`, the inverse
        of its limits, so the caller can end the provider session too. Only the first caller gets the row."""
        async with self.session.unit() as conn:
            cur = await conn.execute(
                "UPDATE app.sessions SET revoked_at = app.current_time()"
                " WHERE session_sha256 = %s AND revoked_at IS NULL AND (expires_at <= app.current_time()"
                " OR last_seen_at <= app.current_time() - make_interval(secs => %s))"
                " RETURNING session_sha256, issuer, subject, tenant_id, sid, username, csrf_secret_sha256,"
                " refresh_token_enc",
                (session_sha256, idle_seconds),
            )
            row = await cur.fetchone()
        return None if row is None else _session_row(row)

    async def record_logout(self, jti: str, *, expires_at: datetime, sid: str) -> int | None:
        """The jti insert and the revocation commit together (spike §5): a rolled-back revocation does not consume
        the token. A target-less ON CONFLICT DO NOTHING needs INSERT only; rowcount 0 is the replay."""
        async with self.session.unit() as conn:
            cur = await conn.execute(
                "INSERT INTO app.logout_jti (jti, expires_at) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (jti, expires_at),
            )
            if cur.rowcount != 1:
                return None
            cur = await conn.execute(
                "UPDATE app.sessions SET revoked_at = app.current_time() WHERE sid = %s AND revoked_at IS NULL", (sid,)
            )
            return int(cur.rowcount)


def _session_row(row: Any) -> SessionRow:
    return SessionRow(
        session_sha256=str(row["session_sha256"]),
        issuer=str(row["issuer"]),
        subject=UUID(str(row["subject"])),
        tenant_id=UUID(str(row["tenant_id"])),
        sid=str(row["sid"]),
        username=str(row["username"]),
        csrf_secret_sha256=str(row["csrf_secret_sha256"]),
        refresh_token_enc=bytes(row["refresh_token_enc"]),
    )
```

Run: `uv run python -m pytest tests/plan_g/test_store_units.py tests/plan_g/test_idempotency.py -q`
Expected: `20 passed`.

Run: `uv run python -m pytest tests/plan_d/test_api.py tests/plan_f -q`
Expected: `158 passed` (the routes still call the pre-T12 methods, kept above with their `TODO(T12)`).

- [ ] **Step 6: Gates and commit**

Format, lint and count characters on the six files; `uv run mypy core/src api/src --no-incremental` once (the
`Unit` protocol and `DbUnit` must agree member for member).

Run: `PYTHONUTF8=1 uv run python scripts/check.py`
Expected: `CHECK: GREEN`; pytest `749 passed, 98 skipped` (729 + 8 + 12).

Run: `PYTHONUTF8=1 uv run python scripts/check.py --profile test`
Expected: `CHECK: GREEN`; pytest `826 passed, 21 skipped` (749 + 77; the API's DbStore now inherits
`AdmissionStore`, and every live test still drives the pre-T12 methods). Then
`git checkout -- reports/bootstrap reports/skeleton`.

Run: `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts`
Expected: exit 0.

```bash
git add api/src/ops_api/idempotency.py api/src/ops_api/store.py core/src/ops_core/persistence.py
git add tests/plan_g/fakes.py tests/plan_g/test_idempotency.py tests/plan_g/test_store_units.py
git commit -m "feat(api): the scoped Idempotency-Key and the admission units over the store (T12)"
```

---

### Task 5: The routes — the key dependency, admission over the router, the clarifications route, the fault route

**Files:**
- Create: `tests/plan_g/test_api_admission.py`
- Modify: `api/src/ops_api/app.py` as Task 2 left it, `:8-10`, `:28-36`, `:41-42`, `:45-46`, `:67-68`, `:116-117`,
  `:120-124`, `:128-129`, `:226-227`, `:463-489`, `:492-509`, `:545-562`, `:564-576`, `:589-590`, `:642-643`
  (docstring, imports, route constants, `FaultRequest`, `create_app(…, profile=…)`, the lifespan's `faults`,
  `requester_mutation`, `idempotency_key`, `scoped`, `recorded`, the four mutation routes, the fault route,
  `production_app`); `api/src/ops_api/store.py` as Task 4 left it, `:653-677`, `:986-1083` (the pre-T12 mutations
  go); `tests/plan_d/test_api.py:5-10`, `:19-23`, `:25-26`, `:72-218`, `:228-230`, `:260-265`, `:287-292`,
  `:405-411`; `tests/plan_f/test_api_auth.py:36-38`, `:132-134`; `tests/e2e/test_r105_walking_skeleton.py:12-14`,
  `:83-84`, `:118-123`, `:146-156`; `tests/e2e/test_auth_live.py:11-13`, `:115-117`, `:231-233`, `:240-242`

**Interfaces:**
- Consumes: everything Task 4 produced; `ops_core.testing.faults.Faults`, `FaultKind`; `ops_core.settings.Profile`.
- Produces: `ops_api.app.ROUTE_CONVERSATIONS`, `ROUTE_MESSAGES`, `ROUTE_CLARIFICATIONS`, `ROUTE_DECISIONS` (the
  scope route strings), `FaultRequest(count: int 1..100)`, `create_app(verifier, store_factory, auth_factory, *,
  admission: AdmissionSettings | None = None, profile: Profile = Profile.DEV)`; the route
  `POST /api/v1/runs/{run_id}/clarifications`; under `profile=Profile.TEST` only, `POST /internal/faults/{kind}`
  (body `{"count": n}`, answers `{"armed": {...}}`). Every `/api/v1` mutation answers through
  `idempotency.response(verdict)` (no `status_code=` decorators any more).
- Produces: `tests.plan_d.test_api.FakeStore` becomes a subclass of `tests.plan_g.fakes.FakeStore` reading its own
  module's `ROWS`; `tests.plan_d.test_api.auth(name)` adds a fresh `Idempotency-Key`;
  `tests.plan_f.test_api_auth.browser(csrf, **extra)` adds one too.

- [ ] **Step 1: Write the failing route test**

Create `tests/plan_g/test_api_admission.py`:

```python
"""The T12 routes over HTTP with the shared fake store (R015-R018, R115, R129; Plan G rulings 1-5, 13-24): the six
admission routes, replay and conflict, the check order, every status code of R115, and what is and is not recorded.

Catches: a route answering without a key, the key checked before identity (a stranger learning which keys exist) or
after the body (a malformed body recorded), a replay that differs from the first answer, one key replaying across
conversations, a recorded 422 for a body that never parsed, a revoked member replaying a recorded success (BS:264
"authenticated current session"), a 429 without Retry-After, a fault before commit that keeps anything, the fault
route reachable outside the test profile, and a stale clarification reply accepted.
"""

import json
from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from ops_api.app import create_app
from ops_core.settings import AdmissionSettings, Profile

from tests.plan_f.auth_fakes import fake_auth
from tests.plan_g import fakes
from tests.plan_g.fakes import ALEX, FakeStore, StubVerifier

SAMPLE = {
    "kind": "investigate",
    "text": "Investigate the alerts on Asset A17 over the last 24 hours.",
    "context": {"asset_id": "A17", "hours": 24},
}


def h(name: str = "alex", key: str | None = None) -> dict[str, str]:
    """A persona's bearer header and an Idempotency-Key (a fresh one unless given)."""
    return {"Authorization": f"Bearer {name}", "Idempotency-Key": key or str(uuid4())}


def client(fake: FakeStore, **kwargs: Any) -> TestClient:
    return TestClient(create_app(StubVerifier(), store_factory=lambda: fake, auth_factory=fake_auth, **kwargs))


@pytest.fixture
def api() -> Iterator[tuple[TestClient, FakeStore]]:
    fake = FakeStore()
    with client(fake) as c:
        yield c, fake


def new_conversation(c: TestClient) -> str:
    r = c.post("/api/v1/conversations", headers=h())
    assert r.status_code == 201, r.text
    return str(r.json()["conversation_id"])


def messages(cid: str) -> str:
    return f"/api/v1/conversations/{cid}/messages"


def test_the_six_admission_routes_over_http(api) -> None:
    c, fake = api
    investigate = c.post(messages(cid := new_conversation(c)), headers=h(), json=SAMPLE)
    assert investigate.status_code == 202 and investigate.json()["status"] == "QUEUED"
    accepted_keys = {"conversation_id", "message_id", "run_id", "status", "state_version", "status_url", "events_url"}
    assert set(investigate.json()) == accepted_keys  # BS:299; stream_url waits for T27
    status = c.post(messages(cid), headers=h(), json={"kind": "status", "text": "How is it going?"})
    assert status.status_code == 200 and status.json()["run_id"] == investigate.json()["run_id"]
    clarify = c.post(
        messages(new_conversation(c)),
        headers=h(),
        json={"kind": "investigate", "text": "Compare A17 and B22, last day."},
    )
    assert clarify.status_code == 200 and clarify.json()["cause"] == "asset_ambiguous"
    readonly = c.post(
        messages(new_conversation(c)), headers=h(), json={"kind": "ask", "text": "What did A17 log in the past 2 days?"}
    )
    assert readonly.status_code == 202 and fake.runs[UUID(readonly.json()["run_id"])]["intent"] == "answer_only"
    reject = c.post(messages(new_conversation(c)), headers=h(), json={"kind": "clarification", "text": "A17"})
    assert (
        reject.status_code == 422
        and reject.json()["message"] == "clarification replies go to /api/v1/runs/{run_id}/clarifications"
    )
    run_id = UUID(investigate.json()["run_id"])
    question = fake.seed_question(run_id)
    body = {"question_id": str(question), "expected_version": 3, "context": {"asset_id": "A17"}}
    reply = c.post(f"/api/v1/runs/{run_id}/clarifications", headers=h(), json=body)
    assert reply.status_code == 202 and reply.json()["run_id"] == str(run_id)
    assert fake.jobs[-1]["type"] == "resume_input"


def test_a_replay_is_the_same_bytes_and_a_reused_key_is_a_conflict(api) -> None:
    c, fake = api
    cid, other = new_conversation(c), new_conversation(c)
    first = c.post(messages(cid), headers=h(key="key-replay-1"), json=SAMPLE)
    reformatted = json.dumps(SAMPLE, indent=2, sort_keys=True)  # whitespace and key order are not the request
    again = c.post(
        messages(cid), headers={**h(key="key-replay-1"), "Content-Type": "application/json"}, content=reformatted
    )
    assert first.status_code == again.status_code == 202 and again.content == first.content
    assert again.headers["X-Request-Id"] != first.headers["X-Request-Id"]  # the request is new; the answer is not
    assert len(fake.runs) == 1
    changed = c.post(
        messages(cid), headers=h(key="key-replay-1"), json={**SAMPLE, "context": {"asset_id": "A17", "hours": 12}}
    )
    elsewhere = c.post(messages(other), headers=h(key="key-replay-1"), json=SAMPLE)
    for refused in (changed, elsewhere):
        assert refused.status_code == 409 and refused.json()["code"] == "IDEMPOTENCY_CONFLICT"
    assert len(fake.runs) == 1 and len(fake.records) == 3  # two conversations and one message; no conflict recorded


def test_the_key_comes_after_identity_and_role_and_before_the_body(api) -> None:
    c, _ = api
    cid = new_conversation(c)
    assert c.post(messages(cid), json=SAMPLE).status_code == 401
    assert c.post(messages(cid), headers={"Authorization": "Bearer sam"}, json=SAMPLE).status_code == 403
    keyless = c.post(messages(cid), headers={"Authorization": "Bearer alex"}, content=b"not json")
    assert keyless.status_code == 422
    assert keyless.json()["message"] == "Idempotency-Key header is required (8–128 visible ASCII characters)"
    malformed = c.post(messages(cid), headers=h(key="key-order-01"), content=b"not json")
    assert malformed.status_code == 422 and malformed.json()["message"] == "request body is not valid"
    assert c.post(messages(cid), headers=h(key="key-order-01"), json=SAMPLE).status_code == 202  # nothing recorded


@pytest.mark.parametrize("key", ["has space1", "short", "a" * 129, ""])
def test_a_malformed_key_is_refused_before_anything_is_read(api, key: str) -> None:
    c, fake = api
    r = c.post(messages(new_conversation(c)), headers=h(key="placeholder") | {"Idempotency-Key": key}, json=SAMPLE)
    assert r.status_code == 422 and r.json()["code"] == "INVALID_INPUT" and not fake.runs


def test_a_full_tenant_queue_is_a_recorded_429_with_retry_after() -> None:
    fake = FakeStore()
    with client(fake, admission=AdmissionSettings(tenant_queue_quota=1)) as c:
        assert c.post(messages(new_conversation(c)), headers=h(), json=SAMPLE).status_code == 202
        cid = new_conversation(c)
        full = c.post(messages(cid), headers=h(key="key-quota-01"), json=SAMPLE)
        assert full.status_code == 429 and full.headers["Retry-After"] == "5" and full.json()["code"] == "RATE_LIMITED"
        fake.runs.clear()  # the queue drains; a replay is still the recorded answer
        again = c.post(messages(cid), headers=h(key="key-quota-01"), json=SAMPLE)
        assert again.status_code == 429 and again.content == full.content and again.headers["Retry-After"] == "5"


def test_a_fault_before_commit_is_a_final_503_and_the_same_key_then_succeeds() -> None:
    fake = FakeStore()
    with client(fake, profile=Profile.TEST) as c:
        cid = new_conversation(c)
        armed = c.post("/internal/faults/drop_before_commit", headers=h(), json={"count": 1})
        assert armed.status_code == 200 and armed.json() == {"armed": {"drop_before_commit": 1}}
        crashed = c.post(messages(cid), headers=h(key="key-fault-01"), json=SAMPLE)
        assert crashed.status_code == 503 and crashed.json()["retryable"] is False
        assert not fake.runs and not fake.messages and len(fake.records) == 1  # only the conversation's record
        retried = c.post(messages(cid), headers=h(key="key-fault-01"), json=SAMPLE)
        assert retried.status_code == 202 and len(fake.jobs) == 1  # R015: after commit the job exists
        wrong = c.post("/internal/faults/reject_next", headers=h(), json={"count": 1})
        assert wrong.status_code == 422


def test_the_fault_route_does_not_exist_outside_the_test_profile(api) -> None:
    c, _ = api
    r = c.post("/internal/faults/drop_before_commit", headers=h(), json={"count": 1})
    assert r.status_code == 404 and r.json()["code"] == "NOT_FOUND"


def test_a_lost_database_during_admission_is_a_retryable_503(api, monkeypatch) -> None:
    c, fake = api
    cid = new_conversation(c)

    async def gone(**_: Any) -> Any:
        raise psycopg.OperationalError("connection lost")

    monkeypatch.setattr(fake, "admit_message", gone)
    r = c.post(messages(cid), headers=h(), json=SAMPLE)
    assert r.status_code == 503 and r.json()["retryable"] is True and "connection lost" not in r.text


def test_router_verdicts_are_recorded_and_replayed(api) -> None:
    c, _ = api
    missing = f"/api/v1/conversations/{uuid4()}/messages"
    first = c.post(missing, headers=h(key="key-404-0001"), json=SAMPLE)
    again = c.post(missing, headers=h(key="key-404-0001"), json=SAMPLE)
    assert first.status_code == again.status_code == 404 and again.content == first.content  # the first request_id
    cid = new_conversation(c)
    assert c.post(messages(cid), headers=h(), json=SAMPLE).status_code == 202
    busy = c.post(messages(cid), headers=h(key="key-409-0001"), json=SAMPLE)
    assert busy.status_code == 409 and busy.json()["code"] == "SLOT_OCCUPIED"


def test_a_revoked_member_cannot_replay_a_recorded_success(api) -> None:
    c, _ = api
    cid = new_conversation(c)
    assert c.post(messages(cid), headers=h(key="key-revoke-1"), json=SAMPLE).status_code == 202
    saved = fakes.ROWS[ALEX]
    fakes.ROWS[ALEX] = []  # the sync deactivated alex
    try:
        replay = c.post(messages(cid), headers=h(key="key-revoke-1"), json=SAMPLE)
        assert replay.status_code == 401 and replay.json()["code"] == "UNAUTHENTICATED"  # identity before the record
    finally:
        fakes.ROWS[ALEX] = saved


def test_a_stale_clarification_reply_is_a_recorded_409(api) -> None:
    c, fake = api
    run_id = UUID(c.post(messages(new_conversation(c)), headers=h(), json=SAMPLE).json()["run_id"])
    question = fake.seed_question(run_id)
    url = f"/api/v1/runs/{run_id}/clarifications"
    stale = {"question_id": str(question), "expected_version": 2, "context": {"hours": 12}}
    first = c.post(url, headers=h(key="key-stale-01"), json=stale)
    assert first.status_code == 409 and first.json()["code"] == "VERSION_CONFLICT"
    assert c.post(url, headers=h(key="key-stale-01"), json=stale).content == first.content
    assert (
        c.post(url, headers={"Authorization": "Bearer sam", "Idempotency-Key": "key-stale-02"}, json=stale).status_code
        == 403
    )
    assert c.post(url, headers={"Authorization": "Bearer alex"}, json=stale).status_code == 422
    assert not any(j["type"] == "resume_input" for j in fake.jobs)


def test_a_decision_replays_and_the_first_decision_wins(api) -> None:
    c, fake = api
    pid = uuid4()
    fake.proposals[pid] = {
        "proposal_id": pid,
        "tenant_id": fakes.ALPHA,
        "run_id": uuid4(),
        "revision": 1,
        "payload_sha256": "9" * 64,
        "authored_by": [ALEX],
        "requester": ALEX,
    }
    url = f"/api/v1/proposals/{pid}/decisions"
    body = {"expected_revision": 1, "expected_payload_sha256": "9" * 64, "decision": "approve"}
    assert c.post(url, headers=h("alex"), json=body).status_code == 403  # the requester: refused, not recorded
    first = c.post(url, headers=h("sam", "key-decide-1"), json=body)
    assert first.status_code == 200 and fake.decision_keys[pid] == "key-decide-1"
    assert c.post(url, headers=h("sam", "key-decide-1"), json=body).content == first.content
    second = c.post(url, headers=h("sam"), json=body)
    assert second.status_code == 409 and second.json()["code"] == "VERSION_CONFLICT"


def test_a_conversation_replay_returns_the_same_id(api) -> None:
    c, fake = api
    first = c.post("/api/v1/conversations", headers=h(key="key-conv-001"))
    again = c.post("/api/v1/conversations", headers=h(key="key-conv-001"))
    assert first.status_code == again.status_code == 201 and again.json() == first.json()
    assert len(fake.conversations) == 1
```

Run: `uv run python -m pytest tests/plan_g/test_api_admission.py -q`
Expected: `15 failed, 1 passed` (only `test_the_fault_route_does_not_exist_outside_the_test_profile` passes: the
routes still call the pre-T12 methods and `create_app` takes no `profile`).

- [ ] **Step 2: The key dependency and the routes over the units**

In `api/src/ops_api/app.py` (line numbers as Task 2 left the file):

Edit 1 (old lines 8-10), replace:

```python
carries a server-made request id, every refusal is the SafeError, and no body over the configured limit reaches a
route.
"""
```

with:

```python
carries a server-made request id, every refusal is the SafeError, and no body over the configured limit reaches a
route; every /api/v1 mutation carries a scoped Idempotency-Key and runs as one recorded unit (`ops_api.store`), and
messages pass the AM-16 admission router (`ops_core.routing`).
"""
```

Edit 2 (old lines 28-36), replace:

```python
from ops_core import keycloak_admin, persistence, settings
from ops_core.contracts import DecisionRequest, DuplicateKey, ErrorCode, MessageKind, MessageRequest, load
from ops_core.keycloak_admin import AdminUnavailable
from ops_core.outcomes import EventRuleViolation
from ops_core.settings import AdmissionSettings, Role
from ops_core.states import IllegalTransition
from ops_core.tokens import Principal, SigningKeysUnavailable, TokenRejected, TokenVerifier
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
```

with:

```python
from ops_core import keycloak_admin, persistence, settings
from ops_core.contracts import ClarificationReply, DecisionRequest, DuplicateKey, ErrorCode, MessageRequest, load
from ops_core.keycloak_admin import AdminUnavailable
from ops_core.outcomes import EventRuleViolation
from ops_core.settings import AdmissionSettings, Profile, Role
from ops_core.states import IllegalTransition
from ops_core.testing.faults import FaultKind, Faults
from ops_core.tokens import Principal, SigningKeysUnavailable, TokenRejected, TokenVerifier
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
```

Edit 3 (old lines 41-42), replace:

```python
from ops_api.auth import AuthDeps, ExchangeRefused, ExchangeUnavailable

```

with:

```python
from ops_api.auth import AuthDeps, ExchangeRefused, ExchangeUnavailable
from ops_api.idempotency import (
    HEADER,
    KEY_REFUSAL,
    Idem,
    IdempotencyConflict,
    KeyInvalid,
    Scope,
    Verdict,
    fingerprint,
    response,
    validate_key,
)

```

Edit 4 (old lines 45-46), replace:

```python
bearer = HTTPBearer(auto_error=False)  # the 401 body is ours (SafeError), not the SDK's

```

with:

```python
bearer = HTTPBearer(auto_error=False)  # the 401 body is ours (SafeError), not the SDK's
# Idempotency scopes name the method and the path template (Plan G ruling 2): the path's ids are in the fingerprint.
ROUTE_CONVERSATIONS = "POST /api/v1/conversations"
ROUTE_MESSAGES = "POST /api/v1/conversations/{conversation_id}/messages"
ROUTE_CLARIFICATIONS = "POST /api/v1/runs/{run_id}/clarifications"
ROUTE_DECISIONS = "POST /api/v1/proposals/{proposal_id}/decisions"

```

Edit 5 (old lines 67-68), replace:

```python
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")

```

with:

```python
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class FaultRequest(BaseModel):
    """How many occurrences of a fault to arm (the test profile's fault route, ruling 24)."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    count: int = Field(ge=1, le=100)

```

Edit 6 (old lines 116-117), replace:

```python
    admission: AdmissionSettings | None = None,
) -> FastAPI:
```

with:

```python
    admission: AdmissionSettings | None = None,
    profile: Profile = Profile.DEV,
) -> FastAPI:
```

Edit 7 (old lines 120-124), replace:

```python
    `admission` carries the body limit and the other T12 bounds; tests pass their own, production passes
    `settings.admission()`, and the default is the spec's starting values (BUILD_SPEC §17).
    """
    bounds = admission or AdmissionSettings()

```

with:

```python
    `admission` carries the body limit and the other T12 bounds; tests pass their own, production passes
    `settings.admission()`, and the default is the spec's starting values (BUILD_SPEC §17). Under the test profile
    the app also arms faults (R098: the hooks do not exist in dev or demo, so the route is the safe 404 there).
    """
    bounds = admission or AdmissionSettings()
    faults = Faults(profile) if profile is Profile.TEST else None

```

Edit 8 (old lines 128-129), replace:

```python
        app.state.store = await made if isinstance(made, Awaitable) else made
        try:
```

with:

```python
        app.state.store = await made if isinstance(made, Awaitable) else made
        app.state.store.faults = faults
        try:
```

Edit 9 (old lines 226-227), replace:

```python
        log.error("request %s failed: %s", limits.request_id_of(request.scope), exc.__class__.__name__)

```

with:

```python
        log.error("request %s failed: %s", limits.request_id_of(request.scope), exc.__class__.__name__)

    async def requester_mutation(who: Annotated[Identity, Depends(browser_mutation)]) -> Identity:
        """A browser-safe mutation by a requester: the role check precedes the key and the body (ruling 21)."""
        who.require("requester")
        return who

    async def idempotency_key(request: Request) -> str:
        """BS:264: every /api/v1 mutation carries a key, checked after identity and role and before the body."""
        try:
            return validate_key(request.headers.get(HEADER), bounds)
        except KeyInvalid as exc:
            raise ApiError(422, ErrorCode.INVALID_INPUT, KEY_REFUSAL) from exc

    def scoped(
        request: Request, who: Identity, route: str, key: str, path: dict[str, str], parsed: BaseModel | None
    ) -> Idem:
        """The unit's scope and fingerprint: the person (bearer or cookie, ruling 2), the route, the key, and what
        the request says once validated (ruling 3)."""
        return Idem(
            Scope(who.tenant_id, who.subject, route, key),
            fingerprint(path, None if parsed is None else parsed.model_dump(mode="json")),
            bounds.idempotency_ttl_seconds,
            limits.request_id_of(request.scope),
        )

    async def recorded(unit: Awaitable[Verdict]) -> Response:
        """The verdict as the response; a key reused for another request is a 409 nobody records (ruling 5)."""
        try:
            return response(await unit)
        except IdempotencyConflict as exc:
            raise ApiError(409, ErrorCode.IDEMPOTENCY_CONFLICT, exc.message) from exc

```

Edit 10 (old lines 463-489), replace:

```python

    @app.post("/api/v1/conversations", status_code=201)
    async def create_conversation(
        request: Request, who: Annotated[Identity, Depends(browser_mutation)]
    ) -> dict[str, str]:
        cid = await request.app.state.store.create_conversation(who.tenant_id, who.subject)
        return {"conversation_id": str(cid)}

    @app.post("/api/v1/conversations/{conversation_id}/messages", status_code=202)
    async def post_message(
        conversation_id: UUID, request: Request, who: Annotated[Identity, Depends(browser_mutation)]
    ) -> dict[str, Any]:
        who.require("requester")
        message: MessageRequest = await body(request, MessageRequest)
        # T08 routes only `investigate` with a resolvable asset and interval; the admission router (T12) adds the rest.
        if (
            message.kind is not MessageKind.INVESTIGATE
            or message.context is None
            or (message.context.asset_id is None or message.context.hours is None)
        ):
            raise ApiError(
                422, ErrorCode.INVALID_INPUT, "only an investigate request with asset_id and hours is routed"
            )
        start_at, end_at = st.resolve_interval(message.context.hours, datetime.now(UTC))
        try:
            accepted = await request.app.state.store.admit(
                tenant_id=who.tenant_id,
```

with:

```python

    @app.post("/api/v1/conversations")
    async def create_conversation(
        request: Request,
        who: Annotated[Identity, Depends(browser_mutation)],
        key: Annotated[str, Depends(idempotency_key)],
    ) -> Response:
        """BS:270: 201 `{conversation_id}`; no body, so the fingerprint is an empty path and a null body (ruling 22)."""
        store: st.Store = request.app.state.store
        idem = scoped(request, who, ROUTE_CONVERSATIONS, key, {}, None)
        return await recorded(store.open_conversation(idem=idem, tenant_id=who.tenant_id, created_by=who.subject))

    @app.post("/api/v1/conversations/{conversation_id}/messages")
    async def post_message(
        conversation_id: UUID,
        request: Request,
        who: Annotated[Identity, Depends(requester_mutation)],
        key: Annotated[str, Depends(idempotency_key)],
    ) -> Response:
        """BS:271 through the AM-16 router: 202 for a run, 200 for a clarification or a status answer, 409 for a busy
        conversation, 422 for an unroutable kind, 429 for a full tenant queue (ruling 21's order)."""
        message: MessageRequest = await body(request, MessageRequest)
        store: st.Store = request.app.state.store
        idem = scoped(request, who, ROUTE_MESSAGES, key, {"conversation_id": str(conversation_id)}, message)
        return await recorded(
            store.admit_message(
                idem=idem,
                tenant_id=who.tenant_id,
```

Edit 11 (old lines 492-509), replace:

```python
                request=message,
                start_at=start_at,
                end_at=end_at,
            )
        except st.NotFound as exc:
            raise ApiError(404, ErrorCode.NOT_FOUND, "no such conversation or superseded run") from exc
        except st.Conflict as exc:
            raise ApiError(409, ErrorCode(exc.code), "the conversation already has an active run") from exc
        return {
            "conversation_id": str(accepted.conversation_id),
            "message_id": str(accepted.message_id),
            "run_id": str(accepted.run_id),
            "status": accepted.status,
            "state_version": accepted.state_version,
            "status_url": f"/api/v1/runs/{accepted.run_id}",
            "events_url": f"/api/v1/runs/{accepted.run_id}/events",
        }

```

with:

```python
                request=message,
                quota=bounds.tenant_queue_quota,
            )
        )

    @app.post("/api/v1/runs/{run_id}/clarifications")
    async def post_clarification(
        run_id: UUID,
        request: Request,
        who: Annotated[Identity, Depends(requester_mutation)],
        key: Annotated[str, Depends(idempotency_key)],
    ) -> Response:
        """BS:273, the clarification_reply route: bound to the run's outstanding question and expected version."""
        reply: ClarificationReply = await body(request, ClarificationReply)
        store: st.Store = request.app.state.store
        idem = scoped(request, who, ROUTE_CLARIFICATIONS, key, {"run_id": str(run_id)}, reply)
        return await recorded(
            store.reply_clarification(
                idem=idem, tenant_id=who.tenant_id, run_id=run_id, requester=who.subject, reply=reply
            )
        )

```

Edit 12 (old lines 545-562), replace:

```python
    async def post_decision(
        proposal_id: UUID, request: Request, who: Annotated[Identity, Depends(enabled_identity)]
    ) -> dict[str, Any]:
        decision: DecisionRequest = await body(request, DecisionRequest)
        store: st.Store = request.app.state.store
        row = await store.proposal(who.tenant_id, proposal_id)
        if row is None:
            raise ApiError(404, ErrorCode.NOT_FOUND, "no such proposal")
        try:
            st.check_reviewer(
                st.Membership(who.tenant_id, who.roles),
                requester=row["requester"],
                authored_by=list(row["authored_by"]),
                reviewer=who.subject,
            )
            decided = await store.decide(
                tenant_id=who.tenant_id, proposal_id=proposal_id, reviewer=who.subject, request=decision
            )
```

with:

```python
    async def post_decision(
        proposal_id: UUID,
        request: Request,
        who: Annotated[Identity, Depends(enabled_identity)],
        key: Annotated[str, Depends(idempotency_key)],
    ) -> Response:
        """BS:466: the first decision wins and a replay of the same key returns its recorded result."""
        decision: DecisionRequest = await body(request, DecisionRequest)
        store: st.Store = request.app.state.store
        idem = scoped(request, who, ROUTE_DECISIONS, key, {"proposal_id": str(proposal_id)}, decision)
        try:
            return await recorded(
                store.decide_once(
                    idem=idem,
                    tenant_id=who.tenant_id,
                    proposal_id=proposal_id,
                    reviewer=who.subject,
                    roles=who.roles,
                    request=decision,
                )
            )
```

Edit 13 (old lines 564-576), replace:

```python
            raise ApiError(403, ErrorCode.FORBIDDEN, "an independent current reviewer is required") from exc
        except st.NotFound as exc:
            raise ApiError(404, ErrorCode.NOT_FOUND, "no such proposal") from exc
        except st.Conflict as exc:
            raise ApiError(409, ErrorCode(exc.code), "the proposal is not the active, undecided revision") from exc
        return {
            "proposal_id": str(decided.proposal_id),
            "run_id": str(decided.run_id),
            "decision": decided.decision,
            "status": decided.status,
            "state_version": decided.state_version,
        }

```

with:

```python
            raise ApiError(403, ErrorCode.FORBIDDEN, "an independent current reviewer is required") from exc

```

Edit 14 (old lines 589-590), replace:

```python
        return {"events": [{**r, "occurred_at": stamp(r["occurred_at"])} if "occurred_at" in r else r for r in rows]}

```

with:

```python
        return {"events": [{**r, "occurred_at": stamp(r["occurred_at"])} if "occurred_at" in r else r for r in rows]}

    if faults is not None:
        armable = faults  # a local the closure can rely on: `faults` is narrowed to non-None only here

        @app.post("/internal/faults/{kind}")
        async def arm_fault(
            kind: FaultKind, request: Request, _: Annotated[Identity, Depends(identity)]
        ) -> dict[str, dict[str, int]]:
            """Arm a fault for the next `count` admissions (R015's crash before commit, ruling 24); the route exists
            only under PROFILE=test, like incident-sim's."""
            if kind is not FaultKind.DROP_BEFORE_COMMIT:
                raise ApiError(422, ErrorCode.INVALID_INPUT, "the API implements drop_before_commit only")
            armed: FaultRequest = await body(request, FaultRequest)
            armable.arm(kind, armed.count)
            return {"armed": armable.armed()}

```

Edit 15 (old lines 642-643), replace:

```python

    return create_app(verifier, make_store, make_auth, admission=settings.admission())
```

with:

```python

    return create_app(verifier, make_store, make_auth, admission=settings.admission(), profile=settings.profile())
```

Run: `uv run python -m pytest tests/plan_g/test_api_admission.py -q`
Expected: `16 passed`.

Run: `uv run python -m pytest tests/plan_d/test_api.py tests/plan_f -q`
Expected: `8 failed, 150 passed` (the Plan D and Plan F tests still post without a key, and Plan D's own fake has no
units yet; Step 3 fixes both).

- [ ] **Step 3: The Plan D and Plan F unit tests use the shared fake and send keys**

In `tests/plan_d/test_api.py`:

Edit 1 (old lines 5-10), replace:

```python
tenant seeing or deciding a proposal (404, not 403: existence is not disclosed), a decision on a stale hash accepted,
a second decision overwriting the first, and a run in another tenant readable by id.
"""

import time
from collections.abc import Iterator
```

with:

```python
tenant seeing or deciding a proposal (404, not 403: existence is not disclosed), a decision on a stale hash accepted,
a second decision overwriting the first, and a run in another tenant readable by id. Since Plan G every mutation
here carries a fresh Idempotency-Key (`auth()` adds one) and the store is the shared fake of tests/plan_g/fakes.py.
"""

from collections.abc import Iterator
```

Edit 2 (old lines 19-23), replace:

```python
from ops_api.app import create_app
from ops_api.store import LoginState, SessionRow
from ops_core import persistence
from ops_core.contracts import DecisionRequest, MessageRequest
from ops_core.tokens import Principal, TokenRejected
```

with:

```python
from ops_api.app import create_app
from ops_core import persistence
from ops_core.tokens import Principal, TokenRejected
```

Edit 3 (old lines 25-26), replace:

```python
from tests.plan_f.auth_fakes import fake_auth

```

with:

```python
from tests.plan_f.auth_fakes import fake_auth
from tests.plan_g import fakes

```

Edit 4 (old lines 72-84), replace:

```python

class FakeStore:
    def __init__(self) -> None:
        self.conversations: dict[UUID, UUID] = {}  # conversation -> tenant
        self.runs: dict[UUID, dict[str, Any]] = {}
        self.proposals: dict[UUID, dict[str, Any]] = {}
        self.decided: set[UUID] = set()
        self.slot_occupied = False
        self.logins: dict[str, tuple[LoginState, float]] = {}  # login hash -> (state, expiry)
        self.sessions: dict[str, dict[str, Any]] = {}  # session hash -> row fields + last_seen, expires, revoked
        self.jtis: set[str] = set()
        self.clock = time.time  # tests replace it to age sessions

```

with:

```python

class FakeStore(fakes.FakeStore):
    """Plan D's name for the shared fake (Plan G Task 5): the real admission orchestration over in-memory tables, with
    membership read from this module's ROWS, which tests/plan_f/test_api_auth.py edits to stand in for the sync."""

```

Edit 5 (old lines 86-218), replace:

```python
        return store.single_tenant(ROWS.get(subject, [])) if issuer == ISSUER else None

    async def create_conversation(self, tenant_id: UUID, created_by: UUID) -> UUID:
        cid = uuid4()
        self.conversations[cid] = tenant_id
        return cid

    async def admit(
        self,
        *,
        tenant_id: UUID,
        conversation_id: UUID,
        requester: UUID,
        request: MessageRequest,
        start_at: datetime,
        end_at: datetime,
    ) -> store.Accepted:
        if self.conversations.get(conversation_id) != tenant_id:
            raise store.NotFound
        sup = request.supersedes_run_id
        if sup is not None and (sup not in self.runs or self.runs[sup]["conversation_id"] != conversation_id):
            raise store.NotFound
        if self.slot_occupied:
            raise store.Conflict("SLOT_OCCUPIED")
        run_id = uuid4()
        self.runs[run_id] = {
            "run_id": run_id,
            "tenant_id": tenant_id,
            "conversation_id": conversation_id,
            "requester": requester,
            "state": "QUEUED",
            "state_version": 1,
            "active_proposal_id": None,
            "asset_id": request.context.asset_id if request.context else None,
            "start_at": start_at,
            "end_at": end_at,
            "created_at": start_at,
        }
        return store.Accepted(conversation_id, uuid4(), run_id, "QUEUED", 1)

    async def run(self, tenant_id: UUID, run_id: UUID) -> dict[str, Any] | None:
        row = self.runs.get(run_id)
        return row if row and row["tenant_id"] == tenant_id else None

    async def proposal(self, tenant_id: UUID, proposal_id: UUID) -> dict[str, Any] | None:
        row = self.proposals.get(proposal_id)
        return row if row and row["tenant_id"] == tenant_id else None

    async def decide(
        self, *, tenant_id: UUID, proposal_id: UUID, reviewer: UUID, request: DecisionRequest
    ) -> store.Decided:
        row = await self.proposal(tenant_id, proposal_id)
        if row is None:
            raise store.NotFound
        if (row["revision"], row["payload_sha256"]) != (request.expected_revision, request.expected_payload_sha256):
            raise store.Conflict("VERSION_CONFLICT")
        if proposal_id in self.decided:
            raise store.Conflict("VERSION_CONFLICT")
        self.decided.add(proposal_id)
        status = "APPROVED" if request.decision == "approve" else "REJECTED"
        return store.Decided(proposal_id, row["run_id"], request.decision, status, 5)

    async def events(self, tenant_id: UUID, run_id: UUID, *, after: int, limit: int) -> list[dict[str, Any]]:
        return [] if await self.run(tenant_id, run_id) is None else [{"sequence": 1, "type": "run.accepted"}]

    async def begin_login(
        self, *, login_sha256: str, state_sha256: str, nonce_sha256: str, code_verifier: str, ttl_seconds: int
    ) -> None:
        self.logins[login_sha256] = (LoginState(state_sha256, nonce_sha256, code_verifier), self.clock() + ttl_seconds)

    async def take_login(self, login_sha256: str) -> LoginState | None:
        entry = self.logins.pop(login_sha256, None)
        return None if entry is None or entry[1] <= self.clock() else entry[0]

    async def create_session(
        self,
        *,
        session_sha256: str,
        issuer: str,
        subject: UUID,
        tenant_id: UUID,
        sid: str,
        username: str,
        csrf_secret_sha256: str,
        refresh_token_enc: bytes,
        absolute_seconds: int,
    ) -> None:
        self.sessions[session_sha256] = {
            "row": SessionRow(
                session_sha256, issuer, subject, tenant_id, sid, username, csrf_secret_sha256, refresh_token_enc
            ),
            "last_seen": self.clock(),
            "expires": self.clock() + absolute_seconds,
            "revoked": False,
        }

    async def live_session(self, session_sha256: str, *, idle_seconds: int) -> SessionRow | None:
        entry = self.sessions.get(session_sha256)
        now = self.clock()
        if entry is None or entry["revoked"] or entry["expires"] <= now or entry["last_seen"] <= now - idle_seconds:
            return None
        entry["last_seen"] = now
        row: SessionRow = entry["row"]
        return row

    async def revoke_session(self, session_sha256: str) -> SessionRow | None:
        entry = self.sessions.get(session_sha256)
        if entry is None or entry["revoked"]:
            return None
        entry["revoked"] = True
        row: SessionRow = entry["row"]
        return row

    async def expire_session(self, session_sha256: str, *, idle_seconds: int) -> SessionRow | None:
        entry = self.sessions.get(session_sha256)
        now = self.clock()
        if entry is None or entry["revoked"]:
            return None
        if entry["expires"] > now and entry["last_seen"] > now - idle_seconds:
            return None  # still live: not this method's to revoke
        entry["revoked"] = True
        row: SessionRow = entry["row"]
        return row

    async def record_logout(self, jti: str, *, expires_at: datetime, sid: str) -> int | None:
        if jti in self.jtis:
            return None
        self.jtis.add(jti)
        hit = [e for e in self.sessions.values() if e["row"].sid == sid and not e["revoked"]]
        for entry in hit:
            entry["revoked"] = True
        return len(hit)

```

with:

```python
        return store.single_tenant(ROWS.get(subject, [])) if issuer == ISSUER else None

```

Edit 6 (old lines 228-230), replace:

```python
def auth(name: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {name}"}

```

with:

```python
def auth(name: str) -> dict[str, str]:
    """A persona's bearer header plus a fresh Idempotency-Key, so every mutation is a new request (BS:264)."""
    return {"Authorization": f"Bearer {name}", "Idempotency-Key": str(uuid4())}

```

Edit 7 (old lines 260-262), replace:

```python
def test_supersedes_run_must_be_in_the_same_conversation(api):
    c, _ = api
    cid = c.post("/api/v1/conversations", headers=auth("alex")).json()["conversation_id"]
```

with:

```python
def test_supersedes_run_must_be_in_the_same_conversation(api):
    c, fake = api
    cid = c.post("/api/v1/conversations", headers=auth("alex")).json()["conversation_id"]
```

Edit 8 (old lines 264-265), replace:

```python
    first = c.post(f"/api/v1/conversations/{cid}/messages", headers=auth("alex"), json=body).json()["run_id"]
    url = f"/api/v1/conversations/{cid}/messages"
```

with:

```python
    first = c.post(f"/api/v1/conversations/{cid}/messages", headers=auth("alex"), json=body).json()["run_id"]
    fake.runs[UUID(first)]["state"] = "FAILED"  # a run that ended frees the slot (since Plan G the router checks it)
    url = f"/api/v1/conversations/{cid}/messages"
```

Edit 9 (old lines 287-292), replace:

```python
        {**body, "tenant_id": str(BETA)},  # authority field (BUILD_SPEC §7)
        {**body, "kind": "ask"},  # not routed in T08 (admission router is T12)
        {"kind": "investigate", "text": "x"},  # no asset/interval
        {**body, "context": {"asset_id": "a17", "hours": 24}},  # AssetId pattern
    ):
        assert c.post(f"/api/v1/conversations/{cid}/messages", headers=auth("alex"), json=bad).status_code == 422, bad
```

with:

```python
        {**body, "tenant_id": str(BETA)},  # authority field (BUILD_SPEC §7)
        {**body, "context": {"asset_id": "a17", "hours": 24}},  # AssetId pattern
    ):  # `ask` and a request without asset or window are routed since Plan G (tests/plan_g/test_api_admission.py)
        assert c.post(f"/api/v1/conversations/{cid}/messages", headers=auth("alex"), json=bad).status_code == 422, bad
```

Edit 10 (old lines 405-407), replace:

```python

    async def broken_admit(**_: Any) -> store.Accepted:
        """Stand in for a function that rejected bytes the API had just built."""
```

with:

```python

    async def broken_admit(**_: Any) -> Any:
        """Stand in for a function that rejected bytes the API had just built."""
```

Edit 11 (old lines 409-411), replace:

```python

    monkeypatch.setattr(fake, "admit", broken_admit)
    cid = c.post("/api/v1/conversations", headers=auth("alex")).json()["conversation_id"]
```

with:

```python

    monkeypatch.setattr(fake, "admit_message", broken_admit)
    cid = c.post("/api/v1/conversations", headers=auth("alex")).json()["conversation_id"]
```

In `tests/plan_f/test_api_auth.py`:

Edit 1 (old lines 36-38), replace:

```python
def browser(csrf: str, **extra: str) -> dict[str, str]:
    return {"Origin": ORIGIN, "X-CSRF-Token": csrf, **extra}

```

with:

```python
def browser(csrf: str, **extra: str) -> dict[str, str]:
    """A cookie-mode mutation's headers: Origin, the CSRF token and (since Plan G) a fresh Idempotency-Key."""
    return {"Origin": ORIGIN, "X-CSRF-Token": csrf, "Idempotency-Key": str(uuid4()), **extra}

```

Edit 2 (old lines 132-134), replace:

```python
    assert ok.status_code == 201
    referer_only = c.post("/api/v1/conversations", headers={"Referer": ORIGIN + "/app", "X-CSRF-Token": csrf})
    assert referer_only.status_code == 201
```

with:

```python
    assert ok.status_code == 201
    referer_only = c.post(
        "/api/v1/conversations",
        headers={"Referer": ORIGIN + "/app", "X-CSRF-Token": csrf, "Idempotency-Key": str(uuid4())},
    )
    assert referer_only.status_code == 201
```

Run: `uv run python -m pytest tests/plan_g tests/plan_d/test_api.py tests/plan_f -q`
Expected: `242 passed` (84 Plan G tests and the 158 Plan D/F tests).

- [ ] **Step 4: The pre-T12 store mutations go**

In `api/src/ops_api/store.py` (as Task 4 left it), delete the two `TODO(T12)` blocks:

Edit 1 (old lines 653-677), replace:

```python

    # TODO(T12): the three pre-Plan-G mutations below serve the routes until Plan G Task 5 moves them to the
    # idempotent units above; Task 5 deletes them.
    async def create_conversation(self, tenant_id: UUID, created_by: UUID) -> UUID:
        """Create an empty conversation in the tenant."""
        ...

    async def admit(
        self,
        *,
        tenant_id: UUID,
        conversation_id: UUID,
        requester: UUID,
        request: MessageRequest,
        start_at: datetime,
        end_at: datetime,
    ) -> Accepted:
        """Commit message, run, job and `run.accepted` together."""
        ...

    async def decide(self, *, tenant_id: UUID, proposal_id: UUID, reviewer: UUID, request: DecisionRequest) -> Decided:
        """Record the first decision on the exact revision and hash, or raise Conflict."""
        ...

    async def run(self, tenant_id: UUID, run_id: UUID) -> dict[str, Any] | None:
```

with:

```python

    async def run(self, tenant_id: UUID, run_id: UUID) -> dict[str, Any] | None:
```

Edit 2 (old lines 986-1083), replace:

```python

    # TODO(T12): the three pre-Plan-G mutations below serve the routes until Plan G Task 5 moves them to the
    # idempotent units; Task 5 deletes them.
    async def create_conversation(self, tenant_id: UUID, created_by: UUID) -> UUID:
        """Create an empty conversation in the tenant."""
        cid = uuid4()
        async with self.session.unit(tenant_id) as conn:
            await conn.execute(
                "INSERT INTO app.conversations (conversation_id, tenant_id, created_by) VALUES (%s, %s, %s)",
                (cid, tenant_id, created_by),
            )
        return cid

    async def admit(
        self,
        *,
        tenant_id: UUID,
        conversation_id: UUID,
        requester: UUID,
        request: MessageRequest,
        start_at: datetime,
        end_at: datetime,
    ) -> Accepted:
        """Commit message, run, job and `run.accepted` together."""
        if request.context is None or request.context.asset_id is None:  # app.py checked the route
            raise ValueError("admit requires an investigate request with asset_id")
        message_id = uuid4()
        try:
            async with self.session.unit(tenant_id) as conn:
                cur = await conn.execute(
                    "SELECT 1 FROM app.conversations WHERE conversation_id = %s AND tenant_id = %s",
                    (conversation_id, tenant_id),
                )
                if await cur.fetchone() is None:
                    raise NotFound
                await conn.execute(
                    "INSERT INTO app.messages (message_id, tenant_id, conversation_id, kind, text, context, author)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (
                        message_id,
                        tenant_id,
                        conversation_id,
                        request.kind.value,
                        request.text,
                        Jsonb(request.context.model_dump(mode="json")),
                        requester,
                    ),
                )
                # The function validates the supersedes target against tenant and conversation (SA:450).
                run_id, version = await persistence.create_run(
                    conn,
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                    message_id=message_id,
                    requester=requester,
                    intent=Intent.INVESTIGATE,
                    asset_id=request.context.asset_id,
                    start_at=start_at,
                    end_at=end_at,
                    supersedes_run_id=request.supersedes_run_id,
                )
        except persistence.NotFound as exc:
            raise NotFound from exc
        except persistence.Refused as exc:
            raise map_refusal(exc) from exc
        return Accepted(conversation_id, message_id, run_id, RunState.QUEUED.value, version)

    async def decide(self, *, tenant_id: UUID, proposal_id: UUID, reviewer: UUID, request: DecisionRequest) -> Decided:
        """Record the first decision on the exact revision and hash, or raise Conflict / Forbidden / NotFound."""
        try:
            async with self.session.unit(tenant_id) as conn:
                cur = await conn.execute(
                    "SELECT revision FROM app.proposals WHERE proposal_id = %s AND tenant_id = %s",
                    (proposal_id, tenant_id),
                )
                proposal = await cur.fetchone()
                if proposal is None:
                    raise NotFound
                if proposal["revision"] != request.expected_revision:
                    raise Conflict("VERSION_CONFLICT")  # the hash is the function's check; the revision is ours
                decided = await persistence.record_decision(
                    conn,
                    tenant_id=tenant_id,
                    proposal_id=proposal_id,
                    reviewer=reviewer,
                    expected_payload_sha256=request.expected_payload_sha256,
                    decision=request.decision,
                    reason=request.reason,
                )
        except persistence.NotFound as exc:
            raise NotFound from exc
        except persistence.VersionConflict as exc:
            raise Conflict("VERSION_CONFLICT") from exc
        except persistence.Refused as exc:
            raise map_refusal(exc) from exc
        return Decided(proposal_id, decided.run_id, request.decision, decided.state.value, decided.state_version)

    async def run(self, tenant_id: UUID, run_id: UUID) -> dict[str, Any] | None:
```

with:

```python

    async def run(self, tenant_id: UUID, run_id: UUID) -> dict[str, Any] | None:
```

Run: `uv run mypy core/src api/src --no-incremental`
Expected: `Success: no issues found in 23 source files`.

Run: `uv run python -m pytest tests/plan_g tests/plan_d/test_api.py tests/plan_f -q`
Expected: `242 passed`.

- [ ] **Step 5: The two live modules that post to the API send keys**

(Moved here from Task 6 so the live suite is never red between tasks.) In `tests/e2e/test_r105_walking_skeleton.py`:

Edit 1 (old lines 12-14), replace:

```python
from typing import Any
from uuid import UUID

```

with:

```python
from typing import Any
from uuid import UUID, uuid4

```

Edit 2 (old lines 83-84), replace:

```python

def wait_for(client: httpx2.Client, url: str, headers: dict[str, str], states: set[str], timeout: float = 45.0) -> dict:
```

with:

```python

def keyed(headers: dict[str, str]) -> dict[str, str]:
    """A mutation's headers with a fresh Idempotency-Key (BS:264; required on every /api/v1 mutation since T12)."""
    return {**headers, "Idempotency-Key": str(uuid4())}


def wait_for(client: httpx2.Client, url: str, headers: dict[str, str], states: set[str], timeout: float = 45.0) -> dict:
```

Edit 3 (old lines 118-123), replace:

```python
        assert refused.status_code == 401  # a workload token at the API: wrong audience and azp
        cid = c.post("/api/v1/conversations", headers=a).json()["conversation_id"]
        accepted = c.post(
            f"/api/v1/conversations/{cid}/messages",
            headers=a,
            json={
```

with:

```python
        assert refused.status_code == 401  # a workload token at the API: wrong audience and azp
        cid = c.post("/api/v1/conversations", headers=keyed(a)).json()["conversation_id"]
        accepted = c.post(
            f"/api/v1/conversations/{cid}/messages",
            headers=keyed(a),
            json={
```

Edit 4 (old lines 146-156), replace:

```python
        }
        self_decision = c.post(f"/api/v1/proposals/{pid}/decisions", headers=a, json=decision)
        assert self_decision.status_code == 403  # the requester may not approve their own proposal
        stale = c.post(
            f"/api/v1/proposals/{pid}/decisions", headers=s, json={**decision, "expected_payload_sha256": "0" * 64}
        )
        assert stale.status_code == 409 and stale.json()["code"] == "VERSION_CONFLICT"
        approved = c.post(f"/api/v1/proposals/{pid}/decisions", headers=s, json=decision)
        assert approved.status_code == 200 and approved.json()["status"] == "APPROVED", approved.text
        second = c.post(f"/api/v1/proposals/{pid}/decisions", headers=s, json=decision)
        assert second.status_code == 409  # the first decision wins
```

with:

```python
        }
        self_decision = c.post(f"/api/v1/proposals/{pid}/decisions", headers=keyed(a), json=decision)
        assert self_decision.status_code == 403  # the requester may not approve their own proposal
        stale = c.post(
            f"/api/v1/proposals/{pid}/decisions",
            headers=keyed(s),
            json={**decision, "expected_payload_sha256": "0" * 64},
        )
        assert stale.status_code == 409 and stale.json()["code"] == "VERSION_CONFLICT"
        approved = c.post(f"/api/v1/proposals/{pid}/decisions", headers=keyed(s), json=decision)
        assert approved.status_code == 200 and approved.json()["status"] == "APPROVED", approved.text
        second = c.post(f"/api/v1/proposals/{pid}/decisions", headers=keyed(s), json=decision)
        assert second.status_code == 409  # the first decision wins
```

In `tests/e2e/test_auth_live.py`:

Edit 1 (old lines 11-13), replace:

```python
from pathlib import Path
from uuid import UUID

```

with:

```python
from pathlib import Path
from uuid import UUID, uuid4

```

Edit 2 (old lines 115-117), replace:

```python
    assert refused == [403, 403, 403, 403], refused
    created = session.api.post("/api/v1/conversations", headers=session.mutation_headers())
    assert created.status_code == 201
```

with:

```python
    assert refused == [403, 403, 403, 403], refused
    created = session.api.post(
        "/api/v1/conversations", headers={**session.mutation_headers(), "Idempotency-Key": str(uuid4())}
    )
    assert created.status_code == 201
```

Edit 3 (old lines 231-233), replace:

```python
            me_enabled = c.get("/api/v1/me", headers=headers).status_code
            decided_enabled = c.post(decision_url, headers=headers, json=body).status_code
            assert me_enabled == 200 and decided_enabled == 404, (me_enabled, decided_enabled)
```

with:

```python
            me_enabled = c.get("/api/v1/me", headers=headers).status_code
            keyed = {**headers, "Idempotency-Key": str(uuid4())}  # every /api/v1 mutation carries one (T12)
            decided_enabled = c.post(decision_url, headers=keyed, json=body).status_code
            assert me_enabled == 200 and decided_enabled == 404, (me_enabled, decided_enabled)
```

Edit 4 (old lines 240-242), replace:

```python
            # never 404 (the check is a dependency, T11 review note 2).
            decided = c.post(decision_url, headers=headers, json=body)
            decided_code, decided_body = decided.status_code, decided.json()
```

with:

```python
            # never 404 (the check is a dependency, T11 review note 2).
            decided = c.post(decision_url, headers={**headers, "Idempotency-Key": str(uuid4())}, json=body)
            decided_code, decided_body = decided.status_code, decided.json()
```

- [ ] **Step 6: Gates and commit**

Format, lint and count characters on every file of this task.

Run: `PYTHONUTF8=1 uv run python scripts/check.py`
Expected: `CHECK: GREEN`; pytest `765 passed, 98 skipped` (749 + 16).

Run: `PYTHONUTF8=1 uv run python scripts/check.py --profile test`
Expected: `CHECK: GREEN`; pytest `842 passed, 21 skipped` (765 + 77; R105 now admits through the router and the
units and decides with a key per decision, and the auth module's conversation and decision posts carry keys). Then
`git checkout -- reports/bootstrap reports/skeleton`.

Run: `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts`
Expected: exit 0.

```bash
git add api/src/ops_api/app.py api/src/ops_api/store.py tests/plan_g/test_api_admission.py
git add tests/plan_d/test_api.py tests/plan_f/test_api_auth.py
git add tests/e2e/test_r105_walking_skeleton.py tests/e2e/test_auth_live.py
git commit -m "feat(api): idempotent admission routes, the clarifications route and the test fault hook (T12)"
```

---

### Task 6: Live proof and evidence — crash before commit, replay, the slot race, the clock, the six routes

**Files:**
- Create: `tests/e2e/test_admission_live.py`, `reports/admission/t12-admission.txt` (written by the test)
- Modify: `tests/e2e/conftest.py:143-144` (`PURGE_ORDER`) and `:163-164` (insert `purge_conversation` before
  `SEEDED_TENANTS`), `tests/plan_b/test_evidence.py:4-7`, `:16-18`
- Re-run: `tests/e2e/test_r105_walking_skeleton.py` (six processes; its evidence file is committed)

**Interfaces:**
- Consumes: `ops_api.app.create_app(…, admission=…, profile=Profile.TEST)`, `ROUTE_MESSAGES` (Task 5);
  `ops_api.store.DbStore` (Task 4); `tests.plan_g.fakes.StubVerifier`; `tests.plan_f.auth_fakes.fake_auth`; the e2e
  fixtures `app_conn`, `role_conn`.
- Produces: `tests.e2e.conftest.purge_conversation(conn, conversation_id) -> None`; `PURGE_ORDER` deletes the
  record whose response names the run; `EVIDENCE_ROOTS` includes `reports/admission`.

- [ ] **Step 1: The purge helper and the evidence root**

In `tests/e2e/conftest.py`:

Edit 1 (old lines 143-144), replace:

```python
    "DELETE FROM app.run_directory WHERE run_id = %s",  # the directory references runs
)
```

with:

```python
    "DELETE FROM app.run_directory WHERE run_id = %s",  # the directory references runs
    # T12: the idempotency record of the admission that started the run (its response names the run).
    "DELETE FROM app.idempotency_request WHERE response->>'run_id' = %s::text",
)
```

Edit 2 (old lines 163-164), replace:

```python

SEEDED_TENANTS = {"3ea79c95-914c-52cb-9d10-c4e19dda8ff7", "5ab45c2c-1e12-5a0c-a2b9-66cd2ff05201"}
```

with:

```python

async def purge_conversation(conn: persistence.Conn, conversation_id: object) -> None:
    """Remove a conversation the admission tests made with everything in it: its runs (as `purge_run` does), every
    message (status answers and clarification questions included, which revision 0006's downgrade refuses to keep)
    and the records whose response names it."""
    cur = await conn.execute("SELECT run_id FROM app.runs WHERE conversation_id = %s", (conversation_id,))
    runs = [row["run_id"] for row in await cur.fetchall()]
    async with conn.transaction():
        for run_id in runs:
            for statement in PURGE_ORDER:
                await conn.execute(statement, (run_id,))
        await conn.execute("DELETE FROM app.runs WHERE conversation_id = %s", (conversation_id,))
        await conn.execute("DELETE FROM app.messages WHERE conversation_id = %s", (conversation_id,))
        await conn.execute(
            "DELETE FROM app.idempotency_request WHERE response->>'conversation_id' = %s::text", (conversation_id,)
        )
        await conn.execute("DELETE FROM app.conversations WHERE conversation_id = %s", (conversation_id,))


SEEDED_TENANTS = {"3ea79c95-914c-52cb-9d10-c4e19dda8ff7", "5ab45c2c-1e12-5a0c-a2b9-66cd2ff05201"}
```

In `tests/plan_b/test_evidence.py`:

Edit 1 (old lines 4-7), replace:

```python
and must not appear in any evidence file; in CI no secrets exist, so only the JWT-shape check applies.
`reports/auth` (T11's session and revocation evidence) and `reports/ci` (T06's CI run record) are scanned the
same way.
"""
```

with:

```python
and must not appear in any evidence file; in CI no secrets exist, so only the JWT-shape check applies.
`reports/auth` (T11's session and revocation evidence), `reports/ci` (T06's CI run record) and
`reports/admission` (T12's durable-admission evidence) are scanned the same way.
"""
```

Edit 2 (old lines 16-18), replace:

```python

EVIDENCE_ROOTS = (Path("reports/bootstrap"), Path("reports/skeleton"), Path("reports/auth"), Path("reports/ci"))
JWT = re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")
```

with:

```python

EVIDENCE_ROOTS = (
    Path("reports/bootstrap"),
    Path("reports/skeleton"),
    Path("reports/auth"),
    Path("reports/ci"),
    Path("reports/admission"),
)
JWT = re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")
```

Run: `uv run python -m pytest tests/plan_b/test_evidence.py -q`
Expected: `2 passed` (`reports/admission` does not exist yet; the scan treats a missing root as empty).

- [ ] **Step 2: The live admission module**

Create `tests/e2e/test_admission_live.py`:

```python
"""T12 live (OPS_LIVE=1): durable admission against the per-session test database, through the real API app and
`DbStore` as role `api` in this process (R015, R016, R017, R018, R115, R129; Plan G rulings 6, 11, 15, 24).

Identity is the unit tests' stub verifier (a bearer token is a persona's name) resolved against the seeded
memberships by the real `resolve_identity`; Keycloak is not involved, because nothing here is about tokens (T11 owns
those). Two app instances hold two `api` connections, so a race is a real race in PostgreSQL (spike §4: one process
with one connection serialises it). Writes evidence to reports/admission/ (status codes, counts and the run ids of
the seeded tenant only).

Catches: an acknowledgement before commit or a record without its work (R015), a replay that starts a second run or
a changed body accepted (R016), two runs holding one conversation's slot or a status question that writes a job
(R017), an interval that moves with the clock or a text/form disagreement that starts work (R018), a route no input
reaches live (R129), and an error that is not the safe schema (R115).
"""

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx2
import pytest
import pytest_asyncio
from ops_api import store as st
from ops_api.app import ROUTE_MESSAGES, create_app
from ops_core import persistence, settings
from ops_core.settings import AdmissionSettings, Profile, Role
from psycopg.types.json import Jsonb

from tests.e2e.conftest import purge_conversation
from tests.plan_f.auth_fakes import fake_auth
from tests.plan_g.fakes import StubVerifier

pytestmark = pytest.mark.asyncio

RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
EVIDENCE = Path("reports/admission/t12-admission.txt")
ALPHA = UUID("3ea79c95-914c-52cb-9d10-c4e19dda8ff7")
ALEX = UUID("2fc05986-c7ec-544c-b628-fdb112bbf18a")
SAMPLE = {
    "kind": "investigate",
    "text": "Investigate the alerts on Asset A17 over the last 24 hours.",
    "context": {"asset_id": "A17", "hours": 24},
}
# A week-long replay window, so R018's replay three days on the test clock is still inside it (the default 24 h
# window is SA:297's; the bound is ruling 7's maximum).
WEEK = AdmissionSettings(idempotency_ttl_seconds=604800)


@pytest.fixture(scope="module")
def lines() -> Iterator[list[str]]:
    out = [f"T12 durable admission — {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}"]
    yield out
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")


@pytest_asyncio.fixture
async def created(app_conn: persistence.Conn) -> AsyncIterator[list[str]]:
    """Every conversation a test makes is purged afterwards with all its rows: revision 0006's downgrade (a later
    module's R006 test) refuses a database that still holds a system message."""
    made: list[str] = []
    yield made
    for cid in made:
        await purge_conversation(app_conn, UUID(cid))


@asynccontextmanager
async def api(admission: AdmissionSettings = WEEK) -> AsyncIterator[httpx2.AsyncClient]:
    """The real app over its own `api` connection, lifespan included (the 0006 relation guard runs)."""

    async def store() -> st.Store:
        return st.DbStore(await persistence.connect(settings.app_postgres(Role.API)))

    app = create_app(
        StubVerifier(), store_factory=store, auth_factory=fake_auth, admission=admission, profile=Profile.TEST
    )
    async with app.router.lifespan_context(app):
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(transport=transport, base_url="http://localhost:8000") as client:
            yield client


def h(name: str = "alex", key: str | None = None) -> dict[str, str]:
    return {"Authorization": f"Bearer {name}", "Idempotency-Key": key or str(uuid4())}


async def conversation(c: httpx2.AsyncClient, created: list[str]) -> str:
    r = await c.post("/api/v1/conversations", headers=h())
    status, cid = r.status_code, r.json().get("conversation_id")
    assert status == 201, status
    created.append(str(cid))
    return str(cid)


async def count(app_conn: persistence.Conn, sql: str, *params: Any) -> int:
    cur = await app_conn.execute(sql, params)
    return int((await cur.fetchone())["n"])


def messages(cid: str) -> str:
    return f"/api/v1/conversations/{cid}/messages"


async def test_r015_a_crash_before_commit_leaves_nothing_and_the_retry_commits(
    app_conn: persistence.Conn, created: list[str], lines: list[str]
) -> None:
    async with api() as c:
        cid = await conversation(c, created)
        armed = await c.post("/internal/faults/drop_before_commit", headers=h(), json={"count": 1})
        assert armed.status_code == 200
        crashed = await c.post(messages(cid), headers=h(key="r015-key-0001"), json=SAMPLE)
        crash_status, crash_body = crashed.status_code, crashed.json()
        assert crash_status == 503 and crash_body["retryable"] is False, crash_status
        left = [
            await count(app_conn, "SELECT count(*) AS n FROM app.messages WHERE conversation_id = %s", UUID(cid)),
            await count(app_conn, "SELECT count(*) AS n FROM app.runs WHERE conversation_id = %s", UUID(cid)),
            await count(app_conn, "SELECT count(*) AS n FROM app.idempotency_request WHERE key = %s", "r015-key-0001"),
        ]
        assert left == [0, 0, 0], left  # no ack, and nothing behind it (BS:681)
        retried = await c.post(messages(cid), headers=h(key="r015-key-0001"), json=SAMPLE)
        retry_status, run_id = retried.status_code, retried.json().get("run_id")
        assert retry_status == 202, retry_status
    cur = await app_conn.execute("SELECT type, dedup_key FROM app.jobs WHERE run_id = %s", (UUID(run_id),))
    jobs = [(r["type"], r["dedup_key"]) for r in await cur.fetchall()]
    assert jobs == [("investigate", f"{run_id}:1")]  # after commit the job exists
    lines.append(
        f"R015 crash before commit: 503 retryable=False, left messages/runs/records={left}; retry 202 jobs={len(jobs)}"
    )


async def test_r016_a_replay_resolves_once_and_a_changed_body_conflicts(
    app_conn: persistence.Conn, created: list[str], lines: list[str]
) -> None:
    async with api() as c:
        cid, other = await conversation(c, created), await conversation(c, created)
        first = await c.post(messages(cid), headers=h(key="r016-key-0001"), json=SAMPLE)
        again = await c.post(messages(cid), headers=h(key="r016-key-0001"), json=SAMPLE)
        same = again.content == first.content
        assert first.status_code == again.status_code == 202 and same
        changed = await c.post(
            messages(cid), headers=h(key="r016-key-0001"), json={**SAMPLE, "context": {"asset_id": "A17", "hours": 12}}
        )
        elsewhere = await c.post(messages(other), headers=h(key="r016-key-0001"), json=SAMPLE)
        conflicts = [(r.status_code, r.json()["code"]) for r in (changed, elsewhere)]
        assert conflicts == [(409, "IDEMPOTENCY_CONFLICT")] * 2, conflicts
        runs = await count(app_conn, "SELECT count(*) AS n FROM app.runs WHERE conversation_id = %s", UUID(cid))
        assert runs == 1
        # Ruling 6's re-read path: an expired record the sweeper has not purged yet blocks its key.
        await app_conn.execute(
            "INSERT INTO app.idempotency_request (tenant_id, subject, route, key, fingerprint_sha256, status_code,"
            " response, expires_at) VALUES (%s, %s, %s, 'r016-key-0002', %s, 202, %s,"
            " app.current_time() - interval '1 minute')",
            (ALPHA, ALEX, ROUTE_MESSAGES, "0" * 64, Jsonb({"old": True})),
        )
        blocked = await c.post(messages(other), headers=h(key="r016-key-0002"), json=SAMPLE)
        blocked_code, blocked_message = blocked.status_code, blocked.json()["message"]
        assert (blocked_code, blocked_message) == (409, "Idempotency-Key is not reusable yet; use a new key")
        other_runs = await count(app_conn, "SELECT count(*) AS n FROM app.runs WHERE conversation_id = %s", UUID(other))
        assert other_runs == 0  # the unit's work was rolled back with the failed record insert
    await app_conn.execute("DELETE FROM app.idempotency_request WHERE key = 'r016-key-0002'")
    lines.append(f"R016 replay: 202 twice, same bytes={same}, runs=1; changed body and other conversation: {conflicts}")
    lines.append(f"R016 expired unpurged key: {blocked_code} not reusable, runs started=0")


async def test_r017_one_active_run_per_conversation(
    app_conn: persistence.Conn, created: list[str], lines: list[str]
) -> None:
    async with api() as one, api() as two:  # two apps, two `api` connections: the race reaches PostgreSQL
        cid = await conversation(one, created)
        raced = await asyncio.gather(
            one.post(messages(cid), headers=h(), json=SAMPLE), two.post(messages(cid), headers=h(), json=SAMPLE)
        )
        statuses = sorted(r.status_code for r in raced)
        codes = [r.json().get("code") for r in raced if r.status_code == 409]
        assert statuses == [202, 409] and codes == ["SLOT_OCCUPIED"], statuses
        held = await count(
            app_conn, "SELECT count(*) AS n FROM app.runs WHERE conversation_id = %s AND slot_held", UUID(cid)
        )
        assert held == 1
        twin = await conversation(one, created)
        same_key = await asyncio.gather(
            one.post(messages(twin), headers=h(key="r017-key-0001"), json=SAMPLE),
            two.post(messages(twin), headers=h(key="r017-key-0001"), json=SAMPLE),
        )
        twins = [r.status_code for r in same_key]
        assert twins == [202, 202] and same_key[0].content == same_key[1].content  # the advisory lock, then a replay
        twin_runs = await count(app_conn, "SELECT count(*) AS n FROM app.runs WHERE conversation_id = %s", UUID(twin))
        assert twin_runs == 1
        before = [
            await count(
                app_conn,
                "SELECT count(*) AS n FROM app.jobs j JOIN app.runs r ON r.run_id = j.run_id"
                " WHERE r.conversation_id = %s",
                UUID(cid),
            ),
            await count(app_conn, "SELECT count(*) AS n FROM app.events e WHERE e.conversation_id = %s", UUID(cid)),
        ]
        status = await one.post(messages(cid), headers=h(), json={"kind": "status", "text": "Where is my run?"})
        after = [
            await count(
                app_conn,
                "SELECT count(*) AS n FROM app.jobs j JOIN app.runs r ON r.run_id = j.run_id"
                " WHERE r.conversation_id = %s",
                UUID(cid),
            ),
            await count(app_conn, "SELECT count(*) AS n FROM app.events e WHERE e.conversation_id = %s", UUID(cid)),
        ]
        status_code, answer = status.status_code, status.json()["answer"]
        assert status_code == 200 and after == before and answer.startswith("Run ")
        busy = await one.post(messages(cid), headers=h(), json=SAMPLE)
        busy_code = (busy.status_code, busy.json()["code"])
        assert busy_code == (409, "SLOT_OCCUPIED")
    lines.append(f"R017 race, two connections, two keys: {statuses}; one key: {twins} with one run; slot holders=1")
    lines.append(
        f"R017 status question while busy: 200, jobs/events unchanged {before}; sequential admission {busy_code}"
    )


async def test_r018_the_interval_is_resolved_once_and_ambiguity_clarifies(
    app_conn: persistence.Conn, role_conn: RoleConn, created: list[str], lines: list[str]
) -> None:
    harness = await role_conn(Role.TEST_HARNESS)
    try:
        await harness.execute("UPDATE app.test_clock SET clock_offset = interval '2 hours'")
        async with api() as c:
            cid = await conversation(c, created)
            first = await c.post(messages(cid), headers=h(key="r018-key-0001"), json=SAMPLE)
            run_id = UUID(first.json()["run_id"])
            cur = await app_conn.execute(
                "SELECT start_at, end_at, end_at - clock_timestamp() AS ahead FROM app.runs WHERE run_id = %s",
                (run_id,),
            )
            stored = await cur.fetchone()
            ahead = stored["ahead"]
            # The window ends on the database clock, two hours ahead of the wall clock (ruling 11; spike §7).
            assert timedelta(hours=1, minutes=59) < ahead < timedelta(hours=2, minutes=1), ahead
            await harness.execute("UPDATE app.test_clock SET clock_offset = interval '3 days 2 hours'")
            replay = await c.post(messages(cid), headers=h(key="r018-key-0001"), json=SAMPLE)
            assert replay.status_code == 202 and replay.content == first.content
            cur = await app_conn.execute("SELECT start_at, end_at FROM app.runs WHERE run_id = %s", (run_id,))
            again = await cur.fetchone()
            assert (again["start_at"], again["end_at"]) == (stored["start_at"], stored["end_at"])
            fresh = await c.post(messages(cid), headers=h(), json=SAMPLE)
            fresh_code = (fresh.status_code, fresh.json()["code"])
            assert fresh_code == (409, "SLOT_OCCUPIED")  # a new request, and the run still holds the slot
            ask = await conversation(c, created)
            conflict = {
                "kind": "investigate",
                "text": "Investigate B22 over the last 24 hours.",
                "context": {"asset_id": "A17", "hours": 24},
            }
            clarified = await c.post(messages(ask), headers=h(), json=conflict)
            clarify = (clarified.status_code, clarified.json()["cause"])
            assert clarify == (200, "asset_conflict"), clarify
        cur = await app_conn.execute(
            "SELECT kind, author IS NULL AS system FROM app.messages WHERE conversation_id = %s ORDER BY seq",
            (UUID(ask),),
        )
        stored_kinds = [(r["kind"], r["system"]) for r in await cur.fetchall()]
        assert stored_kinds == [("investigate", False), ("clarification_question", True)]
        runs_after = await count(app_conn, "SELECT count(*) AS n FROM app.runs WHERE conversation_id = %s", UUID(ask))
        assert runs_after == 0  # a stored clarification and never a job (R018)
    finally:
        await harness.execute("UPDATE app.test_clock SET clock_offset = interval '0'")
    lines.append(
        f"R018 window ends {ahead} past the wall clock (test clock +2 h); replay at +3 d: 202, same bytes and interval"
    )
    lines.append(
        f"R018 new key while active: {fresh_code}; text B22 vs form A17: {clarify}, messages={stored_kinds}, runs=0"
    )


async def test_r129_every_admission_route_live(
    app_conn: persistence.Conn, role_conn: RoleConn, created: list[str], lines: list[str]
) -> None:
    worker = await role_conn(Role.WORKER)
    seen: dict[str, Any] = {}
    async with api() as c:
        investigate = await c.post(messages(cid := await conversation(c, created)), headers=h(), json=SAMPLE)
        seen["investigate"] = investigate.status_code
        status = await c.post(messages(cid), headers=h(), json={"kind": "status", "text": "Status?"})
        seen["status_question"] = status.status_code
        ask = await c.post(
            messages(await conversation(c, created)),
            headers=h(),
            json={"kind": "ask", "text": "What did A17 log in the last day?"},
        )
        seen["readonly_answer"] = ask.status_code
        clarify = await c.post(
            messages(await conversation(c, created)),
            headers=h(),
            json={"kind": "investigate", "text": "Investigate A17."},
        )
        seen["clarify"] = clarify.status_code
        reject = await c.post(
            messages(await conversation(c, created)), headers=h(), json={"kind": "clarification", "text": "A17"}
        )
        seen["reject"] = reject.status_code
        # Nothing in the worker asks for clarification yet (T20), so the run is staged where the worker would put it,
        # through the worker role's own function (as tests/e2e/test_definers_run_path_live.py does).
        run_id = UUID(investigate.json()["run_id"])
        async with worker.transaction():
            await worker.execute("SELECT app.transition_run(%s, 'QUEUED', 'RETRIEVING', NULL, 1, '{}')", (run_id,))
            await worker.execute(
                "SELECT app.transition_run(%s, 'RETRIEVING', 'AWAITING_INPUT', NULL, 2, '{}')", (run_id,)
            )
        cur = await app_conn.execute(
            "SELECT event_id FROM app.events WHERE run_id = %s AND type = 'clarification.requested'", (run_id,)
        )
        question = (await cur.fetchone())["event_id"]
        body = {"question_id": str(question), "expected_version": 3, "context": {"hours": 12}}
        reply = await c.post(f"/api/v1/runs/{run_id}/clarifications", headers=h(), json=body)
        seen["clarification_reply"] = reply.status_code
    assert seen == {
        "investigate": 202,
        "status_question": 200,
        "readonly_answer": 202,
        "clarify": 200,
        "reject": 422,
        "clarification_reply": 202,
    }, seen
    cur = await app_conn.execute("SELECT intent FROM app.runs WHERE run_id = %s", (UUID(ask.json()["run_id"]),))
    assert (await cur.fetchone())["intent"] == "answer_only"
    cur = await app_conn.execute(
        "SELECT dedup_key FROM app.jobs WHERE run_id = %s AND type = 'resume_input'", (run_id,)
    )
    assert [r["dedup_key"] for r in await cur.fetchall()] == [f"{run_id}:{question}"]
    cur = await app_conn.execute("SELECT type FROM app.events WHERE run_id = %s ORDER BY sequence", (run_id,))
    events = [r["type"] for r in await cur.fetchall()]
    assert events[-1] == "clarification.received", events
    lines.append(f"R129 routes: {seen}; answer_only run, resume_input job and clarification.received recorded")


async def test_r115_live_errors_use_the_safe_schema(created: list[str], lines: list[str]) -> None:
    codes: list[int] = []
    async with api(AdmissionSettings(max_body_bytes=1024)) as c:
        cid = await conversation(c, created)
        refusals = [
            await c.get("/api/v1/me", headers={"Authorization": "Bearer nobody"}),  # 401
            await c.post(messages(cid), headers=h("sam"), json=SAMPLE),  # 403: a reviewer cannot ask
            await c.post(messages(str(uuid4())), headers=h(), json=SAMPLE),  # 404
            await c.post(messages(cid), headers={"Authorization": "Bearer alex"}, json=SAMPLE),  # 422: no key
            await c.post(messages(cid), headers=h(), content=b" " * 1025),  # 422: body over the limit
            await c.get("/nope"),  # 404 from the router itself
        ]
        for r in refusals:
            status, doc, header = r.status_code, r.json(), r.headers.get("X-Request-Id")
            assert set(doc) == {"code", "message", "retryable", "request_id"} and doc["request_id"] == header, status
            codes.append(status)
    assert codes == [401, 403, 404, 422, 422, 404], codes
    lines.append(f"R115 live sample: {codes}, every body the safe schema with its X-Request-Id")
```

Run: `uv run python -m pytest tests/e2e/test_admission_live.py -q`
Expected: `6 skipped` (the live gate).

- [ ] **Step 3: Run it live and read the evidence**

With the dev stack up and `uv run python scripts/skeleton.py status` showing every process down:

Run: `OPS_LIVE=1 PYTHONUTF8=1 uv run python -m pytest tests/e2e/test_admission_live.py -q`
Expected: `6 passed`.

`reports/admission/t12-admission.txt` then holds the header `T12 durable admission — <UTC time>` and nine lines, in
this order and of these shapes (the counts and statuses are exact; the run-free lines carry no id at all):

```text
R015 crash before commit: 503 retryable=False, left messages/runs/records=[0, 0, 0]; retry 202 jobs=1
R016 replay: 202 twice, same bytes=True, runs=1; changed body and other conversation: [(409, 'IDEMPOTENCY_CONFLICT'),
(409, 'IDEMPOTENCY_CONFLICT')]
R016 expired unpurged key: 409 not reusable, runs started=0
R017 race, two connections, two keys: [202, 409]; one key: [202, 202] with one run; slot holders=1
R017 status question while busy: 200, jobs/events unchanged [1, 1]; sequential admission (409, 'SLOT_OCCUPIED')
R018 window ends 1:59:59.<µs> past the wall clock (test clock +2 h); replay at +3 d: 202, same bytes and interval
R018 new key while active: (409, 'SLOT_OCCUPIED'); text B22 vs form A17: (200, 'asset_conflict'), messages=
[('investigate', False), ('clarification_question', True)], runs=0
R129 routes: {'investigate': 202, 'status_question': 200, 'readonly_answer': 202, 'clarify': 200, 'reject': 422,
'clarification_reply': 202}; answer_only run, resume_input job and clarification.received recorded
R115 live sample: [401, 403, 404, 422, 422, 404], every body the safe schema with its X-Request-Id
```

(The two R016 lines, the R018 line with the message list and the R129 line are one line each in the file; they are
wrapped here at 120 characters.) Read the file and confirm it holds no token, no cookie and no id of the second
tenant (it holds none of either by construction: the bearer values are persona names, and every row is ALPHA's).

- [ ] **Step 4: The walking skeleton again, six processes, keys on every mutation**

Run: `OPS_LIVE=1 PYTHONUTF8=1 uv run python -m pytest tests/e2e/test_r105_walking_skeleton.py -q`
Expected: `1 passed`; `reports/skeleton/r105-walking-skeleton.txt` is rewritten with the same nine events ending
`action.confirmed`.

- [ ] **Step 5: Gates and commit**

Format, lint and count characters on the three test files.

Run: `PYTHONUTF8=1 uv run python scripts/check.py`
Expected: `CHECK: GREEN`; pytest `765 passed, 104 skipped` (98 + the 6 live tests skipped).

Run: `PYTHONUTF8=1 uv run python scripts/check.py --profile test`
Expected: `CHECK: GREEN`; pytest `848 passed, 21 skipped` (765 + 83 live). The admission module runs first in
the e2e directory (alphabetical) and purges every conversation it made, so the R006 downgrade later in the session
passes revision 0006's guard. Then `git checkout -- reports/bootstrap` (the admission and R105 evidence files are
committed below).

Run: `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts`
Expected: exit 0.

```bash
git add tests/e2e/test_admission_live.py tests/e2e/conftest.py tests/plan_b/test_evidence.py
git add reports/admission/t12-admission.txt reports/skeleton/r105-walking-skeleton.txt
git commit -m "test(e2e): live durable admission: crash, replay, the slot race, the clock, six routes (T12)"
```

---

### Task 7: Handoff close-out — records, errata, documentation, final gates

**Files:**
- Modify: `handoff/tasks.json` (T12 → `DONE`, one review note), `handoff/acceptance-matrix.json` (R015, R016,
  R017, R018, R115, R129), `handoff/BUILD_BACKLOG.md` (T12 checked, one review note), `SESSION_STATE.md` (the "Next
  task" line, a "Plan G executed" section, the dev database state, the owner inputs), `STATUS.md` (an update
  section), `docs/PROJECT_HISTORY.md` (§24 new, the closing section renumbered §25), `README.md:5` (status line),
  `api/README.md` (the "Runs" section), `docs/runbooks/walking-skeleton.md:21`, `:43`,
  `docs/runbooks/dev-topology.md` (a new last section), this plan (its checkboxes)

Throughout, `<first>..<last>` is the commit range of this plan's execution on `plan-g`: `<first>` is the debt-list
commit of Task 1 Step 1 and `<last>` the newest commit before this task's own (print both with
`git log --reverse --format=%h b4e97bc..HEAD | sed -n '1p;$p'`), and `<date>` is `date -u +%F` on the day of the
close-out.

- [ ] **Step 1: Handoff records**

Run this once from the repository root (it rewrites the two JSON files in their own format: two-space indent,
non-ASCII kept, one trailing newline, which round-trips both files byte for byte today):

```bash
uv run python - <<'EOF'
import json
import subprocess
from pathlib import Path

hashes = subprocess.run(
    ["git", "log", "--reverse", "--format=%h", "b4e97bc..HEAD"], capture_output=True, text=True, check=True
).stdout.split()
span = f"{hashes[0]}..{hashes[-1]}"
note = (
    f"Plan G (branch plan-g): done in {span} (the seven tasks; plan "
    "docs/superpowers/plans/2026-10-10-first-slice-g-admission-idempotency.md). Shipped: the scoped Idempotency-Key "
    "on every /api/v1 mutation (tenant, subject, route template, key; fingerprint over the path and the validated "
    "body; the record is the response, written last under an advisory lock on the scope, 24 h on the application "
    "clock, purged by the sweeper); revision 0006 (app.idempotency_request, messages.seq, the stored-kind CHECK, "
    "author NULL for system rows); the AM-16 admission router as ADMISSION_RULES in core/routing.py with the "
    "text-versus-fields parser (clarify on any disagreement, never a guess) and REPLY_RULES for "
    "POST /api/v1/runs/{id}/clarifications (message + resume_input job + clarification.received); status answers "
    "and conversation-level clarifications stored as messages; the interval resolved once on app.current_time() "
    "inside the unit; the per-tenant queue quota (429, Retry-After 5); the safe error surface (request ids, "
    "framework 404/405 and every exception class mapped, retryable only for outages) and the 64 KiB body limit "
    "as middleware; the test-profile fault route. Evidence: tests/e2e/test_admission_live.py and "
    "reports/admission/t12-admission.txt (live), tests/plan_g/ for the unit half; R105 re-run with keys. "
    "Deferred: the global queue bound -> T13; the model hint's producer -> T19; resume_input handling and the "
    "ANSWERED path -> T20; stream_url -> T27; response schemas -> T26; the feedback table -> T21. Errata 35-43 "
    "are proposed in SESSION_STATE.md."
)
tasks_path = Path("handoff/tasks.json")
tasks = json.loads(tasks_path.read_text(encoding="utf-8"))
t12 = next(t for t in tasks["tasks"] if t["id"] == "T12")
t12["status"] = "DONE"
t12["review_notes"].append(note)
tasks_path.write_text(json.dumps(tasks, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")

matrix_path = Path("handoff/acceptance-matrix.json")
matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
units = {
    "R015": ["tests/plan_g/test_store_units.py", "tests/plan_g/test_api_admission.py"],
    "R016": ["tests/plan_g/test_idempotency.py", "tests/plan_g/test_api_admission.py"],
    "R017": ["tests/plan_g/test_store_units.py", "tests/plan_g/test_routing_admission.py"],
    "R018": ["tests/plan_g/test_routing_admission.py", "tests/plan_g/test_store_units.py"],
    "R115": ["tests/plan_g/test_error_surface.py", "tests/plan_g/test_limits.py", "tests/plan_g/test_api_admission.py"],
    "R129": ["tests/plan_g/test_routing_admission.py", "tests/plan_g/test_api_admission.py"],
}
notes = {
    "R129": "Plan G (T12): the admission router half; the graph router's table and its walk land with T20.",
    "R018": "Plan G (T12): the interval is resolved on app.current_time() inside the unit; the live test moves "
    "the test clock by 3 days and replays.",
}
for row in matrix["requirements"]:
    if row["id"] in units:
        row["implementation_status"] = "IMPLEMENTED_LOCALLY_VERIFIED"
        row["evidence_status"] = "RECORDED_LOCALLY_LIVE"
        row["evidence_paths"] = ["tests/e2e/test_admission_live.py", "reports/admission/t12-admission.txt"]
        row["evidence_paths"] += units[row["id"]]
        row["note"] = notes.get(row["id"], "Plan G (T12): live evidence runs under check.py --profile test.")
matrix_path.write_text(json.dumps(matrix, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")

backlog_path = Path("handoff/BUILD_BACKLOG.md")
backlog = backlog_path.read_text(encoding="utf-8")
head = "- [ ] **T12 Durable admission API and error mapping**"
assert backlog.count(head) == 1
backlog = backlog.replace(head, "- [x] **T12 Durable admission API and error mapping**")
anchor = "  - *Review note:* Status answers and conversation-level clarifications are messages"
start = backlog.index(anchor)
end = backlog.index("\n", start) + 1
backlog = backlog[:end] + f"  - *Review note:* {note}\n" + backlog[end:]
backlog_path.write_text(backlog, encoding="utf-8", newline="\n")
print(span)
EOF
```

Expected: it prints the span (for example `1a2b3c4..5d6e7f8`). `git diff --stat handoff` shows three files changed;
`git diff handoff/acceptance-matrix.json` shows only the six rows.

- [ ] **Step 2: Project state**

In `SESSION_STATE.md`:

1. Replace the whole line that begins `**Next task:**` with:

```markdown
**Next task:** Plan G (T12) is executed on branch `plan-g` (`<first>..<last>`, on top of `plan-f`: the seven tasks;
the close-out commit follows). Owner inputs: (1) the holdout seal (T03 step 9), then the live probe (T02); (2) merge
the stacked PRs in order and open the plan-g -> plan-f PR; (3) T44 step 10 (`docs/runbooks/ollama-network.md` step
A); (4) decide the proposed errata of Plans C, E, F and G (G: 35-43 below); (5) migrate the dev database to revision
0006 (`uv run python scripts/skeleton.py migrate`, dev profile: it adds `app.idempotency_request` and
`messages.seq` and numbers the existing messages; nothing is deleted). Next is Plan H: T13 (leases, wake-ups and the
lease fence; it now also owns the global queue bound), the earliest dependency-satisfied task in `handoff/tasks.json`.
```

2. Insert, after the `## Plan F executed …` section and before `## Walking-skeleton debt list …`:

```markdown
## Plan G executed (<date>, branch `plan-g`)

- T12 = `<first>..<last>` (the debt list first, then the seven tasks). The plan
  (`docs/superpowers/plans/2026-10-10-first-slice-g-admission-idempotency.md`) holds the thirty rulings; the
  inputs are `docs/superpowers/research/2026-10-09-plan-g-inputs.md` and
  `docs/superpowers/research/2026-10-10-plan-g-spike.md`.
  Evidence: `tests/e2e/test_admission_live.py` and `reports/admission/t12-admission.txt` (header plus nine lines),
  `tests/e2e/test_migration_0006_live.py`, `reports/skeleton/r105-walking-skeleton.txt` (R105 with keys); the unit
  half is in `tests/plan_g/`.
- Gates: `check.py` 765 passed / 104 skipped; `check.py --profile test` 848 passed / 21 skipped; `verify_handoff.py`
  exit 0 (STATUS.md, "Update - Plan G executed").
- **Proposed errata (the owner decides; the spec text stays authoritative until then).** Numbered on from Plan F's
  thirty-four:
  35. BS:264: the Idempotency-Key is required on every `/api/v1` mutation; `/auth/logout`, `/auth/backchannel-logout`
      and the test-profile fault route are exempt by design.
  36. SA:429 (AM-20.2 `idempotency_request`): the sweeper holds SELECT beside its DELETE (erratum 25 extended).
  37. SA:188: the lock order begins with the idempotency scope's advisory lock.
  38. BS:548 and R017: a read-only (`answer_only`) run holds the conversation slot and needs an asset and an
      interval.
  39. BS:550: T12 bounds QUEUED runs per tenant (default 100); the global bound moves to T13.
  40. SA:369 (AM-16 `clarification_reply`): the entry is BS:273's `POST /api/v1/runs/{id}/clarifications`; on the
      messages route `kind=clarification` is a 422 reject.
  41. SA:450: `supersedes_run_id` is validated against the tenant and the conversation.
  42. BS:230 with SA:370/SA:372: the message sequence is the table-wide identity `messages.seq`; the stored kinds
      are `investigate`, `ask`, `status_question`, `status_answer`, `clarification_question`, `clarification_reply`;
      `author` is NULL exactly for the two system kinds.
  43. BS:301: a wrong method keeps 405 (`INVALID_INPUT`, with `Allow`); the body limit is 422, never 413, and is
      checked before identity because it is middleware.
- Rulings made during execution: each one the task reviews recorded, one line each with its reason; when there were
  none, the line reads "none beyond the plan".
- **Open items for later**, parked by the task reviews (from the SDD ledger
  `.superpowers/sdd/2026-10-10-first-slice-g-admission-idempotency/progress.md`; in a literal run with no ledger, the
  line reads "none recorded").
```

3. Under `## Dev database state (2026-10-08)`, append the paragraph:

```markdown
**Update (<date>):** Plan G adds revision 0006. The dev `ops` database stays at 0005 until the owner runs
`uv run python scripts/skeleton.py migrate` (dev profile); until then `skeleton.py up` fails fast because the API
and the sweeper refuse to start without `app.idempotency_request`. The upgrade adds the table, numbers the existing
messages through the new identity column and changes no row.
```

4. Under `## Open owner inputs`, add as the first bullet:

```markdown
- Migrate the dev database to revision 0006 (`uv run python scripts/skeleton.py migrate`, dev profile), then decide
  errata 35-43 (see "Plan G executed").
```

- [ ] **Step 3: Status, history and the documents**

`STATUS.md`: append

```markdown
## Update — Plan G executed (<date>, branch `plan-g`)

- Plan G (T12 durable admission, the AM-16 admission router, the scoped Idempotency-Key and the safe error
  surface) executed on branch `plan-g` (`<first>..<last>`, on top of `plan-f`). The plan is
  `docs/superpowers/plans/2026-10-10-first-slice-g-admission-idempotency.md`.
- `PYTHONUTF8=1 uv run python scripts/check.py` is `CHECK: GREEN`: pytest `765 passed, 104 skipped`.
  `PYTHONUTF8=1 uv run python scripts/check.py --profile test` is `CHECK: GREEN`: pytest `848 passed, 21 skipped`.
  `uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts` exits 0.
- **Evidenced** (acceptance matrix `RECORDED_LOCALLY_LIVE` / `IMPLEMENTED_LOCALLY_VERIFIED`): R015, R016, R017,
  R018, R115 and R129 (the admission half; T20 owns the graph router's). A crash before commit leaves no message,
  run, job or record and the same key then commits; a replay returns the first answer byte for byte and a changed
  body or another conversation under the same key is 409; two connections racing one conversation give one 202 and
  one 409 with one slot holder, and one key racing itself gives two identical 202s and one run; the interval ends on
  the database clock and a replay three days later returns the same interval; a text that disagrees with the form
  is a stored clarification and never a job; every admission route answers live; every error is the safe schema
  with its request id (`reports/admission/t12-admission.txt`).
- The dev `ops` database needs revision 0006 (an owner input); the API and the sweeper refuse to start until then.
- Deferred, each with its owner in `SESSION_STATE.md`: the global queue bound -> T13; the model hint's producer ->
  T19; `resume_input` handling and the ANSWERED path -> T20; `stream_url` -> T27; response schemas -> T26; the
  `feedback` table -> T21. Nine errata (35-43) are proposed for the owner to decide.
```

`docs/PROJECT_HISTORY.md`: rename the heading `## 24. What the process taught` to `## 25. What the process taught`
(its text is unchanged) and insert before it:

```markdown
## 24. The admission plan was measured into a different design before a line was written

**Problem.** T12 asks for the API's durable core: a scoped Idempotency-Key, the six AM-16 admission routes as a
table, one active run per conversation, an interval resolved once, and a safe error for every status code. The fact
sheet found the obvious shapes wrong before any design existed: the idempotency table the spec names did not exist,
nothing computed a request's identity, the API resolved "last 24 hours" on the Python wall clock while the run's
history used the database's, the framework still answered unknown paths and unhandled exceptions in its own
formats, and no body limit existed at all. The spike then measured each obvious fix and found most of them unsafe.
Writing the idempotency row last, as the spec's lock order says, made a racing retry of the same key lose to the
slot index and answer 409 instead of its recorded 202; writing it first made the loser fail with a unique-violation
whose detail printed the tenant, the subject and the key in clear. Starlette's own body limiter answered a plain-text
413 after the route had already created a conversation, and never stopped a route that reads no body. Two messages
written in one transaction shared their timestamp, so a status question and its answer had no order; and the API's
role could neither lock a conversation nor count queued work across tenants.

**Change.** The plan took the measured shapes instead: an advisory lock on the key's scope as the unit's first
statement (the loser waits and replays), the record written last and holding the full answer, a pre-reading ASGI
middleware for the body limit, an identity column for message order (a serial would have needed a grant the role
lacks), the interval read from `app.current_time()` inside the unit, and a per-tenant quota with the global bound
declared for T13. The orchestration is written once over a small set of primitive operations, so the unit tests run
the same lock-lookup-work-record code as PostgreSQL rather than a copy of it. Execution's findings follow, one
paragraph per task that needed a fix round, in the same Problem/Change form; a task that passed on its first review
gets no paragraph.
```

Then, below that section and still before `## 25.`, add one `**Problem.**`/`**Change.**` pair per finding the task
reviews and the final review recorded (from the SDD ledger), or the single sentence "Execution found nothing the
plan had not ruled on." when they recorded none.

`README.md`, line 5: replace the status sentence's tail ", durable admission is next (Plan G)" with ", and durable
admission with a scoped Idempotency-Key and the AM-16 router (T12)", so the line reads (one line in the file; wrapped
here):

```markdown
> **Status: walking skeleton runs locally (T08) under per-service database roles with RLS (T09) and a hardened
destination (T10), with browser login with server-side sessions, revocation and the membership sync (T11); the dev
realm now carries the Plan F clients (re-imported on `up`), and durable admission with a scoped Idempotency-Key and
the AM-16 router (T12)** ([runbook](docs/runbooks/walking-skeleton.md)). Read [STATUS.md](STATUS.md) before
interpreting any capability below as built. The capabilities described are **targets**.
```

`api/README.md`: replace the section from `## Runs (T08)` to the end of the file with:

```markdown
## Runs (T08, T11, T12)

`python -m ops_api` on 127.0.0.1:8000 (`OPS_API_PORT`). Identity: bearer persona tokens (`aud ops-api`, `azp
ops-dev-direct`) or the browser session cookie (T11), resolved to a tenant and roles through current memberships on
every request. Endpoints: `/api/v1/me`, `POST /api/v1/conversations`, `POST /api/v1/conversations/{id}/messages`
(the AM-16 admission router: 202 for a run, 200 for a clarification or a status answer, 409, 422, 429),
`POST /api/v1/runs/{id}/clarifications` (202), `GET /api/v1/runs/{id}`, `GET /api/v1/proposals/{id}`,
`POST /api/v1/proposals/{id}/decisions` (independent reviewer, exact revision and hash, first decision wins),
`GET /api/v1/runs/{id}/events`, and the `/auth/*` routes. Every `/api/v1` mutation needs an `Idempotency-Key`
header (8-128 visible ASCII characters); the same key and request replay the recorded answer, the same key with
another request is 409 `IDEMPOTENCY_CONFLICT`. Every response carries `X-Request-Id`; every error is
`{code, message, retryable, request_id}`. Bodies over `OPS_MAX_BODY_BYTES` (65536) are refused before routing.
Settings: `OPS_MAX_BODY_BYTES`, `OPS_IDEMPOTENCY_TTL_SECONDS` (86400), `OPS_TENANT_QUEUE_QUOTA` (100).
```

`docs/runbooks/walking-skeleton.md`: in the line under step 3 that begins
`   The dev database must carry revision 0005`, and in the sentence ending `database carries revision 0005
(`skeleton.py migrate`).`, change `0005` to `0006`; the step-3 line then reads (one line in the file; wrapped here):

```markdown
   The dev database must carry revision 0006 (`skeleton.py migrate`) before `up`: the API and the sweeper refuse
   to start otherwise. The browser login walk-through is in `dev-topology.md`.
```

`docs/runbooks/dev-topology.md`: append at the end of the file:

```markdown

## Admission (T12)

A client creates a conversation (`POST /api/v1/conversations`, 201) and posts messages to it
(`POST /api/v1/conversations/{id}/messages`). Every such mutation carries an `Idempotency-Key` header of 8-128
visible ASCII characters (a UUID is the usual choice), new for each new request and the same for a retry: the API
records the answer of each key with the request's fingerprint for 24 h (`OPS_IDEMPOTENCY_TTL_SECONDS`), returns that
answer to a retry, and refuses a reuse with another request (409 `IDEMPOTENCY_CONFLICT`). A message of kind
`investigate` or `ask` starts a run (202) only when its text agrees with its form fields; otherwise the API stores a
clarification question and answers 200 with it, and the requester sends a new message. `kind=status` is answered
from the recorded state (200, no run). A reply to a run's own question goes to
`POST /api/v1/runs/{id}/clarifications` with the question id and the run's version. One conversation holds one
active run (409 `SLOT_OCCUPIED`); a tenant holds at most `OPS_TENANT_QUEUE_QUOTA` queued runs (429, `Retry-After`).
Under `PROFILE=test` only, `POST /internal/faults/drop_before_commit` arms the crash-before-commit fault the live
test uses.
```

- [ ] **Step 4: Final gates**

```bash
PYTHONUTF8=1 uv run python scripts/check.py
PYTHONUTF8=1 uv run python scripts/check.py --profile test
uv run python -I scripts/verify_handoff.py --reference-code --manifest --contracts
```

Expected: `CHECK: GREEN` with `765 passed, 104 skipped`; `CHECK: GREEN` with `848 passed, 21 skipped`; exit 0.
Then `git checkout -- reports/bootstrap`; commit `reports/admission` and `reports/skeleton` only if the live run
changed them. Tick this plan's checkboxes (`- [ ]` → `- [x]`) for every step executed.

- [ ] **Step 5: Commit**

```bash
git add handoff SESSION_STATE.md STATUS.md README.md api/README.md docs/PROJECT_HISTORY.md docs/runbooks
git add docs/superpowers/plans/2026-10-10-first-slice-g-admission-idempotency.md reports/admission reports/skeleton
git commit -m "docs: close T12 - handoff records, acceptance rows, errata 35-43, runbooks (Plan G)"
```

---

## Self-review (run by the plan's author before execution)

1. **Spec coverage.** T12 instructions: `/api/v1` conversations/messages/runs → Task 5 (routes) over Task 4 (units);
   message + run + job + event committed before 202 → Task 4 (`_start` inside one unit, the record last) with R015
   live in Task 6; scoped Idempotency-Key (24 h) → rulings 1-7, Tasks 2 (table), 4 (`idempotency.py`, units), 5
   (dependency); one active run per conversation → ruling 9, Task 3 (slot row), Task 4 (`Conflict` backstop), Task 6
   (R017 race); interval resolved once → ruling 11, Task 4 (`unit.now()`), Task 6 (R018 at +3 days); safe error
   schema and the 401/403/404/409/422/429/503 mapping → rulings 19-20, Task 1 and Task 5 (`test_api_admission.py`
   reaches every code: 401 and 403 in `test_the_key_comes_after_identity_and_role_and_before_the_body`, 404 and 409
   `SLOT_OCCUPIED` in `test_router_verdicts_are_recorded_and_replayed`, 409 `IDEMPOTENCY_CONFLICT` in the replay
   test, 409 `VERSION_CONFLICT` in the stale-reply and decision tests, 422 for the key, the body parse, the router
   reject (six-routes test) and the body size (Task 1), 429 in the quota test, 503 both ways in the fault and
   lost-database tests); the six AM-16 routes as a table in `core/routing.py`, deterministic-first, the hint only
   producing clarify → rulings 12, 16, Task 3; investigate/readonly_answer through `create_run` with intent → Task 4
   (`Intent.INVESTIGATE`/`ANSWER_ONLY`), Task 6 (`runs.intent = 'answer_only'`); status questions and
   conversation-level clarifications stored as messages with their kinds → rulings 13, 14, 26, Tasks 2, 3, 4. DoD 1
   → Task 6 R015 (and Task 4/5 unit tests); DoD 2 → Task 4, Task 5, Task 6 R016; DoD 3 → the list above; DoD 4 →
   Task 3 (every row and cause), Task 5 (six routes over HTTP), Task 6 R129 and R018 (stored clarification, no job,
   unroutable kind 422). Review note 1 → ruling 9 and Task 6 R017; review note 2 → rulings 13, 14, 16 (the slot row
   precedes the clarify rows). R015, R016, R017, R018, R115, R129 → Task 6's six live tests and Task 7's rows.
   BS:264 → ruling 1 (erratum 35); BS:299 → rulings 4, 23; BS:301 → rulings 19, 21; BS:546 → ruling 17; BS:547 →
   ruling 12; BS:550 → ruling 18; SA:188 → ruling 6; SA:297 → ruling 7; SA:429/SA:523 → rulings 4, 8; SA:362-375 →
   rulings 12-16.
2. **Placeholder scan.** No TBD, no "similar to Task N", no "add validation". The `TODO(T12)` markers in Task 4's
   `store.py` name the step that removes them (Task 5 Step 4); the `TODO(T19)`/`TODO(T27)` markers are ownership
   markers `docs/CODE_COMMENTS.md` requires. `<first>..<last>` and `<date>` in Task 7 are defined with the command
   that prints them; the evidence shapes in Task 6 Step 3 are the exact strings the test writes (the timedelta's
   microseconds vary).
3. **Type and name consistency.** `AdmissionSettings` fields are the same in `settings.py`, `create_app(admission=…)`,
   `validate_key(raw, bounds)` and the live test's `WEEK`; `safe(request, status, code, message, *, retryable)` is the
   one builder after Task 1 (every call passes the request); `Scope(tenant_id, subject, route, key)`,
   `Idem(scope, fingerprint, ttl_seconds, request_id)` and `Verdict(status, body, replayed)` are built in
   `app.scoped`, the unit tests and the store with the same field order; the store's methods are
   `open_conversation`, `admit_message`, `reply_clarification`, `decide_once` in the `Store` protocol, in
   `AdmissionStore`, in the routes, in `fakes.py` (inherited) and in `test_store_units.py`; `Unit` and `DbUnit` and
   `FakeUnit` share every member (mypy checks `DbUnit` against `Unit` through `DbStore.unit`); the fake's tables are
   `event_log` (not `events`, which is the read method) everywhere; `ROUTE_MESSAGES` is imported by the live test from
   `ops_api.app`; `purge_conversation` is defined in `conftest.py` (Task 6 Step 1) before the live module that imports
   it (Step 2); `StoredMessageKind`/`SYSTEM_MESSAGE_KINDS` (Task 3) match `STORED_KINDS_0006`/`SYSTEM_KINDS_0006`
   (Task 2) by test.
4. **Review Focus.** Key reuse across conversations or bodies (1) → Task 4 and Task 5 tests named there, Task 6 R016;
   malformed keys (2) → Task 4 and Task 5; a lying `Content-Length`, a chunked body, a body-less route (3) → Task 1's
   three tests, Task 6 R115; text naming the form's asset among others versus only others (4) → Task 3's
   `test_text_and_fields` rows and `test_questions_name_what_disagreed`, Task 6 R018; a replay after revocation (5) →
   Task 5; the stale clarification reply → Task 4 and Task 5.

## Plan author's notes

- `BodyLimit` catches `BodyTooLarge` itself (pre-read, then replay) instead of letting a handler convert it: a route
  that never reads its body would otherwise run (spike §5, case 5g); the 422 and its text are ruling 17's.
- The body-size refusal comes before identity (it is middleware and ruling 17 applies it to every route); every
  other step of ruling 21's order holds; erratum 43 records it.
- The store's new methods are `open_conversation`/`admit_message`/`decide_once` (the brief's `create_conversation(…,
  record)`/`admit`/`decide(…, key)`), so the pre-T12 methods live beside them through Task 4 and nothing is red
  between tasks; Task 5 deletes the old ones.
- The orchestration is `store.AdmissionStore` over a `Unit` protocol (SQL in `DbUnit`, memory in `FakeUnit`), and
  `idempotent()` sits in `idempotency.py` over a three-method `RecordUnit`; `status_answer` and `clarify` are
  `AdmissionStore` methods that take the unit, not separate protocol entries.
- The quota count is read at ruling 21's position but refuses only investigate and readonly_answer (ruling 18's
  "before create_run"); a status question or a clarification is never a 429.
- `clarification_reply` is reached through a one-row `REPLY_RULES` table (`route_reply`), because ruling 16's table
  and `AdmissionFacts` have nothing that could select it on the messages route; R129's walk covers both tables.
- R018's live replay runs with a 604800 s window (ruling 7's maximum): with the default 86400 s, the +3-day replay of
  ruling 11 would find the record expired.
- An expired record the sweeper has not purged yet blocks its key (the primary key holds it): the re-read path of
  ruling 6 answers 409 "Idempotency-Key is not reusable yet; use a new key"; that is the pre-inserted-row test.
- The R105 and `test_auth_live.py` key edits move from Task 6 to Task 5 Step 5, so the live suite is never red between
  tasks; Task 6 re-runs R105 and commits its evidence.
- The Plan G debt list is committed in Task 1 Step 1 (SA:698, Plan F's precedent), not only in the close-out.
- `create_app` gains `profile: Profile = Profile.DEV` (incident-sim's shape; `production_app` passes
  `settings.profile()`), the fault route requires a persona (`identity`) and accepts `drop_before_commit` only (other
  kinds are 422).
- The `privileges.py` docstring edit (ruling 29's close-out list) is made in Task 2 with the row; `feedback`'s owner
  there becomes T21 (Plan G creates no feedback table), with a debt line.
- Every verdict renders through one sorted, compact serializer (`VerdictResponse`), because jsonb reorders keys and
  ruling 4 asks for a byte-identical replay.
- A framework `HTTPException` other than 404/405 becomes 422 `INVALID_INPUT` "request refused"; the 405 keeps its
  status and its `Allow` header.
- The parser ignores upper-case tokens longer than an `AssetId` (32 characters), takes the first window when the
  text names several, and finds no window in "last 1000 hours" (three digits at most), which asks `missing_interval`.
- A started run's message stores the resolved `{asset_id, hours}`; a clarification stores the request's own context.
- `ApiError` stays unchanged; its 503s (all identity-provider outages) are rendered retryable by the handler.
- A second clarification reply to the same question under a new key is 409 `VERSION_CONFLICT` "the clarification was
  already answered" (the `resume_input` dedup key is the check, inside a savepoint).
- `tests/e2e/conftest.py` gains `purge_conversation` beside `PURGE_ORDER`'s new statement: `purge_run` alone cannot
  delete a conversation that holds status or clarification messages.

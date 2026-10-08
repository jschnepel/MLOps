# Plan B final whole-branch review (2026-10-08)

Branch `plan-b`, range b98140f..8d086ce (Plan B tasks T05, T43, T44, the Plan A comment pass and the slice-end handoff docs), reviewed after each task passed its own gate. Outcome: 0 Critical, 3 Important, 7 Minor. The three Important findings and one minor were fixed in one wave (commits 837dd5b..fc513c5) and confirmed by a scoped re-review: the task-review 'redacted failure message' fix had not worked because pytest's assertion rewriting prints operands (now the tests assert on precomputed identifier lists, with proof tests that tamper a copy and check the literal never reaches the message); a raw carriage-return byte had crept into the Ollama runbook (now a repo-wide no-CR/no-BOM test); the handoff documents mis-stated the commit range and the remote state; the bootstrap password is stripped on read. Deferred: a live test that does not require Keycloak (plan-mandated), runbook and docstring polish.

The report below is the reviewer's text, unedited.

---

# Final whole-branch review: `plan-b` (b98140f..8d086ce, 13 commits)

Reviewer: one broad pass, done in passes by me alone (no subagents): ledger, infra files, tests, live tests and evidence, model pins and probe.py, runbooks, handoff docs, hygiene. Read-only: nothing in Docker was started, and no secret file contents were read. The only things written were scratch files outside the repo and this report.

Commands run (results quoted):
- `uv run python scripts/check.py` gave `89 passed, 11 skipped`, `CHECK: GREEN` (ruff, format and mypy clean).
- `python -I scripts/verify_handoff.py --reference-code --manifest`: all PASS. `git diff --name-only b98140f..8d086ce -- reference` is empty.
- `git log --format=%B b98140f..8d086ce | grep -i claude` printed nothing (exit 1). A wider grep for `co-authored|generated with|anthropic` also printed nothing.
- AST comparison (docstrings stripped) of all 20 pre-existing `.py` files touched by the range: every one is identical. The only "DIFF" is `scripts/__init__.py`, which went from empty to docstring-only. The comment pass is behaviour-neutral.
- Python byte scan of all 57 added or modified files at 8d086ce: no BOM, all valid UTF-8, and **one CR byte** (see I2). No added `.py` line is over 120 columns.
- Diff scan: 0 JWT shapes, 0 secret-like 43-character mixed tokens, 0 `password=`/`client_secret=`. All 10 `PASSWORD=` hits are variable names or `grep -c` commands. `.env` and the secrets directory are not tracked.
- Scratch pytest (outside the repo) to check whether pytest echoes values in assertion output even when a custom message is given: it does (see I1).

## Strengths

- **The secret paths are sound by construction.** Generation uses `O_CREAT|O_EXCL` with mode 0o600 and never overwrites. Secrets live outside the repo. Compose delivers them as `secrets:` files. The Keycloak entrypoint exports them only inside the container's process environment, and they reach the realm only as `${OPS_KC_*}` placeholders. Evidence holds only redacted claims. The in-network `iss` check mounts the secret read-only instead of passing it as an argument. I found no leak on any committed path.
- **`compose.yaml` is tight.** Both ports are on `127.0.0.1` behind `:?` guards. Both images are pinned by digest. There is no `internal: true` network and no privileged or root override. The healthcheck reads the HTTP status line rather than grepping a body, which also says "UP" when the service is down. `down` never passes `-v`.
- **The realm is least-privilege and statically pinned.** Each workload client has exact audiences, and the tests compare audiences exactly rather than with "contains". `ops-web` has one exact redirect and PKCE S256. The direct grant is limited to one public client marked dev-only. The view-users service account has exactly one client role. Persona IDs and roles match `data/seed-ids.json`, and I checked all five by hand.
- **`model_pins.py` is correct and well argued.** Strict JSON-mode validation, `AwareDatetime`, bare lowercase 64-hex digests, `extra=forbid`, and a single error type. The "exact probe.py output" test matches `probe.py:412-413` (indent 2, four keys, bare digest from `/api/tags`, `datetime.now(UTC).isoformat()`).
- **The live tests are honest.** They skip visibly (nine skips appear in every `check.py` run), compare exact status codes and audience sets, and keep tokens inside the test process.
- **The Ollama runbook is grounded in measurement.** It changes the primary control to a loopback bind based on the measured `127.0.0.1` source address, makes step B re-run safe (remove, then add), and gives a full-inverse rollback. Elevation is marked where needed, and nothing instructs the agent to change a system setting.
- **Cited facts check out.** I spot-checked seven against the repo: Docker Desktop 29.6.2, pgvector 0.8.7, `after restart: HTTP 400 (still absent)`, the `compose-ps.txt` command (plan review 3.6c), WSL adapter `172.28.32.1/20`, `.python-version` = 3.13, and `test_ci_workflow.py:28` pinning `contents: read`. All are traceable. The `exact=true` substring-match note agrees with the Keycloak Admin API documentation.

## Declined to judge

- `ops-worker` tokens carry both MCP audiences, so one token is valid at both MCP servers. AM-20.7 item 6 and the T05 review note ("one client, two handle types") mandate this.
- `sslRequired: none` and plain HTTP: this is the BUILD_SPEC §9 localhost-only exception, and it is dev profile only.
- A public password-grant client (`ops-dev-direct`): it is spec-sanctioned as a dev-only test client.
- Keycloak dev-mode storage is ephemeral with no volume. That is a plan Global Constraint, and the rotation procedure depends on it.
- `status`/`down` create secret files and `.env` on a fresh clone. This is documented in `main`'s docstring and harmless.
- `.env` is rewritten on every command, so hand edits are lost. The file is labelled as generated.
- `KC_BOOTSTRAP_ADMIN_PASSWORD` stays in Keycloak PID 1's environment after the account is deleted. It is visible only inside the container, and the account no longer exists.
- `/api/show` vs `/api/tags` as the digest source: this is a T19 concern, already recorded as T19's review note.
- No tenant attribute in Keycloak: BUILD_SPEC §9 says Keycloak is not the application role database.
- The prose of the plan and the plan-review record: these are records that were reviewed in three rounds. I checked only the facts that code and runbooks cite from them.
- The live suite not running in CI: ruling 2, a reasonable trade for a Docker-dependent dev profile.
- Mode bits being advisory on NTFS: covered by a ruling, and `%LOCALAPPDATA%` is per-user.
- The default realm roles the view-users service account may inherit (`default-roles-ops-dev`): these can only be checked live. The 403 tests cover the dangerous half.
- Lines over 120 characters in the realm JSON and in the compose healthcheck: there is no formatter for these, and wrapping would hurt readability.
- Service-account `sub` UUIDs in the evidence change on every import. They are not secret.

## Issues

### Critical (Must Fix)

None. No secret leak, no system-state change by the agent, no broken behaviour, no fabricated evidence, and no hash-pinned file modified (the reference verifier passes and `reference/` is untouched).

### Important (Should Fix)

**I1. The "redacted failure messages" fix does not work under pytest's assertion rewriting, so a leaked literal would still be printed.**
- **Where:** `tests/plan_b/test_realm_template.py:54` and `:57` (the comment at `:50-51` says the opposite); `tests/plan_b/test_evidence.py:36` and `:38`.
- **What's wrong:** Pytest's assertion introspection prints the evaluated sub-expressions even when an assertion has a custom message. I confirmed this with a scratch test:
  - `assert P.match(c["secret"]), ("cid", "secret")` printed `+ where None = <built-in method match ...>('SUPERSECRETVALUE123')`.
  - `assert v not in text, path` printed `assert 'SUPERSECRETVALUE456' not in '...'` plus "is contained here: ...".
  - `test_evidence.py:36` would likewise print the matched JWT.
- **Why it matters:**
  - This was a task-gate Important finding (T2) that the ledger records as fixed. The code comment, `docs/PROJECT_HISTORY.md` §17 and `SESSION_STATE.md` all claim the fix.
  - The tests exist to catch a leaked literal. When they fire, they copy the value into the terminal, the agent transcript or the CI log.
  - For `test_evidence`, the failing evidence file may still be uncommitted, so printing the value is new exposure.
- **How to fix:** Evaluate the condition before the assert, for example `leaked = v in text` then `assert not leaked, path`, or `ok = bool(PLACEHOLDER.match(...))` then `assert ok, (cid, "secret")`. Alternatively use `if ...: pytest.fail(msg, pytrace=False)`. Then add a meta-test with a fake literal that checks the failure text does not contain the value, and correct the comment and the §17 wording.

**I2. A literal CR byte was committed in the Ollama runbook.**
- **Where:** `docs/runbooks/ollama-network.md:53`.
- **What's wrong:** The re-measure command contains `tr -d '<0x0D>'`: a raw carriage return instead of the two characters `\r`. It was introduced in the fix round 8841305; 06bcec0 had 0 CRs. The ledger's "6 files no CR/BOM" check ran on 06bcec0 only.
- **Why it matters:**
  - It breaks the binding "LF only" constraint.
  - In a rendered view or after copy-paste the CR disappears and the command becomes `tr -d ''`, which silently leaves CRs in the PowerShell output that the step is meant to clean. This is exactly what Plan B's Global Constraints warn about.
- **How to fix:** Replace the byte with `\r`, as written in the plan. Consider a repo-wide test that no tracked text file contains `\r` or a BOM, which would have caught this and also protects `entrypoint.sh` (see m3).

**I3. The handoff docs contradict each other and the repository.**
- **Where:** `SESSION_STATE.md:5`, `:7`, `:~168`; `STATUS.md:94`.
- **What's wrong:**
  - `SESSION_STATE.md:5` gives the Plan B range as `a638801…8841305`. a638801 is Plan A's base; Plan B is `b98140f..8d086ce`. It also cites "plus the whole-branch review's fixes", which do not exist yet.
  - `SESSION_STATE.md:7` still says "Remote … **not created yet** … Nothing has been pushed". The parenthetical this range added near line 170 says `main`/`plan-a` were pushed on 2026-10-07, and `git branch -a` shows `origin/main` and `origin/plan-a`.
  - The same owner-input list still begins "`gh auth login`, then approval to push".
  - `STATUS.md`'s pending list still says "T06 push → first CI run URL" without saying that `main`/`plan-a` are already pushed.
- **Why it matters:** CLAUDE.md tells the next session to continue from `SESSION_STATE.md`. A fresh agent would believe nothing is pushed and could try to create the remote again or ask for `gh auth login`.
- **How to fix:**
  - Correct the range.
  - Rewrite the Repository line to match the actual state: remote exists, `main` and `plan-a` pushed, `plan-b` local.
  - Drop the stale `gh auth login` bullet, or mark it done.
  - Drop "plus the whole-branch review's fixes", or fill it in with real SHAs after the fix wave.

### Minor (Nice to Have)

**m1. A newline-mismatched secret file silently leaves `tmpadmin` in place.**
- **Where:** `scripts/bootstrap_dev.py:170` and `tests/plan_b/live/conftest.py:29`.
- **What's wrong:** The secret is read raw, but the entrypoint's `$(cat)` strips trailing newlines. If the owner writes a secret file by hand with a trailing newline, Keycloak gets the stripped value while the script sends the newline, gets a 400, and prints `bootstrap admin: absent`. The master admin is then left standing, and the live test passes for the same reason.
- **How to fix:** Use `.read_text(...).rstrip("\r\n")` in both places, matching the entrypoint. This narrows the ledger's deferred "400 also follows a wrong password" item to the rotation case it already documents.

**m2. `test_running_services_are_healthy` checks only postgres.**
- **Where:** `tests/plan_b/live/test_stack_up.py:6`.
- **What's wrong:** It asserts only `"postgres" in names`. `docker compose ps` without `-a` hides exited containers, so a crashed Keycloak passes both stack tests.
- **How to fix:** `assert {"postgres", "keycloak"} <= names`.

**m3. No static guard keeps `entrypoint.sh` free of CRLF.**
- **Where:** `deploy/dev/keycloak/entrypoint.sh`.
- **What's wrong:** A CRLF save turns `set -euo pipefail` into `invalid option name pipefail\r` and Keycloak crash-loops. `.gitattributes` (`* text=auto eol=lf`) protects clones but not an editor save.
- **How to fix:** Extend `test_file_is_lf_utf8_without_bom` (or the repo-wide test from I2) to cover `entrypoint.sh`, `01-init.sql` and `compose.yaml`.

**m4. `dev-topology.md` has scaffolding and accuracy slips.**
- **Where:** `docs/runbooks/dev-topology.md:14`, `:19-20`, `:27`, `:29`.
- **What's wrong:**
  - Plan-internal references ("Task 2 asserts it", "see Tasks 2–3 additions below") don't make sense to a reader of the repo.
  - The `psql` recipe's inline code span contains a raw line break. Both renderings work in bash, but the copyable text differs from the source.
  - "re-imported on every `up`" is true only after `down`; line 57 itself shows that a restart keeps the data.
- **How to fix:** Name the test instead of the task; put the recipe in a fenced `bash` block with `\n`; say "after `down`".
- **Note:** I checked the recipe itself and it is correct:
  - `printf` is a builtin, so the value never appears in a process list.
  - `grep ^OPS_SECRETS_DIR= .env | cut -d= -f2-` yields the forward-slash path.
  - The container name `ops-copilot-postgres-1` is right.
  - The image's local socket uses `trust`.
  - URL-safe values cannot break the single-quoted literal.

**m5. The evidence README overstates provenance.**
- **Where:** `reports/bootstrap/README.md:3`.
- **What's wrong:** It says all files were captured with the pytest command. `compose-ps.txt` (`docker compose ps --format ...`) and the `after restart` line came from separate plan steps (3.6c and 3.7).
- **How to fix:** Name both commands.

**m6. The Ollama runbook has two readability gaps.**
- **Where:** `docs/runbooks/ollama-network.md:18-28` and `:75-79`.
- **What's wrong:**
  - Two identical, unlabeled firewall tables look like a copy error. They are the outputs of the application-filter query and the display-name query.
  - Step A verification 2 needs `.env`. On a fresh clone the `env` fixture raises `FileNotFoundError`, which shows as an ERROR rather than `1 passed`.
- **How to fix:** Label the two tables, and add "after `uv run python scripts/bootstrap_dev.py secrets`" to verification 2.

**m7. Commenting-standard gaps.**
- **Where:** `tests/plan_b/test_compose_dev.py:16` (`load`), `tests/plan_b/test_model_pins.py:79` (`write`), `tests/plan_b/live/conftest.py:20,27,35` (fixtures `env`, `secret`, `compose_ps`), `compose.yaml:67`.
- **What's wrong:**
  - The listed helpers and fixtures have no docstrings, while `test_realm_template.py`'s helpers do. Fixtures are a shared interface.
  - `compose.yaml:67` says the image ships neither curl "nor wget". The plan's measured facts record only "no curl".
- **How to fix:** Add the docstrings, and either measure wget or drop it from the comment.

## Deferred-minor triage

**Rulings:**
- Ruling 1 (work on `plan-b` in this checkout): sound. No spec impact.
- Ruling 2 (live tests gated by `OPS_LIVE=1`; evidence committed): sound. The skips are visible. Note that I1 weakens the evidence guard's redaction, not its detection.
- Ruling 3 (T44 step 10 is owner-only): sound. AM-31 says "The agent does not change system settings", and nothing in the diff does or instructs the agent to.
- Ruling 4 (real project name, secrets dir and ports): sound. The stack is down, and evidence and tests use the real `.env`.
- Ruling 5 (comment standard applied on top of verbatim code): sound. The AST comparison shows the comment pass is behaviour-neutral.
- Ruling 6 (O_EXCL and 0o600; one POSIX-only test): sound. The total 89/11 matches.

**Deferred minors:**
- T1, 0o700 not applied to pre-existing or parent dirs: stays deferred. `%LOCALAPPDATA%` and `~/.local/share` are already user-private.
- T1, `.env`/`ENV_PATH` relative to the working directory: stays deferred. Compose resolves `.env` next to `compose.yaml`, so running from a subdirectory gives a confusing "run bootstrap first" loop. A one-line fix (`Path(__file__).resolve().parents[1] / ".env"`) is cheap and worth doing when the file is next touched.
- T2, KC_HOSTNAME and image-version facts live in the plan review, not in evidence: stays deferred. I verified they are traceable in `docs/reviews/plan-review-b-2026-10-08.md`.
- T3, `delete_bootstrap_admin` raises on 5xx, URLError or 404: stays deferred. Failing loudly is correct for a security cleanup.
- T3, a 400 also follows a wrong password: stays deferred for the rotation case, but fix the newline variant cheaply (m1).
- T3, DRY between the script and `kc.py`: stays deferred. The script cannot import tests.
- T3, the service account's default realm roles can only be verified live: stays deferred. The 403 tests cover the risk.
- T4, untyped test lambdas: stays deferred. They are outside mypy's scope.

## Recommendations

1. Fix I1 to I3 in one small wave. I1 needs a meta-test so the redaction claim is proven, not asserted. Add the repo-wide no-CR/no-BOM test (I2 and m3).
2. Take m1 and m2 in the same wave. Each is one line and closes a way for a test to pass trivially.
3. After the wave, re-run `check.py` (expect `90 passed, 11 skipped` or similar with the new tests). Re-scan bytes for CR and BOM over the fix commits too, not only the task commits.
4. Owner: T44 step 10 (runbook step A) remains the open security item. LAN exposure of 11434 continues until it is applied.

## Assessment

**Ready to merge?** With fixes

**Reasoning:** The branch delivers what the plan asked for, with sound secret handling, loopback-only bindings and honest tests, and there is no critical defect. Three cheap Important fixes should land first: a guard whose "redaction" fix is ineffective, a CR byte that breaks the LF constraint, and stale handoff state that would mislead the next session.

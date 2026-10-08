# Adversarial review of Plan B (dev bootstrap): rounds 1–2 (2026-10-08)

**Reviewed:** `docs/superpowers/plans/2026-10-08-first-slice-b-dev-bootstrap.md` (T05, T43, T44) before execution.

**Method:** the same gauntlet as round 8 of the spec reviews — one critic reads the plan against the spec and the vendors' documentation; a second critic executes every step on a throwaway worktree with real Docker, Keycloak and Ollama, under a separate Compose project name and a scratch secrets directory. The plan was fixed between rounds; round 2 re-reviewed the fixes and dry-ran the plan again. Each reviewer's report is reproduced below, unedited. The outcome and the fixes are summarised in `docs/PROJECT_HISTORY.md` §17.

**Round-1 verdicts:** static — 1 Blocking (the model-pins loader rejected the digest format the probe writes), 9 Important, 15 Minor; builder — EXECUTABLE WITH FIXES: 5 Blocking (ruff formatting on three tasks' code; Keycloak answers a deleted user's password grant with 400, not 401), 5 Misleading, 3 Risky; every Keycloak unknown (placeholder substitution, seeded IDs, identical `iss`, `view-users` scope, bootstrap-admin self-deletion) held.

**Round-2 builder verdict:** EXECUTABLE WITH FIXES — every revised step passed (placeholders, status-line probe, exact audiences, 400 handling, totals, lint), but one premise was wrong: a container's connection to `host.docker.internal:11434` reaches the host **from 127.0.0.1** (Docker Desktop proxies it), so the planned WSL-subnet firewall rule would admit nothing and a loopback bind is the right control. The runbook was rewritten around that measurement (loopback bind primary, firewall fallback, proposed AM-31 errata).

**Round-2 static verdict:** 20 of 25 round-1 findings addressed, 3 partially, 2 not; 0 Blocking, 2 Important (stale digest contract text; an over-claimed image pull), 11 Minor — all applied before execution.

---

## Round 1 — static critic (documentation cross-check, no execution)

# Plan B static review: `docs/superpowers/plans/2026-10-08-first-slice-b-dev-bootstrap.md`

Reviewer stance: every claim starts as UNPROVEN. **PROVEN** means I opened the evidence (an official doc page, a spec line or a repo file, or ran ruff/mypy/pydantic in a scratch copy of the plan's code); **DENOUNCED** means the claim is wrong, or nothing proves it, and the entry says what evidence would settle it. I ran no Docker and changed nothing in the repository. The only things I executed were these:
- ruff 0.16.10, mypy and pydantic, run from the repo's `.venv` against code blocks extracted from the plan into `scratchpad/planb-review/sim/`, which uses a copy of the repo's `pyproject.toml`;
- one read-only `GET http://127.0.0.1:11434/api/tags`.

Plan line numbers are `Lnnn`.

---

## Lens 1: spec compliance and coverage

| Claim / requirement | Verdict | Evidence |
|---|---|---|
| T05: Compose dev profile, PostgreSQL+pgvector with pinned major and digest | PROVEN (structure). See the digest caveat below. | L156 `pgvector/pgvector:pg17@sha256:…`; `test_images_are_pinned_by_digest` |
| Images pinned by digest that resolves on a clean clone | **DENOUNCED (unproven)** | L13 says the Keycloak digest was read from the *local cache*. If it is the local image ID (`docker inspect .Id`) instead of the RepoDigest, `image@sha256:<id>` cannot be pulled on a clean machine. Evidence needed: `docker inspect --format '{{index .RepoDigests 0}}'` for all three images, recorded in the plan. |
| Every published port binds to 127.0.0.1 (AM-31) | PROVEN (static and live design) | L159, L181; L86-89 static test; L494-499 live test |
| Management port 9000 is unpublished | PROVEN | L180-181: only 8080 is published |
| AM-70: no `internal: true` network with a published port | PROVEN | L230-232; L97-100 (stricter: no internal network at all) |
| `KC_HOSTNAME=http://localhost:<port>` + `KC_HOSTNAME_BACKCHANNEL_DYNAMIC=true` (T05) | PROVEN (config) | L183-184; T05 instructions |
| Realm import with secret placeholders | PROVEN (structure); see Lens 2a for semantics | L701 etc.; L623-629 |
| Workload clients + hardcoded-audience mappers with `MCP_READ/WRITE_RESOURCE_URL` parameters and `incident-sim` (AM-20.7 item 6) | PROVEN | L720-735 (worker), L767-775 (mcp-write → `incident-sim`). The `asset-sim` audience on `ops-mcp-read` (L747-755) is an extension. It is consistent with AM-20.7 item 6 ("asset-sim trusts only the mcp-read workload token") but no spec line asks for it. |
| "Workload tokens carry the **expected** aud" (T05 DoD) | **DENOUNCED (weak)** | L897 checks `set(aud) >= {…}` and L908 checks `expected in aud`, so the tests never detect an *extra* audience (for example `incident-sim` leaking into the mcp-read token, or MCP URLs on an mcp token). AM-20.7 item 6 / §9 "token audience confusion" is exactly that failure. Evidence needed: an exact-set assertion, with `account` allowed if Keycloak adds it. |
| `azp` asserted | PROVEN | L898, L908, L917 |
| `iss` identical from host and container (asserted) | PROVEN (test design) | L921-938 obtain a token in-network via `keycloak:8080` and compare it with the host's |
| `sub` equals the seeded Keycloak user ID | PROVEN (test design) | L912-918; Task 3 extends this to all five at L1196 |
| Dev-only direct-grant test client | PROVEN | L777-787; T05 instructions; r4 "Fix in task" T05 row |
| Two personas in T05, three more plus tenant beta in T43 | PROVEN | L789-814, L1102-1137; seed IDs match `data/seed-ids.json` (compared by eye: alex 2fc05986…, sam 03f7eb09…, lee abcc1200…, riley 2f73af91…, jordan cb551e64…) |
| Secrets under `%LOCALAPPDATA%\ops-copilot`, delivered by Compose `secrets:`, entrypoint wrapper exports from `/run/secrets` | PROVEN | L367-372, L209-225, L246-258 |
| Windows-friendly bootstrap script; "one command from a clean clone" | PROVEN (design) | L328-428; `uv run` syncs the editable workspace (`.venv/Lib/site-packages/_editable_impl_ops_core.pth`) |
| `docker compose ps` shows only 127.0.0.1 bindings | PROVEN (live test + evidence file) | L494-499, L1268 |
| No secret committed; none in `docker inspect` env | PROVEN (design + checks) | L19, L513, L988; secrets are files; `.env` is git-ignored (`.gitignore` line `.env`) |
| Topology document | PROVEN | L526-556, L1009-1024, L1287-1300, L1574-1584 |
| T43: view-users service account; "nothing more is granted" | PROVEN (static) / partial (live) | L1063-1070; L1230-1240 (PUT, POST users and GET clients give 403). Nothing checks DELETE user or role-mapping endpoints, but those need `manage-users`, so this is acceptable. |
| T43: "self-delete via admin REST with the bootstrap token; **verify on the cached 26.8.0 image first**" | **DENOUNCED (partly)** | The plan implements the deletion (L1158-1187) and only checks it afterwards (L1262-1266). It never runs the "verify first" spike, and L1263 states `bootstrap admin: deleted` as the expected output even though the behaviour has not been verified. |
| T43: documented rotation procedure | **DENOUNCED (wrong for one secret)** | L546 says "delete a file to rotate it, then down and up" for *every* secret. `postgres_password` is applied only by initdb on an empty volume (hub.docker.com/_/postgres: "scripts in /docker-entrypoint-initdb.d are only run if you start the container with a data directory that is empty"; POSTGRES_PASSWORD only at init). Rotating that file breaks password authentication for later TCP clients. |
| T43: memberships and tenants seeded by a migrator migration | Deferred, and the plan says so | L1608 (honest; the work moves to T08/T09) |
| T44: container route; host callers do not use `host.docker.internal` | PROVEN | L364, L1467-1477; T44 instructions |
| T44: runbook with exact commands and a verification step | PROVEN (present). Correctness is covered in Lens 4. | L1500-1569 |
| T44: worker reads `data/model-pins.json` (loader in core) | **DENOUNCED (incompatible with the real file)** | See Blocking B1 |
| AM-20.7 5(b): `view-users` secret generated by the bootstrap | PROVEN | L1150 |
| AM-20.7 5(c): sweeper uses the same account | Deferred (T11); stated at L1607 | — |
| §9: Keycloak is not the application role database | PROVEN (stated) | L24, L1021. Realm roles exist "for display and tests only". That is acceptable, but no test stops later code from reading `realm_access.roles`, so treat it as a T10 concern. |
| §9: **exact redirect allowlists** | **DENOUNCED** | L706 and L648 use `redirectUris: ["http://localhost:8000/*"]`, a wildcard, which contradicts BUILD_SPEC §9 "exact redirect allowlists". |
| §9: localhost-only HTTP exception for dev | PROVEN | `sslRequired: "none"` only in the `ops-dev` realm, dev profile |
| §21: non-root containers | Partly. **Minor**. | Keycloak runs as uid 1000 (L13, measured). The postgres image starts as root and drops privileges through gosu; `python:3.13-slim` runs as root. §21 speaks of "target containers" (ours), but the plan never says that third-party dev images are exempt. |
| §21: `down -v` consent | PROVEN | L26, L553; no script runs it |
| §21: "test egress" for Ollama | Not covered, and not flagged | §21 last paragraph. Not a T44 DoD item, so Minor. |
| §27: identity secrets generated outside git | PROVEN | L367-385 |
| §4: "generated temporary credentials" | Declined to judge | The persona credentials have `temporary: false` (L800). Keycloak's `temporary: true` would force a password reset and break the direct grant. I read §4's "temporary" as throwaway dev credentials. |

## Lens 2: Keycloak 26.8 facts

| # | Claim | Verdict | Evidence |
|---|---|---|---|
| a | `--import-realm` substitutes `${VAR}` from environment variables | PROVEN for the `${VAR}` syntax | keycloak.org/server/importExport shows `"${MY_REALM_NAME}"` as the placeholder form for env resolution. Default values (`${VAR:default}`) are documented only for `keycloak.conf` (keycloak.org/server/configuration), not for import; the plan uses none. `${env.VAR}` is not documented. |
| a' | Exporting the placeholders under **`KC_`** names is harmless | **DENOUNCED (unproven)** | keycloak.org/server/configuration: "Environment variables are converted back to normal option keys by lower-casing the name and replacing `_` with `-`." The entrypoint (L252-256) exports `KC_CLIENT_SECRET_OPS_WEB`, `KC_PERSONA_ALEX_PASSWORD` and the others, so they enter Keycloak's option namespace as unknown options (`client-secret-ops-web` …). Whether 26.8 warns, logs the key or rejects them is undocumented. Only `KC_BOOTSTRAP_ADMIN_PASSWORD` needs the `KC_` prefix. Fix: export the others as `OPS_KC_*` (and change the L594 regex to match). |
| b | Import skips an existing realm | PROVEN | importExport: "If a realm already exists in the server, the import operation is skipped." Plan L1260 is correct. |
| c | `KC_HOSTNAME` (full URL) + backchannel-dynamic yields one `iss` | PROVEN by repo evidence, not by docs | keycloak.org/server/hostname: backchannel-dynamic requires `hostname` as a full URL (met). The page does **not** state the iss behaviour. The proof is the r4 dry run (`docs/reviews/plan-review-r4-2026-10-06.md` "Evidence gathered") plus the plan's own live test L921. |
| d | `KC_HEALTH_ENABLED` exposes `/health/ready` on 9000; body contains `"status": "UP"` | PROVEN (port, path, body); **DENOUNCED (healthcheck logic)** | keycloak.org/observability/health: "exposed on the management port `9000` by default"; ready response shows `"status": "UP"`. It is a build-time option; `start-dev` auto-builds (not stated on the page; L979 would show it). The healthcheck at L202 greps the **body** for `"UP"`. A not-ready response is `{"status":"DOWN","checks":[{…,"status":"UP"},…]}`, so the grep can report healthy while the overall status is DOWN. The doc's own example greps the status line: `grep 'HTTP/1.0 200'`. |
| e | Bootstrap admin: created when / re-created / deletion | PROVEN in part | keycloak.org/server/bootstrap-admin-recovery: "created only during the initial start … when the master realm doesn't exist yet"; the account is "temporary" and "needs to be removed manually". So after deletion, `docker compose restart` keeps the dev H2 database inside the container layer and must **not** re-create it; `down`/`up` creates a new container and database and **will** re-create it. Self-deletion with the account's own token is **not documented** either way; T43 itself asks for it to be verified first. |
| f | uid 1000, bash entrypoint replacement | PROVEN (no objection) | keycloak.org/server/containers: custom entrypoints must `exec` the server as the last step. The plan does (L257). uid 1000 and the absence of curl are measured (L13), and the health page confirms curl is absent. |
| g1 | `oidc-audience-mapper` + `included.custom.audience` | PROVEN only by Keycloak's export format convention (no doc page opened shows it) | Least-certain item; the L897/L908 live tests would catch an error. |
| g2 | User `id` honoured on import | **UNPROVEN** | The docs do not say. The live test L916 catches a failure. |
| g3 | `serviceAccountClientId` + `clientRoles.realm-management` user in import JSON | **UNPROVEN** | Undocumented. It depends on Keycloak creating `realm-management` before user import and skipping its own auto-created SA user. L1063 is static only; the L1237 live GET would catch a failure. |
| g4 | `attributes.pkce.code.challenge.method`, `sslRequired:"none"`, `directAccessGrantsEnabled` on a public client, `accessTokenLifespan` | Standard representation fields; no doc page opened | Not live-tested for `ops-web` (no code-flow test in Plan B). |
| g5 | The `tenant` user attribute survives import and is visible | **DENOUNCED (unproven)** | Keycloak 24+ always enables user profile, and unmanaged attributes are disabled by default. `tenant` (L798) may be dropped or hidden from the admin API. The plan never reads it live, so this does not fail, but L24/L1021 rely on it "for display and tests". |
| h | `view-users` alone: GET user 200; PUT/POST user and GET clients give 403 | **UNPROVEN** | No doc states the status codes. GET `/clients` with only `view-users` could plausibly return 200 with a filtered (empty) list instead of 403 (behaviour depends on version and admin-permissions version). The live test L1239 asserts 403, so an executor may hit an unexpected failure. |

## Lens 3: Docker Compose facts

| Claim | Verdict | Evidence |
|---|---|---|
| Top-level `name:` sets the project | PROVEN (Compose spec `name` attribute; container names `ops-copilot-*-1` follow) | — |
| `secrets: file:` with `${OPS_SECRETS_DIR}` interpolated from root `.env` | PROVEN (`.env` in the project dir is the default interpolation source; `file:` "The secret is created with the contents of the file", docs.docker.com/reference/compose-file/secrets) | Windows `C:/…` forward-slash paths: accepted by Docker Desktop (no doc page opened; the live run would fail loudly). |
| `.env` absent → `${PG_PORT}` empty → `127.0.0.1::5432` | **Minor** | No `${PG_PORT:?run bootstrap_dev.py secrets}` guard; the error message would be confusing. |
| `profiles`, `up --wait --wait-timeout` | PROVEN (documented flags) | — |
| `ps --format json` is JSON Lines with `Publishers[].URL/PublishedPort` | PROVEN | docs.docker.com/reference/cli/docker/compose/ps: "JSON Lines (one JSON object per line)", with example `"Publishers":[{"URL":"0.0.0.0","TargetPort":80,"PublishedPort":8080,…}]`. The L496 filter correctly drops `PublishedPort: 0` (EXPOSEd ports). |
| Healthcheck `CMD` with `\\r\\n` in YAML double quotes | PROVEN | YAML yields the literal `\r\n` and `printf` interprets it; `'\"UP\"'` → `'"UP"'`; no `$`, so no Compose interpolation. The logic flaw is under 2d. |
| `host.docker.internal` resolves in plain `docker run` on Docker Desktop | PROVEN by repo evidence | r4: "The `host.docker.internal:11434` bridge works from containers." |
| postgres image honours `POSTGRES_PASSWORD_FILE`; initdb.d only on an empty volume | PROVEN | hub.docker.com/_/postgres (quoted above). pg17 PGDATA `/var/lib/postgresql/data` matches L167 (the same page: 18+ changes it). |
| Rotation consequence for `postgres_password` documented | **DENOUNCED** | L546 says the opposite. |
| `CREATE DATABASE` in a `.sql` initdb file | PROVEN-ish | The entrypoint runs psql without `--single-transaction`, so CREATE DATABASE is allowed. |
| Dev Keycloak "ephemeral, no volume" | PROVEN in substance | L198-200: no data volume. "Every `up` after a `down` re-imports" is true because `down` removes containers. A bare `docker compose up` on a running stack does **not** re-import and does **not** delete the admin. Only the script deletes it (L1182), and L1299 implies more than that. |

## Lens 4: Windows Firewall and network

| Claim | Verdict | Evidence |
|---|---|---|
| A block rule wins over an allow rule, so adding none is right | PROVEN | learn.microsoft.com/…/windows-firewall/rules: "Explicit block rules take precedence over any conflicting allow rules." |
| Disabling the Ollama rules + one scoped allow = "loopback + subnet only" | PROVEN *if* the default inbound action is Block and the firewall is on for the active profile | The same page: "Explicitly defined allow rules take precedence over the default block setting"; default inbound is block. The runbook never **checks** this (`Get-NetFirewallProfile | ft Name,Enabled,DefaultInboundAction`). If the owner disabled the firewall on one profile, the restriction does nothing. |
| The "installer" created the allow rules | **DENOUNCED (wording)** | The rules page says the first-listen *prompt* creates the rules ("Two rules are typically created, one each for TCP and UDP"; answering No creates **block** rules). Disabling every `*ollama*` rule covers both cases, so only the wording is wrong. |
| `Program -like '*ollama*'` matches | PROVEN in practice (PowerShell `-like` is case-insensitive, and the plan measured rules on 2026-10-07, L1493). It also matches `ollama app.exe` rules; disabling those is harmless. Port-based rules not tied to the program are missed; add `Get-NetFirewallRule -DisplayName '*ollama*'`. | — |
| Loopback bypasses the firewall | Declined (no MS page opened states it). Listing `127.0.0.1` in the rule is harmless either way. | — |
| Docker Desktop → host LAN IP arrives with a source in the WSL subnet | **DENOUNCED (unmeasured)** | The plan measured the adapter address (L13) but never the **remote address Ollama actually sees** for a container connection. Docker Desktop can also proxy host-bound traffic through its own backend (source loopback or another subnet), which would make the runbook's scope wrong in either direction, and its "Why not bind to 127.0.0.1" paragraph (L1517) unproven. Evidence needed: during a long container request, `Get-NetTCPConnection -LocalPort 11434 -State Established | ft RemoteAddress`. The runbook's verification step 2 would catch a failure *after* the owner applies it, with no fallback. |
| Hyper-V firewall is irrelevant | PROVEN in principle | learn.microsoft.com/…/hyper-v-firewall: it filters traffic "to/from containers hosted by Windows, including WSL", with `DefaultOutboundAction` per VMCreatorId `{40E0AC32-…}`. WSL→host is *outbound* from the VM and allowed by default. The runbook should record `Get-NetFirewallHyperVVMSetting -PolicyStore ActiveStore -Name '{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}'` so a non-default outbound Block is visible. **Minor.** |
| The WSL subnet can change at reboot | Not proven by an MS doc I opened; the plan hedges it (L1519). There is no documented `.wslconfig` key that fixes the NAT subnet. **Minor:** a subnet change makes containers fail closed (not insecure). Suggest a `bootstrap_dev.py status` check that compares the current subnet with the rule's RemoteAddress. |

## Lens 5: security and secrets

| Path | Verdict |
|---|---|
| Secret in git | PROVEN safe: secrets live outside the repo (`test_default_secrets_dir_is_outside_repo`); `.env` is ignored; the realm JSON holds placeholders (static test). |
| Secret in `docker inspect` | PROVEN safe by design: env carries only `_FILE` paths and the username; the entrypoint exports at process level; L513 and L988 check. |
| Secret in pytest messages | PROVEN safe: assertion messages carry names and paths only (L290, L971). `secret(...)` values are never compared in an assert. Default `--tb` without `-l` shows no locals. `CalledProcessError` shows the mount *path*, not the value. |
| Secret in Keycloak logs | UNPROVEN: unknown `KC_*` options (2a') could be echoed by a warning. |
| `test_evidence_has_no_token_shapes` in CI | Runs, but **weakly**. On ubuntu CI `LOCALAPPDATA` is unset, so `secrets_dir` = relative `ops-copilot/secrets` (missing) and `values=[]`; only the JWT regex runs. Locally it also ignores an `OPS_SECRETS_DIR` set only in `.env`. It duplicates `bootstrap_dev.secrets_dir()` instead of importing it. **Minor.** |
| `ops-dev-direct` public password-grant client | Acceptable: T05 explicitly asks for "a dev-only direct-grant test client". Nothing enforces "never deployed outside dev" (L780). **Minor.** |
| Persona emails `*.example` | No objection (`.example` is a reserved TLD; §4 needs only fictional tenants). |
| Evidence README omits `typ` | Minor. |

## Lens 6: test design and toolchain

Measured with ruff 0.16.10 from the repo `.venv` on the extracted plan code, using the repo `pyproject.toml`:

| File (plan block) | Result |
|---|---|
| `tests/plan_b/live/kc.py` (L827) | **ruff check RUF100**: unused `# noqa: S310` (S310 is not enabled; the plan's L28 says itself that urlopen is not flagged). **ruff format**: L852 would be reformatted. |
| `tests/plan_b/live/test_keycloak_tokens.py` (L871) | **format**: L905 and L933-936 (the magic trailing comma plus a 152-character list). |
| `tests/plan_b/test_evidence.py` (L951) | **format**: L964 (131 characters). |
| `tests/plan_b/live/test_service_account.py` (L1200) | **format**: L1232, L1234, L1246. |
| `tests/plan_b/test_model_pins.py` (L1334) | **ruff check I001**: ruff classifies `ops_core` (under `core/src`, not in ruff's default `src`) as third-party, so the blank line between `import pytest` and `from ops_core…` is an unsorted block. |
| `tests/plan_b/live/test_ollama_bridge.py` (L1456) | **format**: L1475. |
| `core/src/ops_core/model_pins.py` | `mypy --strict`: **Success**. |
| `scripts/bootstrap_dev.py` (Task 1 form) | ruff clean; `mypy --strict` clean (scripts are not in check.py's mypy set anyway). |

As a result, check.py prints **CHECK: RED** at Task 2 Step 8 (L1005), Task 3 Step 9 (L1306) and Task 4 Step 8 (L1587), not the GREEN those steps state.

Pytest arithmetic (Plan A: 55 collected = 54 passed + 1 skipped, confirmed with `pytest --co`):

| Point | Plan says | Computed | Verdict |
|---|---|---|---|
| T1 S13 | 66 passed / 3 skipped | 54+8+4 = 66; 1+2 = 3 | PROVEN |
| T2 S7 live | 6 passed | 2+4 | PROVEN |
| T2 S8 | 74 / 7 | 66+7+1; 3+4 | PROVEN |
| T3 S1 | 3 failed | test_realm_users (KeyError lee), view_users, secret_names | PROVEN |
| T3 S4 | 21 passed | realm 8 + bootstrap 5 + compose 8 | PROVEN |
| T3 S6 live | 8 passed | 2+4+2 | PROVEN |
| T3 S9 | 76 / 9 | 74+2; 7+2 | PROVEN |
| T4 S4 | 9 passed | 1+1+6+1 | PROVEN |
| T4 S8 | 85 / 10 | PROVEN |
| T2 S7: "five lines" in keycloak-claims.txt | **DENOUNCED** | worker 1 + mcp 2 + personas 2 + iss 1 = **6** lines (9 after Task 3). |

Behaviour versus structure:
- Static tests (`test_compose_dev`, `test_realm_template`) are structural, which is appropriate here.
- `test_every_live_binding_is_loopback` passes **vacuously** when `compose_ps` is empty (stack down). Its sibling would fail, but the test should assert `compose_ps` is non-empty itself.
- `test_evidence_has_no_token_shapes` passes vacuously when `reports/bootstrap/` is missing (L962-963).
- `test_compose_environment_carries_no_secret` only catches keys named `*PASSWORD*`/`*SECRET*`. A secret under another key name passes. Acceptable alongside the `docker inspect` greps.
- `test_bootstrap_admin_is_absent` writes the evidence file with `write_text` (L1255). Task 3 Step 7 asks the executor to *append* the restart line, then possibly re-run that test, which **overwrites** the appended line.
- Live tests skip without `OPS_LIVE=1` and pytest `-ra` lists the skip reason in check.py output, so the skip is honest. CI never exercises them, and the plan says so (L29).
- Imports: `from tests.plan_b.live import kc` works only because `python -m pytest` puts the cwd on `sys.path` (there is no `tests/__init__.py`). A bare `pytest` would fail. The plan always uses `-m`, so this is Minor.
- Model pins: `probed_at: 1700000000` (an int) is **accepted** (pydantic lax mode; I measured it), and so is `model: " "`. Minor.

## Lens 7: plan hygiene

- **Nested code fences**:
  - Problem: L1501-1569 opens a ```` ```markdown ```` block that contains ```` ``` ```` and ```` ```powershell ```` fences. The outer block closes at L1511, so the rendered plan and any copy-paste executor see a broken runbook.
  - Fix: use a four-backtick outer fence.
- **Expected outcomes the author could not know**:
  - L1263 `bootstrap admin: deleted`: self-delete has not been verified (T43 asks for that first).
  - L980 lists log lines (hedged).
  - L1005/L1306/L1587 claim `CHECK: GREEN` (false; see Lens 6).
  - L986 says "five lines" (false).
- **Fill-in placeholders**: `<paste the table…>` (L1512) and `<the line recorded in step 7>` (L1299) are explicit, which is fine. No step makes sure they were filled before the commit; add a `grep -n '<paste\|<the line' docs/runbooks` check before each commit.
- **Task 3 Step 3 imports**: "add: import json …" (L1152-1155) is shown as a separate block. An executor may paste it mid-file, which gives E402/I001. Say "merge into the top import block, sorted".
- **Interfaces drift**: L51 names the parameter `dir`; the code uses `directory`. Trivial.
- **`main()` side effects**: `down` and `status` also generate secrets and rewrite `.env` (L413-417). Surprising, and harmless.
- **`git add` lists versus created files**: they match for all four tasks (checked L564, L1032, L1312, L1592).
- **Task 1 Step 15**: the expected `Network ops-dev-net Removed` holds because the network has an explicit `name:`.

---

## Consolidated findings

### Blocking

**B1. The model-pins loader rejects the real pins file** (L1328, L1422, the test at L1372 `no-prefix`).
- Problem: T02's `scripts/probe.py` `model_digest()` writes the digest from `/api/tags` verbatim, and Ollama returns it **without** a `sha256:` prefix. I read it live: `"digest":"500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41"`. `Field(pattern=r"^sha256:[0-9a-f]{64}$")` therefore raises `ModelPinsError` on the file T02 will produce, and the "no-prefix" test enshrines that rejection. T19 would fail closed for good.
- Fix: accept a bare 64-hex digest (`^(sha256:)?[0-9a-f]{64}$`, normalised to one form). Change the `GOOD` fixture to the bare form and drop or invert the `no-prefix` case. Add a test that round-trips the exact dict `probe.py` writes. Record the format decision for T45's `model-pins.schema.json`.

### Important

**I1. The lint and format gate goes RED** (L842, L852, L905, L933-936, L964, L1232-1246, L1336-1341, L1475).
- Problem: RUF100 (unused `noqa: S310`), I001 in `test_model_pins.py`, and `ruff format` reflow in 5 files. The `CHECK: GREEN` expectations at L1005, L1306 and L1587 are false.
- Fix: remove the noqa, remove the blank line before `from ops_core…`, and paste ruff-formatted code (or add a `ruff format` step before each check).

**I2. Keycloak healthcheck false positive** (L202).
- Problem: it greps the body for `"UP"`. A DOWN readiness body still contains per-check `"status": "UP"`, so `--wait` may return before the realm import completes, and `delete_bootstrap_admin` then races.
- Fix: check the status line, as keycloak.org/observability/health does: `printf 'GET /health/ready HTTP/1.0\r\n\r\n' >&3 && head -1 <&3 | grep -q ' 200'`.

**I3. Wrong rotation instruction for `postgres_password`** (L546; also implied at L1299).
- Problem: initdb applies the password only on an empty volume (hub.docker.com/_/postgres).
- Fix: document that `postgres_password` rotation needs `ALTER ROLE ops PASSWORD …` (run inside the container from the new file) or a deliberate owner-run `down -v`. Rotation of the Keycloak secrets is as stated.

**I4. Audience assertions are not exact** (L897, L908).
- Problem: extra audiences, the token-confusion case of AM-20.7 item 6 and §9, go undetected.
- Fix: assert `set(aud) - {"account"} == {expected…}` per client, and add a negative check (the mcp-read token lacks `incident-sim`; the worker token lacks both sim audiences).

**I5. Wildcard redirect URI for `ops-web`** (L648, L706).
- Problem: it contradicts BUILD_SPEC §9 "exact redirect allowlists".
- Fix: register the exact callback T10 will use (for example `http://localhost:8000/auth/callback`) and the exact post-logout URI, and test equality. Alternatively, leave `ops-web` to T10.

**I6. The firewall runbook rests on an unmeasured source address** (L1517, L1526-1535; Task 4 Step 6 at L1495).
- Problem: the plan never measures the remote address Ollama sees for a container connection, and never checks that the default inbound action is Block and the firewall is enabled per profile.
- Fix:
  - In Step 6, record `Get-NetTCPConnection -LocalPort 11434 | ft RemoteAddress,State` during a container request, and `Get-NetFirewallProfile | ft Name,Enabled,DefaultInboundAction`.
  - Add the profile check and the Hyper-V VM setting readout to runbook Step 3.
  - Give a fallback if the measured source is not in the WSL subnet.
  - Reword "installer created" to "the first-run firewall prompt created", and also list rules by `-DisplayName '*ollama*'`.

**I7. Placeholder variables share Keycloak's option namespace** (L250-256, L594, L701, L800 etc.).
- Problem: Keycloak maps every `KC_*` env var to an option (keycloak.org/server/configuration), and how 26.8 treats unknown options is undocumented.
- Fix: export only `KC_BOOTSTRAP_ADMIN_PASSWORD` under `KC_`. Export the rest as `OPS_KC_*`, use `${OPS_KC_…}` placeholders, and update the L594 regex. Alternatively, keep the names and add a Task 2 step that greps `docker logs` for `client-secret|persona` warnings and records the result.

**I8. T43's "verify on the cached image first" is skipped, and its outcome is asserted** (L1158-1187, L1263).
- Fix: before Step 3, add a throwaway spike: start Keycloak, delete tmpadmin with its own token, record the HTTP codes. Make L1263 conditional on that result.

**I9. Image digests are unproven as pullable RepoDigests** (L13, L18).
- Fix: record `docker inspect --format '{{index .RepoDigests 0}}'` output for all three images in the plan, and add `docker pull <ref@digest>` as a Task 1 step.

### Minor

- **M1 (L1255, L1283):** the evidence file is overwritten by a re-run. Use append mode, or append the restart line after any re-run.
- **M2 (L986):** "five lines" should be six (nine after Task 3).
- **M3 (L1501-1569):** nested fences; use a four-backtick outer fence.
- **M4 (L494-499):** add `assert compose_ps` so the loopback test is not vacuous.
- **M5 (L960-971):** import `secrets_dir()` from `bootstrap_dev`, and also read `OPS_SECRETS_DIR` from `.env`. The evidence test then checks the right directory, and in CI it is explicitly JWT-only.
- **M6 (L798, L24):** the `tenant` attribute may be dropped or hidden by Keycloak's user profile (unmanaged attributes are off by default). Either enable unmanaged attributes in the realm's user-profile component, or say that `tenant` is file-only.
- **M7 (L1152):** say "merge into the sorted top import block".
- **M8 (L1424):** use `strict=True` on `probed_at` (an epoch int is accepted today), and strip/validate `model` (`" "` is accepted).
- **M9 (L159, L181):** use `${PG_PORT:?run scripts/bootstrap_dev.py secrets}` guards for a clearer clean-clone error.
- **M10 (§21):** state that the third-party dev images (postgres entry as root, python helper) are outside "target container is non-root", or add `user:` where supported.
- **M11 (§21):** egress test for Ollama is not covered; note it in Coverage notes.
- **M12 (L1182, L1299):** state that a bare `docker compose up` (not the script) leaves tmpadmin in place.
- **M13 (L1533):** consider `-Program <ollama.exe path>` on the scoped allow rule, and a `status` check that warns when the WSL subnet no longer matches the rule.
- **M14 (L878, L1209):** `from tests.plan_b.live import kc` depends on `python -m pytest`. Add `tests/__init__.py`, or note the constraint.
- **M15 (L999):** the evidence README omits `typ`.

## Declined to judge

- **The Keycloak `iss` equality mechanism:** the hostname docs do not state it. I accept the r4 dry-run evidence plus the plan's live test, but I did not re-verify it.
- **Status codes and endpoint permissions** (401 for a deleted user's password grant; `view-users` → 403 on GET `/clients`; self-delete permitted): I found no official doc page. They are listed as unproven, and the parallel dry-run is the right place to settle them.
- **Whether `start-dev` applies the build-time `health-enabled`:** not stated on the page I opened; the dry run will show it.
- **Loopback exemption in Windows Firewall, and WSL subnet stability across reboots:** not confirmed by an MS page I opened. Both are harmless to the runbook's correctness as written.
- **§4 "temporary credentials":** I read it as throwaway dev credentials, not Keycloak's `temporary` flag.
- **Docker Compose v5.3.1 / Docker Desktop 29.6.2 version claims and the measured facts at L13:** environment measurements; the parallel dry-run reviewer will settle them.

---

## Round 1 — builder dry-run on a scratch worktree with real Docker

# Plan B dry run — adversarial BUILDER report

Plan: `docs/superpowers/plans/2026-10-08-first-slice-b-dev-bootstrap.md` (untracked in the real repo; copied to `planb-review/plan.md`).
Run: 2026-10-07 23:58 – 2026-10-08 00:10 (MST), on a scratch worktree at `plan-a` HEAD `b98140f`, Docker 29.6.2 / Compose v5.3.1, Keycloak 26.8.0 image cached, Ollama 0.33.3 on host.

Isolation notes:
- `git worktree add <scratch> plan-a` fails (`fatal: 'plan-a' is already used by worktree at 'C:/Users/joeys/Desktop/MLOps'`); used `git worktree add --detach <scratch> plan-a` (same commit). Not a plan defect.
- `COMPOSE_PROJECT_NAME=ops-copilot-dryrun` was exported for every Compose command, so every `ops-copilot-<svc>-1` in the plan's Expected lines appeared as `ops-copilot-dryrun-<svc>-1`. That is a dry-run artifact, and the table below treats it as a match.
- `OPS_SECRETS_DIR=/c/Users/.../scratchpad/planb-secrets` (Git Bash form) was exported. **No Git Bash path problem:** MSYS converts the variable for native processes, so `write_env` wrote `OPS_SECRETS_DIR=C:/Users/joeys/AppData/Local/Temp/.../planb-secrets` (forward slashes). Compose resolved the secret files from both the shell variable and `.env` alone (`env -u OPS_SECRETS_DIR docker compose config` → `file: C:/Users/.../planb-secrets/<name>`). No workaround was needed.
- Plan file content was extracted mechanically from the plan's fenced blocks (exact bytes, LF). Where the plan says "replace/append/extend", I applied the smallest literal edit.
- Baseline before Task 1: `uv sync --locked` took 3.4 s, and `check.py` gave `54 passed, 1 skipped`, `CHECK: GREEN`.

## Execution log

| Task.Step | Command / action | Actual | Expected | Verdict |
|---|---|---|---|---|
| 1.1 | create `tests/plan_b{,/live}/__init__.py`, edit `testpaths` | done | — | PROVEN |
| 1.3 | pytest test_compose_dev (RED) | `8 failed`, all `FileNotFoundError` | `8 failed`, FileNotFoundError | PROVEN |
| 1.6 | pytest test_compose_dev | `8 passed` | `8 passed` | PROVEN |
| 1.8 | pytest test_bootstrap_dev (RED) | `ImportError: cannot import name 'bootstrap_dev' from 'scripts'`; `1 error in 0.45s` | same | PROVEN |
| 1.10 | pytest test_bootstrap_dev | `4 passed` (OPS_SECRETS_DIR unset) | `4 passed` | PROVEN (see R1) |
| 1.12a | `bootstrap_dev.py secrets && compose up --wait postgres` | `secrets: 8 created, 0 kept, in C:\...\planb-secrets`, `.env written: ...`; tail ends `Container ops-copilot-dryrun-postgres-1 Healthy`. pgvector pull + up took 16 s in total | same | PROVEN |
| 1.12b | live test_stack_up | `2 passed` | `2 passed` | PROVEN |
| 1.12c | `ps --format "{{.Service}} {{.Ports}}"` | `postgres 127.0.0.1:15432->5432/tcp` | same | PROVEN |
| 1.12d | `docker inspect ... grep -c POSTGRES_PASSWORD=` | `0` | `0` | PROVEN |
| 1.12e | psql extension / database | `vector`, `incident` | same | PROVEN |
| 1.13 | `check.py` | `66 passed, 3 skipped`, `CHECK: GREEN`; ruff check clean; `75 files already formatted` | `66 passed`, `3 skipped`, GREEN | PROVEN (OPS_SECRETS_DIR unset; see R1) |
| 1.14 | create dev-topology.md | done | — | PROVEN |
| 1.15 | `compose down | tail -2` | ` Network ops-dev-net Removing` / ` Network ops-dev-net Removed` | `Container ops-copilot-postgres-1 Removed` and `Network ops-dev-net Removed` | **Misleading (M1)** |
| 1.15 | `git add …; git status --short` | exactly the 12 listed paths (11 A + `M pyproject.toml`); `.env` absent (it shows only under `--ignored`) | only those files | PROVEN |
| 2.2 | pytest test_realm_template (RED) | `7 failed`, 7× FileNotFoundError | same | PROVEN |
| 2.4 | pytest test_realm_template | `7 passed` | same | PROVEN |
| 2.7a | `rm -f …; bootstrap_dev.py up | tail -4` | rc 0; the last two lines are `Container ops-copilot-dryrun-postgres-1 Healthy`, `Container ops-copilot-dryrun-keycloak-1 Healthy`. Wall clock was 27 s (00:00:03→00:00:30) | two Healthy lines (30–90 s) | PROVEN |
| 2.7b | docker logs grep | `Realm 'ops-dev' imported`; `KC-SERVICES0077: Created temporary admin user with username tmpadmin`; `… started in 13.657s. Listening on: http://0.0.0.0:8080. Management interface listening on http://0.0.0.0:9000.` | import line + Listening line | PROVEN |
| 2.7c | live tests/plan_b/live | `6 passed in 19.32s` (included pulling `python:3.13-slim`, which was not cached) | `6 passed` | PROVEN (see R2) |
| 2.7d | `cat keycloak-claims.txt` | **6** lines: ops-worker, ops-mcp-read, ops-mcp-write, persona alex, persona sam, `iss host vs container`. Keys are as stated and there is no `eyJ` | "five lines" | **Misleading (M2)** |
| 2.7e | `docker inspect keycloak … grep -c "PASSWORD=\|SECRET="` | `0` | `0` | PROVEN |
| 2.8 | `check.py` | `74 passed, 7 skipped`, **`CHECK: RED`**: `RUF100 Unused noqa directive (non-enabled: S310)` at `tests/plan_b/live/kc.py:16`, and `3 files would be reformatted` (`tests/plan_b/live/kc.py`, `tests/plan_b/live/test_keycloak_tokens.py`, `tests/plan_b/test_evidence.py`) | `74 passed`, `7 skipped`, GREEN | **Blocking (B1)**. Workaround W1 → GREEN |
| 2.9 | append realm section | done (I added one blank separator line) | — | PROVEN |
| 2.10 | `compose down | tail -1` | ` Network ops-dev-net Removed` | same | PROVEN |
| 2.10 | git add / status | exactly the plan's paths (8 entries); no `.env` | only those paths | PROVEN |
| 3.1 | extend tests, run (RED) | `3 failed, 10 passed`: the three named tests | `3 failed` (those three) | PROVEN |
| 3.2 | append client/users to realm JSON | done. The fragments carry no separating comma, so the engineer must add `,` (M4) | — | PROVEN |
| 3.3 | compose + bootstrap edits | done. The import block must be merged into the existing sorted block (shown standalone). The `main` snippet is shown at 8-space indent but sits inside `if rc == 0:` (12 spaces) (M4) | — | PROVEN with ambiguity |
| 3.4 | pytest 3 static files | `21 passed` | `21 passed` | PROVEN |
| 3.5 | persona loop + test_service_account.py | done | — | PROVEN |
| 3.6a | `down && rm && bootstrap_dev.py up | tail -3` | `secrets: 4 created, 8 kept`; tail: `…postgres-1 Healthy`, `…keycloak-1 Healthy`, `bootstrap admin: deleted`. 34 s | keycloak Healthy, then `bootstrap admin: deleted` | PROVEN |
| 3.6b | live tests | **`1 failed, 7 passed`**: `test_bootstrap_admin_is_absent` → `assert 400 == 401`. Keycloak 26.8 answers `400 {"error":"invalid_grant","error_description":"Invalid user credentials"}` (log: `LOGIN_ERROR … error="user_not_found"`), and the same 400 for a wrong password or an unknown user. `bootstrap-admin.txt` was not written | `8 passed` | **Blocking (B2)**. Workaround W2 → `8 passed` |
| 3.6c | `ps --format … | tee compose-ps.txt` | `keycloak 127.0.0.1:18080->8080/tcp`, `postgres 127.0.0.1:15432->5432/tcp`, LF | two lines | PROVEN |
| 3.6/3.7 | second `bootstrap_dev.py up` while admin already deleted | **Traceback `urllib.error.HTTPError: HTTP Error 400: Bad Request`, rc=1**. `delete_bootstrap_admin` maps only 401 to "absent", so `up` is not idempotent | `up` re-runnable (step 7 tells you to re-run it) | **Blocking (B3)**. With W2: `bootstrap admin: absent` |
| 3.7 | restart + up --wait + probe | `after restart: HTTP 400 (still absent)`. The container restart kept dev data (log: `Realm 'ops-dev' already exists. Import skipped`, no `Created temporary admin`). Restart→healthy 15 s | exactly `…HTTP 200 (re-created)` or `…HTTP 401 (still absent)` | **Misleading (M3)**, a consequence of B2 |
| 3.8 | append the persona/admin section, substituting the line | done | — | PROVEN |
| 3.9a | `check.py` | `76 passed, 9 skipped`, **`CHECK: RED`**: `1 file would be reformatted`, `tests/plan_b/live/test_service_account.py` | `76 passed`, `9 skipped`, GREEN | **Blocking (B4)**. W1-style format → GREEN |
| 3.9b | `compose down | tail -1` | ` Network ops-dev-net Removed` | same | PROVEN |
| 3.9c | git add / status | exactly the plan's paths (11 entries); no `.env` | only those paths | PROVEN |
| 4.2 | pytest test_model_pins (RED) | `ModuleNotFoundError: No module named 'ops_core.model_pins'`; `1 error` | same | PROVEN |
| 4.4 | pytest test_model_pins | `9 passed` | `9 passed` | PROVEN |
| 4.4+ | `uv run python -m mypy core/src` | `Success: no issues found in 2 source files` | strict clean | PROVEN |
| 4.5 | live test_ollama_bridge | `1 passed in 1.28s`; evidence lines are `host http://127.0.0.1:11434/api/version -> 0.33.3` and `container http://host.docker.internal:11434/api/version -> 0.33.3` | `1 passed`, two lines ending 0.33.3 | PROVEN |
| 4.6a | firewall rules (read-only) | two rows: `ollama.exe True Inbound Allow Private, Public` | allow-inbound Public+Private | PROVEN |
| 4.6b | WSL adapter (read-only) | `vEthernet (WSL (Hyper-V firewall)) 172.28.32.1 20` | same | PROVEN |
| 4.7 | write ollama-network.md | written. The plan wraps it in a ```` ```markdown ```` fence that contains 10 inner ```` ``` ```` fences, so in rendered Markdown the outer block ends at the first inner fence and the boundaries are ambiguous. I took everything up to the fence before "Then paste…" | — | **Misleading (M5)** |
| 4.8 | `check.py` | `85 passed, 10 skipped`, **`CHECK: RED`**: `I001 Import block is un-sorted` at `tests/plan_b/test_model_pins.py:3` (ruff classifies `ops_core` as third-party, so `import pytest` and `from ops_core…` belong in one block), and `1 file would be reformatted`, `tests/plan_b/live/test_ollama_bridge.py` | `85 passed`, `10 skipped`, GREEN | **Blocking (B5)**. W1-style fix → GREEN |
| 4.9 | git add / status | exactly the plan's paths (6 entries); no `.env` | only those paths | PROVEN |

## Findings

### Blocking (5)
- **B1 (2.8):** `check.py` RED. RUF100 unused `# noqa: S310` in `tests/plan_b/live/kc.py` (S rules are not enabled). Also `ruff format` would rewrite `tests/plan_b/live/kc.py`, `tests/plan_b/live/test_keycloak_tokens.py` and `tests/plan_b/test_evidence.py` (lines over 120 characters; the hand-wrapped `subprocess.run([...], capture_output=True, text=True, check=True, timeout=120,)` gets exploded).
- **B2 (3.6):** `test_bootstrap_admin_is_absent` asserts 401, but Keycloak 26.8.0 returns **400 invalid_grant** for a deleted user, a wrong password or an unknown user. Step 6 gives `1 failed, 7 passed`, and the evidence `bootstrap-admin.txt` is never written.
- **B3 (3.3/3.7):** `delete_bootstrap_admin` returns "absent" only on 401. Any `bootstrap_dev.py up` after the admin is gone (a second `up` while the stack runs, and the step-7 "run up again" path) crashes with `HTTPError 400` and exit 1.
- **B4 (3.9):** `check.py` RED because `tests/plan_b/live/test_service_account.py` needs reformatting (3 long lines).
- **B5 (4.8):** `check.py` RED because of I001 in `tests/plan_b/test_model_pins.py` (the separate first-party block for `ops_core` is wrong for this ruff config) and because `tests/plan_b/live/test_ollama_bridge.py` needs reformatting.

### Misleading (5)
- **M1 (1.15):** `tail -2` of `down` shows `Network ops-dev-net Removing` and `Network ops-dev-net Removed`, not a `Container … Removed` line.
- **M2 (2.7):** `keycloak-claims.txt` has 6 lines, not five (3 workload clients, 2 personas, and the `iss host vs container` line). After Task 3 it is 9 per run.
- **M3 (3.7):** the probe prints `after restart: HTTP 400 (still absent)`, which is neither of the two "exactly one of" strings. The script's label is right, but the expected text is wrong.
- **M4 (3.2/3.3):** the edit instructions are underspecified. The JSON fragments omit the separating commas. The `import json/urllib.*` block is shown standalone (it has to be merged into the existing import block in sorted order, or ruff I001/E402 fails). The `main` snippet is shown at 8-space indent but goes inside `if rc == 0:`. No placement is given for `delete_bootstrap_admin`.
- **M5 (4.7):** the nested fences in the runbook block make the file boundaries ambiguous to a reader and to any tool that extracts fenced blocks.

### Risky (3)
- **R1:** `test_default_secrets_dir_is_outside_repo` requires `"ops-copilot" in d.parts and d.name == "secrets"`. With the plan's documented override `OPS_SECRETS_DIR` set to any other path, `pytest`/`check.py` fail (`1 failed, 11 passed`). Every `check.py` total above was GREEN only because the override was unset in that shell. Relatedly, `test_evidence.py` compares evidence against whichever secrets directory the current shell resolves, not necessarily the one the stack used.
- **R2:** `python:3.13-slim@sha256:bf44…` was not cached on this machine. The plan's "Facts" give only its digest, and the first `test_iss_is_identical_from_host_and_container` pulls it inside `subprocess.run(timeout=120)`. It worked here in about 15 s; on a slow link it would time out. (The image is now cached as a side effect of this dry run, and so is pgvector.)
- **R3:** `_record` appends to `keycloak-claims.txt`. Any re-run of the live suite (inevitable after a failure such as B2) duplicates every line; I got 18 lines after two Task-3 runs. Only Task 2 step 7 and Task 3 step 6 `rm -f` the file first, and those duplicated lines get committed.

Informational: `docker compose restart keycloak` keeps the H2 dev data in the container layer (realm import skipped, admin not re-created). "Ephemeral" holds only across container re-creation (`down`/`up`), which the docs correctly use for rotation.

## Unknowns 1–12

1. **Placeholder substitution: yes.** `${KC_*}` and `${MCP_*}` are substituted. All persona password grants succeeded and `sub` equals the seed IDs. Worker `aud` = `["http://mcp-read:8081/mcp","http://mcp-write:8082/mcp","account"]`, mcp-read `["asset-sim","account"]`, mcp-write `["incident-sim","account"]`. Log: `Full importing from file …/realm-ops-dev.json`, `Realm 'ops-dev' imported`, `KC-SERVICES0032: Import finished successfully`.
2. **Healthcheck: yes.** Health log shows `/dev/tcp/127.0.0.1/9000: Connection refused` until ready, then exit 0. Container start → healthy ≈ 26 s (start 07:00:04.7, healthy probe 07:00:30.2); Keycloak's own `started in 13.657s`. Whole `up` 27 s with images cached. The restart took 15 s.
3. **Entrypoint: yes.** It ran. The file is stored and checked out LF (`git ls-files --eol`: `i/lf w/lf`, `.gitattributes * text=auto eol=lf` overrides `core.autocrlf=true`), it is invoked via `/bin/bash` so mode is irrelevant, and uid 1000 read every `/run/secrets/kc_*` (substitution proves it).
4. **Seed IDs: yes.** `sub` == seed id for all five personas (`alex 2fc05986…`, `sam 03f7eb09…`, `lee`, `riley`, `jordan` all asserted).
5. **Same `iss`: yes.** Both are `http://localhost:18080/realms/ops-dev` (evidence line `iss host vs container`).
6. **view-users role: yes.** The role imports via `serviceAccountClientId` + `clientRoles`. GET `users/{alex}` → 200 with `enabled: true`. PUT user, GET clients and POST users → 403 (asserted by the passing test).
7. **Bootstrap admin removal: yes, with a gap.** The self-token delete works (`bootstrap admin: deleted`). After `restart`: `after restart: HTTP 400 (still absent)`. The status is 400, not 401 (B2/B3).
8. **Compose ps JSON: yes.** One JSON object per line (1 line for 1 container). Fields present: `"Service":"postgres"`, `"State":"running"`, `"Health":"healthy"`, `"Publishers":[{"URL":"127.0.0.1","TargetPort":5432,"PublishedPort":15432,"Protocol":"tcp"}]`.
9. **No secrets in inspect: yes.** It prints `0` for both postgres (`POSTGRES_PASSWORD=`) and keycloak (`PASSWORD=\|SECRET=`).
10. **Task 4: yes.** The helper reached `host.docker.internal:11434` (0.33.3 = host). The RED result was the stated `ModuleNotFoundError`, `1 error`. The pins tests gave exactly `9 passed`, and `mypy core/src` reported `Success: no issues found in 2 source files`.
11. **check.py totals:** 66/3, 74/7, 76/9 and 85/10 all match exactly. Task 1 was GREEN as written. Tasks 2, 3 and 4 were **RED as written** because of ruff (B1, B4, B5). Files the formatter wants to change: `tests/plan_b/live/kc.py`, `tests/plan_b/live/test_keycloak_tokens.py`, `tests/plan_b/test_evidence.py`, `tests/plan_b/live/test_service_account.py` and `tests/plan_b/live/test_ollama_bridge.py`. ruff check flagged `RUF100` in kc.py and `I001` in test_model_pins.py.
12. **git status: yes.** After every `git add`, `git status --short` listed only the plan's paths, and `.env` never appeared (git-ignored).

## Workarounds applied (scratch only)
- **W1 (B1, B4, B5):** `uv run ruff check --fix` on `tests/plan_b/live/kc.py` and `tests/plan_b/test_model_pins.py`, then `uv run ruff format` on the 5 listed files.
- **W2 (B2, B3):** `assert status in (400, 401)` in `test_bootstrap_admin_is_absent`, and `if exc.code in (400, 401):` in `delete_bootstrap_admin`.
- **Not a plan workaround:** I removed one extra blank line that my own insertion of `delete_bootstrap_admin` had introduced.

## Cleanup confirmation
- `docker compose --profile dev down` was run, and `docker volume rm ops-copilot-dryrun_pg-data` succeeded. `docker network rm ops-dev-net` returned "not found" (already removed by `down`).
- `docker ps -a | grep dryrun`, `docker volume ls | grep -E "dryrun|ops-copilot"` and `docker network ls | grep ops-dev` all returned empty. The other project's `portal-*` containers were not touched.
- `git worktree remove --force` and `git worktree prune` were run. `git worktree list` now shows only `C:/Users/joeys/Desktop/MLOps b98140f [plan-b]`. The 3 dry-run commits were on a detached HEAD and are now unreferenced.
- I deleted `planb-secrets/`. The real `%LOCALAPPDATA%\ops-copilot` was never written; it was only read by `test_evidence.py` when `OPS_SECRETS_DIR` was unset.
- **Note:** the real repository's current branch now reads **`plan-b`** (it was `plan-a` at the start). This dry run never ran checkout/switch/branch in the real repo, so the change came from outside it. The untracked plan file is still there.
- Side effects outside the repo: `pgvector/pgvector:pg17@sha256:ac08…` and `python:3.13-slim@sha256:bf44…` are now in the local image cache.

## Final verdict
**EXECUTABLE WITH FIXES**:
1. Use 400 (or 400/401) for the deleted-admin password grant, in both `test_bootstrap_admin_is_absent` and `delete_bootstrap_admin`. Update the step-7 expected strings and the runbook paragraph to match.
2. Make the plan's Python ruff-clean as written. Drop `# noqa: S310` in kc.py, merge the `ops_core` import into the third-party block in test_model_pins.py, and pre-format kc.py, test_keycloak_tokens.py, test_evidence.py, test_service_account.py and test_ollama_bridge.py to ruff format at 120 characters.
3. Fix the expected text: step 1.15 tail output, the 6-line claims file (9 after Task 3), and the step-3.7 line.
4. Make the edit instructions in Task 3 steps 2–3 explicit (commas, import merge, indentation, placement), and fix the nested fences around `ollama-network.md`.
5. Optionally fix R1–R3: let `test_default_secrets_dir_is_outside_repo` ignore or unset `OPS_SECRETS_DIR`, add `docker pull` of the helper image to the bootstrap, and truncate `keycloak-claims.txt` at session start rather than appending.

---

## Round 2 — static re-review of the fixes

# Plan B static re-review, round 2

**Plan reviewed:** `docs/superpowers/plans/2026-10-08-first-slice-b-dev-bootstrap.md` (revised, 1735 lines). `Lnnn` means a line of the revised plan.

**Stance:** every claim starts UNPROVEN. I ran no Docker and modified no repository file. I did run some checks in `scratchpad/planb-review/sim2/` with the repo's `.venv` (ruff 0.16.10, mypy, pydantic 2.13.5) and the repo's `pyproject.toml`:

- **Extraction:** a script pulled all 13 `Create <path>` Python blocks out of the plan, then built two Task 3 merges:
  - **t3good:** imports merged into the top block in sorted order.
  - **t3naive:** the "add:" import block pasted directly below the existing imports.
- **Loader tests:** I ran the `ModelPins` tests against the extracted loader (13 passed).
- **Strict mode:** I probed pydantic strict-mode edge cases directly.

## 1. Round-1 findings: verdicts

| # | Round-1 finding | Verdict | Evidence in the revised plan |
|---|---|---|---|
| B1 | The pins loader rejects the real bare-hex digest | **PARTIALLY** | **Fixed in code.**<br>- `Digest` pattern `^[0-9a-f]{64}$` (L1505).<br>- The GOOD fixture is bare (L1403).<br>- The `prefixed` digest is rejected (L1446, L1457).<br>- `test_loads_exactly_what_probe_py_writes` (L1421-1434) matches `probe.py` L348-350: four keys, `indent=2`, trailing `\n`.<br>- The ruling is sound: `probe.py` `model_digest()` returns `/api/tags`'s `digest` verbatim (L66-71), so there is one canonical form.<br><br>**Not fixed in the contract text.** The format decision that T19/T45 read is recorded backwards:<br>- Interfaces L1387 still says `digest: str matching ^sha256:[0-9a-f]{64}$`.<br>- Review Focus L40 still names "a digest without `sha256:`" as the failure the loader must reject.<br><br>See N1. |
| I1 | ruff gate goes RED | **ADDRESSED** | Measured on the extracted plan code:<br>- All 13 Create blocks give `All checks passed!` and `13 files already formatted`.<br>- The t3good merge (the Task 3 snippets merged correctly) is also clean.<br>- The t3naive merge gives **I001** in `scripts/bootstrap_dev.py` (fixable). The residual is tracked under M7. |
| I2 | The healthcheck greps the body for `"UP"` | **ADDRESSED** | L204-205: `head -n 1 <&3 \| grep -q ' 200 '` on the status line. This exact probe was never run; see N9. |
| I3 | `postgres_password` rotation | **ADDRESSED** | L555 documents `ALTER ROLE` before the restart, or an owner-run `down -v`. A new hygiene issue is N7 (the secret goes on the command line). |
| I4 | Audience assertions not exact | **ADDRESSED** | L904-907 removes `account` from the token's `aud`, then:<br>- L913 asserts the worker's audiences equal exactly the two MCP URLs.<br>- L925 asserts each MCP client's audiences equal exactly its one audience.<br><br>The dry run measured `account` in every workload `aud`, so excluding it is correct. |
| I5 | Wildcard redirect | **ADDRESSED** | - L718 sets the exact redirect `http://localhost:8000/auth/callback`.<br>- L720 sets `post.logout.redirect.uris` to `http://localhost:8000/`.<br>- L657-660 test both by equality.<br><br>The stale Interfaces L589 still says `/*` (N2). |
| I6 | Firewall runbook rests on an unmeasured source address | **PARTIALLY** | **Done:**<br>- Step 6 lists the rules by Program and by `-DisplayName` (L1589).<br>- It reads `Get-NetFirewallProfile` (L1592).<br>- It records `Get-NetTCPConnection` while a helper container holds a socket (L1595-1599).<br>- The runbook reasons from the measured address, with a fallback (L1642, L1674).<br>- The wording is now "created when Windows asked ... or by its installer" (L1615).<br>- Step 3 verifies the profiles (L1667-1669).<br><br>**Gaps:**<br>- (a) The Hyper-V VM firewall readout from the round-1 fix is absent.<br>- (b) The step-6 Expected (L1599) has no branch for "every row is 127.0.0.1". That result is plausible if Docker Desktop proxies host-bound traffic.<br>- (c) "`NotConfigured`, which means Block" (L1593, L1669) is not what the docs say (N6). |
| I7 | Placeholders in Keycloak's `KC_` option namespace | **ADDRESSED** | - The entrypoint (L252-263) exports `KC_BOOTSTRAP_ADMIN_PASSWORD` and `OPS_${name^^}` for every other `kc_*` file.<br>- The regex `^\$\{OPS_KC_[A-Z0-9_]+\}$` (L603) matches every realm placeholder (L713, 727, 754, 774, 811, 822, 1141, 1159, 1170, 1181).<br>- The names agree across all three layers: `SECRET_NAMES` (L356-365 plus four) = Compose `secrets:` (L192-199 plus four) = `OPS_KC_*` placeholders.<br><br>Prose still says `${KC_*}` at L7, L1030 and L1069 (N2). |
| I8 | The self-delete verify-first spike was skipped | **ADDRESSED** | The ruling is sound and correctly applied. The dry run (rows 3.6a and 3.7, Unknown 7) measured:<br>- `bootstrap admin: deleted`<br>- 400 `invalid_grant` afterwards<br>- `after restart: HTTP 400 (still absent)`<br><br>The plan records these at L15, L1206-1207, L1311 and L1342. |
| I9 | Image digests unproven as pullable RepoDigests | **NOT ADDRESSED** | L15 claims "all three image digests pulled from their registries". The dry-run report says otherwise:<br>- "Keycloak 26.8.0 image cached" (header).<br>- Side effects list only `pgvector` and `python:3.13-slim` as newly cached (L115).<br>- The `python:3.13-slim` helper "was not cached" (R2).<br><br>No `docker pull` or RepoDigests readout was ever recorded for Keycloak. The ruling's premise is wrong; see N3. |
| M1 | The evidence file was overwritten on a re-run | **ADDRESSED** | L1313 now appends. That introduces accumulation (N8). |
| M2 | "five lines" | **ADDRESSED** | L1033: "six lines". |
| M3 | Nested fences | **ADDRESSED** | L1606-1607 and L1690 use a four-backtick outer fence. No other block contains an inner fence: I checked the topology blocks at L536, L1058, L1347 and L1696. |
| M4 | Vacuous loopback test | **ADDRESSED** | L503 `assert compose_ps`; L506 requires at least one published port per row. |
| M5 | Evidence test reads the wrong secrets directory | **ADDRESSED** | - L993 imports `secrets_dir`.<br>- L998-1004 read `OPS_SECRETS_DIR` from `.env`.<br>- The docstring states that CI applies the JWT check only. |
| M6 | `tenant` attribute dropped by the user profile | **ADDRESSED** | Users carry no `attributes` (L801-824, L1149-1182). L677 and L1107 assert `"attributes" not in user`. Stale prose remains at L26, L1069 and L1729 (N2). |
| M7 | "Merge into the sorted top import block" | **PARTIALLY** | L30 sets the general rule, but Task 3 Step 3 (L1195-1201) still says only "add:" above a standalone import block. A literal paste gives **I001** (measured on t3naive). The `main` snippet is still shown at 8-space indent; L1236 explains in prose that it goes inside `if rc == 0:` (12 spaces). |
| M8 | `probed_at` int accepted; blank `model` accepted | **ADDRESSED** | `strict=True` (L1515), `strip_whitespace` with `min_length=1` (L1504), and tests at L1450-1452. Measured: the `epoch-int` input is rejected with `datetime_type`, and `"   "` and `"\t"` are rejected with `string_too_short`. Residue in N12. |
| M9 | `${PG_PORT:?}` guard | **ADDRESSED** | L161 and L183. Compose's `${VAR:?err}` fails `config`/`up` with "required variable ... is missing a value: err". |
| M10 | §21 non-root, third-party images | **ADDRESSED** | L1730. |
| M11 | Egress test not noted | **ADDRESSED** | L1730 (deferred to T08). |
| M12 | A bare `compose up` leaves `tmpadmin` | **ADDRESSED** | L1358. |
| M13 | `-Program` scope and a subnet-drift status check | **NOT ADDRESSED (deliberate)** | The ruling is acceptable: only Ollama listens on 11434, and a subnet drift fails closed. Note that the drift-check half was declined along with the `-Program` half. |
| M14 | `python -m pytest` dependency | **ADDRESSED** | L1731. |
| M15 | README omits `typ` | **ADDRESSED** | L1046. |

**Totals:** 20 ADDRESSED, 3 PARTIALLY (B1, I6, M7), 2 NOT ADDRESSED (I9, M13; M13 deliberately).

## 2. New findings

### Blocking

None.

### Important

**N1. The model-pins contract text contradicts the B1 fix** (L1387, L40).
- **Problem:**
  - Interfaces → Produces says `digest` must match `^sha256:[0-9a-f]{64}$`.
  - Review Focus 5 says the loader must reject "a digest without `sha256:`".
  - The code (L1505) and the tests (L1446) do the opposite.
- **Why it matters:** T19 (the warm-up comparison) and T45 (`schemas/model-pins.schema.json`, AM-80) read the Interfaces section. Writing the schema from L1387 reintroduces B1 at the schema layer, and `probe.py`'s output then fails schema validation.
- **Fix:**
  - L1387: `digest: str` matching `^[0-9a-f]{64}$` (the bare hex Ollama reports; `sha256:`-prefixed values are rejected).
  - L40: "(a `sha256:`-prefixed or non-hex digest, a missing field)".
  - Note the canonical form for T45 in Coverage notes.

**N3. A false "verified" fact: the Keycloak digest was never pulled** (L15; I9 ruling).
- **Problem:** The dry run used the cached Keycloak image and recorded no `docker pull` and no `RepoDigests` for it. With the classic (non-containerd) image store, `name@sha256:<id>` can resolve locally against an image ID that is not a registry manifest digest, so a successful local `up` does not prove a clean clone can pull.
- **Fix:** Before execution, run these and record the output in L13/L15:
  - `docker buildx imagetools inspect quay.io/keycloak/keycloak:26.8.0 --format '{{json .Manifest.Digest}}'`, or `docker pull quay.io/keycloak/keycloak:26.8.0@sha256:b0f60d48…` from a machine or context without the cache;
  - `docker image inspect --format '{{json .RepoDigests}}'` for all three images.

  Until then, reword L15 to "pgvector and python digests pulled; Keycloak digest taken from the local cache, pull unverified".

### Minor

**N2. Stale prose after the I5/I7/M6 edits.** Each item below is the location, then the replacement text.
- **L7 (Architecture):** "exports … as `KC_*` … only `${KC_*}` placeholders" → `KC_BOOTSTRAP_ADMIN_PASSWORD` plus `OPS_KC_*`; `${OPS_KC_*}` placeholders.
- **L26:** "a `tenant` user attribute exist for display and tests only" → delete the clause.
- **L589:** "redirect `http://localhost:8000/*`" → the exact URI plus the post-logout URI.
- **L1030:** "`${KC_*}` placeholders" → `${OPS_KC_*}`.
- **L1069:** this text ships in the committed `dev-topology.md` runbook. Change "`${KC_*}` placeholders" to `${OPS_KC_*}`, and change "Realm roles and the `tenant` attribute are informational" to "Realm roles are informational; Keycloak users carry no tenant attribute".
- **L1729:** "The realm's `tenant` attribute is informational" → "Keycloak carries no tenant data".

**N4. Wrong diagnostic status** (L1030).
- **Problem:** The step says that if the persona test "fails with `401 invalid_grant`", the placeholders were not substituted. The dry run measured that Keycloak 26.8 answers a bad password grant with **400** `invalid_grant`. An executor who sees 400 does not recognise the described failure.
- **Fix:** "fails with HTTP 400 `invalid_grant` (password grant) or 401 `unauthorized_client` (client credentials)". The 401 for client credentials is from my knowledge of Keycloak's error mapping and is unmeasured, so phrase it as "or a 401".

**N5. Task 3 Step 3 is still paste-unsafe** (L1195-1201; dry-run M4, carried over).
- Fix both points:
  - Say "merge these four imports into the existing top import block in sorted order (json before os; urllib.* after sys)".
  - Show the `main` hunk in full context:

    ```python
    if command == "up":
        rc = compose(...)
        if rc == 0:
            ...
        return rc
    ```

- **Also from the dry run, still unfixed:**
  - The Step 2 JSON fragments (L1134, L1149) need a leading `,` after the last existing element. State it.
  - L53 still names the parameter `dir`; the code uses `directory`.

**N6. The `NotConfigured` claim does not match Microsoft's docs** (L1593, L1669).
- **What the docs say** (learn.microsoft.com/powershell/module/netsecurity/set-netfirewallprofile, `-DefaultInboundAction`): "NotConfigured: Valid only when configuring a Group Policy Object (GPO)… The default setting when managing a computer is Block."
- **Problem:** `Get-NetFirewallProfile` reads the PersistentStore by default and can show `NotConfigured` there. The effective value comes from the merged policy, so a GPO or MDM `Allow` would hide behind `NotConfigured`.
- **Fix:** In both places use `Get-NetFirewallProfile -PolicyStore ActiveStore | Select Name,Enabled,DefaultInboundAction`, and require `Block` there.

**N7. The `postgres_password` rotation puts the secret on the command line** (L555).
- **Problem:** `psql -c "ALTER ROLE ops PASSWORD '<new value>'"` leaves the value in shell history and briefly in the container's process list.
- **Fix:** Feed it from the file:

  ```
  docker exec -i ops-copilot-postgres-1 psql -U ops -d ops -v pw="$(cat "$OPS_SECRETS_DIR/postgres_password")" <<<"ALTER ROLE ops PASSWORD :'pw';"
  ```

  or use `\password ops` interactively. The local socket uses trust in the official image, so no old password is needed.

**N8. Evidence files accumulate on re-runs** (L976 `_record` appends; L1313 appends; L1342 appends; dry-run R3).
- **Problem:** Two files grow on every re-run, and the duplicates get committed (dry run: 18 lines after two runs):
  - `bootstrap-admin.txt` is never truncated, and every live re-run adds another "after bootstrap" line.
  - `keycloak-claims.txt` is truncated only by Step 6's `rm`; a failed-then-re-run live suite duplicates it.
- **Fix:**
  - Add `rm -f reports/bootstrap/bootstrap-admin.txt` to Task 3 Step 6's command (L1321).
  - State at L1342 that Step 7's line is appended after the final live run.
  - Add a pre-commit check that the files have exactly 9 and 2 lines (`wc -l`). Alternatively, have a session-scoped autouse fixture truncate them.

**N9. The revised healthcheck is unmeasured** (L204-205 versus L15).
- **Problem:** L15's "readiness probe … healthy about 26 s" measured the old body-grep probe. The new probe adds `head`; `grep` is proven present because the old probe used it. The Keycloak image is ubi9-micro based, and I did not verify that coreutils' `head` is present. If it is missing, `up --wait` fails after 240 s, loudly, not insecurely.
- **Fix:** Reword L15 to "the old probe". Use bash only, avoiding external commands:

  ```
  read -r line <&3; [[ $line == *" 200 "* ]]
  ```

  That needs `bash -c` with the `exec` first, which is already the case.

**N10. `test_bootstrap_admin_is_absent` and `delete_bootstrap_admin` cannot tell "absent" from "wrong password"** (L1216, L1311).
- **Problem:** The dry run measured the same 400 `Invalid user credentials` for a deleted user, a wrong password and an unknown user. Only the server event (`error="user_not_found"`) differs. A secrets-directory mismatch therefore reports "absent" while `tmpadmin` still exists.
- **Fix:** In the test, also assert that `docker logs ops-copilot-keycloak-1` contains `error="user_not_found"` with `username="tmpadmin"` after the attempt. Rename the evidence label to "password grant rejected".

**N11. `test_default_secrets_dir_is_outside_repo` fails when `OPS_SECRETS_DIR` is set** (L321-324; dry-run R1, not fixed).
- **Problem:** The plan documents the override (L344), yet setting it in the shell turns `check.py` RED.
- **Fix:** Take `monkeypatch` and call `monkeypatch.delenv("OPS_SECRETS_DIR", raising=False)` first.
- **Related:** the Step 7 inline script (L1335) ignores `.env`'s `OPS_SECRETS_DIR`. Read `.env` the way `local_secrets_dir()` does.

**N12. Small residues in the pins and runbook code.**
- **Numeric-string timestamp:**
  - Measured: strict mode accepts `"probed_at": "1759881723"` as an aware datetime (2025-10-08 UTC), because the string is parsed as a Unix timestamp.
  - Harmless for `probe.py`, which writes `isoformat()`. Add the case if you want only ISO 8601.
- **Probe fixture:** the probe-shape test uses a timestamp without microseconds. `probe.py` writes `datetime.now(UTC).isoformat()` with microseconds. Measured: that parses fine, but the fixture could use the real shape.
- **Runbook Step 2 is not re-runnable:**
  - Its `Get-NetFirewallRule -DisplayName '*ollama*' | Disable-NetFirewallRule` (L1650) also matches the scoped rule "Ollama 11434 - …".
  - Re-applying Step 2, for example after a reboot, disables the scoped rule and creates a duplicate.
  - Fix: filter with `Where-Object DisplayName -notlike 'Ollama 11434*'`.
- **Step 1.15 Expected (L570):** it still says `Container … Removed` plus `Network … Removed`. The dry run's `tail -2` showed `Network … Removing` and `Network … Removed` (dry-run M1). Use `tail -1`, or loosen the Expected.

**N13. The plan cites a non-existent evidence file** (L15).
- **Problem:** `docs/reviews/plan-review-b-2026-10-08.md` does not exist (`ls docs/reviews/` shows the r-series and the plan-a review only). L32 forbids changing `docs/reviews/` during execution.
- **Fix:** Commit the round-1 and round-2 review record there before execution, as earlier plans did, or cite the actual report.

### Checks that passed (no finding)

- **Pytest totals:**
  - 66/3: 54 + 8 + 4; 1 + 2.
  - 74/7: + 7 realm + 1 evidence; + 4 live.
  - 76/9: + 1 realm + 1 bootstrap; + 2 live.
  - 89/10: + 13; + 1.
  - Task 3 Step 1: 3 failed, 10 passed (13 = 8 realm + 5 bootstrap).
  - Task 3 Step 4: 21 = 8 + 5 + 8.
  - Task 4 Step 4: 13. Measured: 13 passed.
  - Task 3 Step 6 live: 8 = 2 + 4 + 2.
- **Name consistency:** `SECRET_NAMES` = Compose `secrets:` = entrypoint exports = realm placeholders, both before and after Task 3.
- **No secrets leak into messages or evidence:**
  - Assertion messages carry names, paths, `aud` and status codes only.
  - `redact()` keeps six non-secret claims.
  - The firewall and `Get-NetTCPConnection` tables hold addresses only.
  - Every Expected line carries no secret.
  - `ops-dev-direct` stays labelled dev-only and is tested (L663-667).
- **Pydantic 2.13.5 strict mode** (docs.pydantic.dev conversion table and strict-mode pages; measured):
  - `model_validate_json` accepts ISO-8601 strings for `AwareDatetime` and rejects JSON ints (`datetime_type`).
  - `StringConstraints(strip_whitespace=True, min_length=1)` strips before the length check, so `"   "` and `"\t"` are rejected.
  - Upper-case hex is rejected.
  - `mypy --strict` reports success on `model_pins.py`.
- **Windows Firewall claims:**
  - "Explicit block rules take precedence over any conflicting allow rules" and "explicitly defined allow rules take precedence over the default block setting" are confirmed (learn.microsoft.com/…/windows-firewall/rules).
  - The first-run prompt creating rules is confirmed (same page).
  - `-RemoteAddress` accepts single addresses and `a.b.c.d/nn` subnets as a `String[]`, so `127.0.0.1,$subnet` is valid. `Set-NetFirewallRule -RemoteAddress` sets the filter (learn.microsoft.com/powershell/module/netsecurity/set-netfirewallrule, Example "AllowWeb80").
  - "Loopback is not filtered" is not stated on any page I opened. It is harmless because `127.0.0.1` is in the rule.
- **Compose:**
  - `${VAR:?msg}` fails interpolation with the message.
  - The healthcheck string contains no `$`, so Compose does not interpolate it.
  - Under `--wait`, failures during `start_period` do not count, and Compose waits for `healthy` up to `--wait-timeout 240`.
- **Fences and `git add`:**
  - The runbook's four-backtick fence holds.
  - The `git add` lists cover every created file: `compose-ps.txt` and `bootstrap-admin.txt` under `reports/bootstrap` (Task 3), and `ollama-bridge.txt` (Task 4).

## 3. The three least-certain Keycloak facts from round 1, re-assessed against the dry run

| Round-1 item | Round-1 verdict | Dry-run measurement | Verdict now |
|---|---|---|---|
| g1: `oidc-audience-mapper` + `included.custom.audience`, with `${MCP_*}` substituted | Least certain | Unknown 1: worker `aud` = `[mcp-read URL, mcp-write URL, account]`, mcp-read `[asset-sim, account]`, mcp-write `[incident-sim, account]` | **PROVEN** for 26.8.0. This also proves that non-`KC_` env vars substitute, which carries over to `OPS_KC_*` by the same mechanism. `OPS_KC_*` itself is untested, but the Task 2 live run catches a failure immediately. |
| g2: user `id` honoured on import | UNPROVEN | Unknown 4: `sub` == seed ID for all five personas | **PROVEN** |
| g3: `serviceAccountClientId` + `clientRoles.realm-management` | UNPROVEN | Unknown 6: GET user → 200 (`enabled: true`); PUT user, GET clients, POST users → 403 | **PROVEN** (role granted, and nothing that permits writes or client listing). The h item (403 on GET `/clients`) is also PROVEN. |

## 4. Declined to judge

- **Whether `head` exists in the Keycloak 26.8.0 image:** I did not run Docker (N9 gives the bash-only alternative).
- **Whether Docker Desktop on this machine proxies `host.docker.internal` traffic:** if it does, the source address is loopback; if not, it is the WSL VM address. Only the Step 6 measurement settles it (I6(b)).
- **Which image store this Docker Desktop uses, classic or containerd:** this decides whether a cached digest reference can be an image ID (N3).
- **AM-31's "compare the model digest (`/api/show`)":** `probe.py` notes that `/api/show` carries no digest. This is a T19 concern, outside Plan B.
- **Whether 401 `unauthorized_client` is Keycloak 26.8's code for a wrong client secret:** this is from my knowledge, not measured (N4).

---

## Round 2 — builder dry-run of the revised plan

# Plan B dry run, round 2: adversarial BUILDER report

Plan: `docs/superpowers/plans/2026-10-08-first-slice-b-dev-bootstrap.md`. I copied it at the start of the run (00:18 MST) to `planb-review/plan2.md`.
**The plan changed mid-run.** The real file was rewritten at 00:26:28 MST, while I was on Task 4, and that version is saved as `planb-review/plan3.md`. It is the current file; I re-checked it at the end of the run and it was byte-identical. The revision fixed text I would otherwise have reported as Misleading (listed below). I applied the revision's **executable** changes to the scratch copy and re-ran them; the results are in the "Re-verification of the mid-run revision" section.

Run: 2026-10-08 00:18–00:31 MST. Scratch worktree `planb-dryrun2` at `plan-a` = `b98140f` (detached). Docker 29.6.2, Compose v5.3.1. The Keycloak 26.8.0, pgvector and python:3.13-slim images were all cached.
- `COMPOSE_PROJECT_NAME=ops-copilot-dryrun2` was set for every Compose command, so each `ops-copilot-<svc>-1` in the plan reads `ops-copilot-dryrun2-<svc>-1` here. I treat that as a match.
- `OPS_SECRETS_DIR=C:/…/scratchpad/planb-secrets2` was set for Compose and bootstrap commands. For the `check.py` runs I unset it (`env -u`) as long as the plan as copied still had R1 (see item 9). After the revision I ran `check.py` with it set.
- Baseline: `uv sync --locked` took 3.5 s, and `check.py` gave `54 passed, 1 skipped`, `CHECK: GREEN`. Ports 18080 and 15432 were free.
- The real repo's HEAD moved during the session to `plan-b` = `32bf85d` (two external "docs(code)" commits; `docs/reviews/plan-review-b-2026-10-08.md` also appeared, untracked). I did not cause either. A baseline at `32bf85d` in a second throwaway worktree is also `54 passed, 1 skipped`, GREEN, so the totals below carry over.

## Execution log

| Task.Step | Actual | Expected | Verdict |
|---|---|---|---|
| 1.1 | `testpaths = ["tests/plan_a", "tests/plan_b"]` | — | PROVEN |
| 1.3 | `8 failed`, FileNotFoundError | same | PROVEN |
| 1.6 | `8 passed` | same | PROVEN |
| 1.8 | `ImportError: cannot import name 'bootstrap_dev' from 'scripts'`, `1 error` | same | PROVEN |
| 1.10 | `4 passed` with the override unset. With `OPS_SECRETS_DIR` set: `1 failed, 3 passed` (R1) | `4 passed` | PROVEN. R1 is fixed in the revision (re-verified) |
| 1.12a | `secrets: 8 created, 0 kept, in C:\…\planb-secrets2`, then `.env written`; tail `Container …-postgres-1 Healthy`, 7 s | same | PROVEN |
| 1.12b–e | `2 passed`; `postgres 127.0.0.1:15432->5432/tcp`; `0`; `vector`, `incident` | same | PROVEN |
| 1.13 | `66 passed, 3 skipped`, GREEN with the override unset. With it set: `1 failed, 65 passed`, **RED** | 66/3 GREEN | PROVEN after the revision (R1 fixed) |
| 1.15 | tail -2 = `Network ops-dev-net Removing` / `Network ops-dev-net Removed` | plan2: `Container … Removed` + `Network … Removed`. plan3: last line `Network ops-dev-net Removed` | plan2 Misleading; **plan3 PROVEN** |
| 1.15 git | 12 paths (11 A + `M pyproject.toml`); no `.env` | only those | PROVEN |
| 2.2 | `7 failed`, 7× FileNotFoundError | same | PROVEN |
| 2.4 | `7 passed` | same | PROVEN |
| 2.7a | `up` rc 0, 26.6 s. The tail ends with `…postgres-1 Healthy`, `…keycloak-1 Healthy` | same | PROVEN |
| 2.7b | `Realm 'ops-dev' imported`, `KC-SERVICES0077: Created temporary admin user with username tmpadmin`, `… started in 13.433s. Listening on: http://0.0.0.0:8080. Management interface listening on http://0.0.0.0:9000.` | import + Listening | PROVEN |
| 2.7c | `6 passed in 14.45s` | `6 passed` | PROVEN |
| 2.7d | 6 lines, as listed; 0 `eyJ` | six lines | PROVEN |
| 2.7e | `0` | `0` | PROVEN |
| 2.8 | ruff check clean, `80 files already formatted`, `74 passed, 7 skipped`, GREEN | 74/7 GREEN | PROVEN |
| 2.10 | `Network ops-dev-net Removed`; 8 paths; no `.env` | same | PROVEN |
| 3.1 | `3 failed, 10 passed` (the three named tests) | same | PROVEN |
| 3.2/3.3 | applied (commas, sorted import merge, `if rc == 0:` body at 12 spaces). ruff clean | — | PROVEN. plan3 now states all three explicitly |
| 3.4 | `21 passed` | same | PROVEN |
| 3.6a | tail: `…postgres-1 Healthy`, `…keycloak-1 Healthy`, `bootstrap admin: deleted` (34 s) | same | PROVEN |
| 3.6b | `8 passed in 32.70s`; `bootstrap-admin.txt` = `tmpadmin password grant after bootstrap: HTTP 400 (absent)` | `8 passed` | PROVEN |
| 3.6c | `keycloak 127.0.0.1:18080->8080/tcp`, `postgres 127.0.0.1:15432->5432/tcp`, LF | same | PROVEN |
| extra | second `bootstrap_dev.py up`: `bootstrap admin: absent`, rc 0 | idempotent | PROVEN |
| 3.7 | `after restart: HTTP 400 (still absent)`, 15 s. Log `Realm 'ops-dev' already exists. Import skipped` | same | PROVEN (plan2 and plan3 probes both) |
| 3.7 append | file = line 1 `tmpadmin password grant after bootstrap: HTTP 400 (absent)$`, line 2 `after restart: HTTP 400 (still absent)$` | that order | PROVEN |
| 3.8 | placeholder substituted | — | PROVEN |
| 3.9 | ruff clean, `81 files already formatted`, `76 passed, 9 skipped`, GREEN; `Network … Removed`; 11 paths, no `.env` | same | PROVEN |
| 4.2 | `ModuleNotFoundError: No module named 'ops_core.model_pins'`, `1 error` | same | PROVEN |
| 4.4 | `13 passed`; mypy `Success: no issues found in 2 source files` | same | PROVEN |
| 4.5 | `1 passed in 1.32s`; `host …/api/version -> 0.33.3`, `container …/api/version -> 0.33.3` | same | PROVEN |
| 4.6a | rules table (below) | allow-inbound tables | PROVEN |
| 4.6b | profiles table (below) | three rows | PROVEN |
| **4.6c** | **The only row is `127.0.0.1 127.0.0.1`** | at least one row whose RemoteAddress is **not** 127.0.0.1 | **BLOCKING (B1)** |
| 4.6d | `vEthernet (WSL (Hyper-V firewall)) 172.28.32.1 20` | same | PROVEN |
| 4.7 | four-backtick fence extracts cleanly: 82 lines, 14 inner fences intact | — | PROVEN (round-1 M5 fixed) |
| 4.8 | ruff clean, `84 files already formatted`, `89 passed, 10 skipped`, GREEN | 89/10 GREEN | PROVEN |
| 4.9 | 6 paths, no `.env` | same | PROVEN |

## Findings

### Blocking (1)
- **B1 (Task 4 step 6 and the runbook's premise).** Docker Desktop proxies a container's connection to `host.docker.internal` through `com.docker.backend`, which opens a loopback connection to Ollama. The host sees the container as `127.0.0.1`, not as an address in the WSL subnet. Measured during the container connection:
  ```
  LocalAddress LocalPort RemoteAddress RemotePort OwningProcess Proc
  127.0.0.1        53863 127.0.0.1          11434         29620 com.docker.backend
  127.0.0.1        11434 127.0.0.1          53863         28872 ollama
  ```
  The plan's own command printed only `127.0.0.1    127.0.0.1`. Inside the container, `host.docker.internal` = `192.168.65.254`, and the peer printed by `getpeername()` was `('192.168.65.254', 11434)`. In a controlled probe, a Python HTTP server bound to **127.0.0.1:18999 only** on the host was reachable from a container through `http://host.docker.internal:18999/` and reported `peer=127.0.0.1`.
  The step's Expected line cannot be met: "Record the row verbatim; the runbook's `-RemoteAddress` scope must contain it" has no non-loopback row to record. The plan's Facts line ("Docker's VM eth0 is 172.28.36.254") and the runbook's "Why not bind Ollama to 127.0.0.1 only" section are both wrong on this machine: a loopback-only bind would **not** cut the containers off. The WSL-subnet scope is therefore unnecessary for container traffic. The proposed firewall change would not break containers either, because loopback is not filtered. The runbook's design choice (keep `0.0.0.0` and add a firewall scope, rather than set `OLLAMA_HOST=127.0.0.1`) rests on a falsified premise, so the owner should re-decide.

### Misleading (0 open in the current plan)
In the version I started with (plan2), these were stale and the revision fixed all of them: the Architecture text said `${KC_*}`; Global Constraints said "a `tenant` user attribute"; Review Focus 5 said a "digest without `sha256:`"; the Task 2 Produces line said `redirect http://localhost:8000/*`; the 2.7 failure hint said `401`/`${KC_*}`; the topology realm section said `${KC_*}`/tenant attribute; step 1.15's Expected was wrong; the Task 3 step 2/3 edit instructions were underspecified (round-1 M4); the Task 4 Produces line gave the digest as `^sha256:…`. I confirmed in plan3 that each is fixed. The only stale prose left is line 1648 (part of B1).

### Risky (2)
- **R-a (round-1 R3, still open).** `_record` and `test_bootstrap_admin_is_absent` append. One extra `pytest tests/plan_b/live` run after step 3.7 took `keycloak-claims.txt` from 9 to 18 lines and put a second `tmpadmin … (absent)` line **after** the `after restart` line, which breaks the order step 3.7 describes. The plan says "append … after any re-run", but nothing truncates the files on a re-run in Task 4 or later.
- **R-b.** The Facts line and the runbook's "Step 1" both tell the owner to scope `-RemoteAddress` to the WSL subnet "and the measured source address". The measured address is `127.0.0.1`, so an owner following this literally will believe the subnet scope was validated when it never carries container traffic. This follows from B1.

## Re-verification of the mid-run revision (plan3), executed on scratch
- `test_default_secrets_dir_is_outside_repo(monkeypatch)` + `delenv`: `check.py` **with `OPS_SECRETS_DIR` set** gives `89 passed, 10 skipped`, `CHECK: GREEN`. R1 is fixed.
- `up` branch with the added comment line: ruff check clean, `84 files already formatted`.
- `probed_at` with `.123456`: `13 passed`.
- The step 3.7 probe reading `.env`, run with the shell `OPS_SECRETS_DIR` **unset**: `after restart: HTTP 400 (still absent)`.
- `Get-NetFirewallProfile -PolicyStore ActiveStore` gives Domain/Private/Public `True` / `Block`. Without `-PolicyStore` it gives `NotConfigured` for all three. The revision is right to use ActiveStore.
- Live suite under plan3 with the shell override unset: `9 passed`.

## Answers 1–12
1. **Placeholders substitute: yes.** In the Keycloak process environment (`/proc/1/environ`, names only): `KC_BOOTSTRAP_ADMIN_PASSWORD`, `KC_BOOTSTRAP_ADMIN_USERNAME`, `KC_HEALTH_ENABLED`, `KC_HOSTNAME`, `KC_HOSTNAME_BACKCHANNEL_DYNAMIC`, `KC_HTTP_ENABLED`, `KC_RUN_IN_CONTAINER` and `OPS_KC_CLIENT_SECRET_OPS_{MCP_READ,MCP_WRITE,WEB,WORKER}`, `OPS_KC_PERSONA_{ALEX,SAM}_PASSWORD` (more after Task 3). Every persona and client-credentials grant succeeded. The logs contain **no** unknown-option warning; the only WARNs are deprecated features (`identity-brokering-api:v1`, `twitter-broker:v1`) and `shouldAttachRoute` deprecated. `docker inspect` env `grep -c "PASSWORD=\|SECRET="` returns `0` for keycloak, and `POSTGRES_PASSWORD=` returns `0` for postgres.
2. **Healthcheck: yes.** Probes until `Connection refused` at 07:20:19/24/29/34 (every 5 s, Docker's default start interval). The first `rc=0` was at 07:20:39.91 UTC. Container start 07:20:14.45, so healthy took about 25.5 s. `Realm 'ops-dev' imported` at 07:20:39.029, `Listening` at 07:20:39.436, and `up --wait` returned at 07:20:40.22, all **after** the import. Manually: `/health/ready` returns `HTTP/1.0 200 OK\r`, and `/health/nope` returns `HTTP/1.0 404 Not Found` with grep rc=1. `head` (coreutils) and `grep` exist in the image. A restart took 15 s to healthy.
3. **Guard: yes.** With `.env` absent: `error while interpolating services.postgres.ports.[]: required variable PG_PORT is missing a value: run scripts/bootstrap_dev.py secrets first`, rc=1. `.env` was then restored by `secrets`.
4. **Audiences:** worker `["http://mcp-read:8081/mcp", "http://mcp-write:8082/mcp", "account"]`, mcp-read `["asset-sim", "account"]`, mcp-write `["incident-sim", "account"]`. Keycloak adds `account` and nothing else. Persona tokens carry no `aud` at all.
5. **Yes.** `test_bootstrap_admin_is_absent` passes on a measured 400 (log `LOGIN_ERROR … error="user_not_found"`). The second `bootstrap_dev.py up` prints `bootstrap admin: absent`, rc 0.
6. **Yes.** `after restart: HTTP 400 (still absent)`. The evidence file holds the grant line, then the restart line, as described. A later live re-run breaks that order (R-a).
7. Firewall (read-only):
   ```
   DisplayName Enabled Direction Action         Profile
   ollama.exe     True   Inbound  Allow Private, Public
   ollama.exe     True   Inbound  Allow Private, Public
   ```
   (Both queries print the same table.) Profiles (plan2 command): `Domain/Private/Public True NotConfigured`. ActiveStore (plan3): `True Block` for all three. Connection: `LocalAddress 127.0.0.1  RemoteAddress 127.0.0.1` (owner `com.docker.backend` ↔ `ollama`). **The RemoteAddress is NOT inside `172.28.32.0/20`** (B1). WSL: `vEthernet (WSL (Hyper-V firewall)) 172.28.32.1 20`.
8. **Yes.** `13 passed`. mypy `Success: no issues found in 2 source files`. RED step: `ModuleNotFoundError: No module named 'ops_core.model_pins'`, `1 error`. Extra probe of rejection reasons: no-digest `missing`; prefixed, not-hex, short and upper-case hex `string_pattern_mismatch`; empty and blank `string_too_short`; naive `timezone_aware`; epoch `datetime_type`; extra `extra_forbidden`. A `Z` suffix is accepted.
9. **All match.** After every task, `ruff check` printed `All checks passed!` and `ruff format --check` reported all files formatted (75, 80, 81, 84). Totals 66/3, 74/7, 76/9 and 89/10, each `CHECK: GREEN`. The formatter wanted no changes anywhere (round-1 B1/B4/B5 fixed). Caveat for plan2 only: with `OPS_SECRETS_DIR` set, Tasks 1–3 went RED (R1). plan3 fixes this, and I re-verified GREEN with the override set.
10. **Yes.** After each `git add`, only the plan's paths were listed (12, 8, 11, 6), and `.env` appears only under `--ignored`.
11. **Yes.** No `eyJ` in any evidence file. `test_evidence.py` gives `1 passed` with the secrets dir populated, both through the shell override and through `.env` alone. Negative control: planting one persona password into `keycloak-claims.txt` gives `1 failed`, and I restored the file afterwards.
12. **What a fresh engineer would trip on:**
    - (a) B1.
    - (b) Re-running the live suite duplicates evidence lines (R-a).
    - (c) Git Bash path forms are fine. With the shell variable unset and the default `LOCALAPPDATA` (`C:\Users\…`), `.env` gets `OPS_SECRETS_DIR=C:/…/ops-copilot/secrets` and `compose config --quiet` returns rc 0. A `/c/...` override is converted to `C:/...` too. I simulated the default by pointing `LOCALAPPDATA` at a scratch path, so the real `%LOCALAPPDATA%\ops-copilot` was never created.
    - (d) `docker exec … /bin/bash` from Git Bash needs `MSYS_NO_PATHCONV=1`, otherwise it gets rewritten to `C:/Program Files/Git/usr/bin/bash`. No plan step does this; I hit it only during ad-hoc inspection.
    - (e) `tee` and `printf … >>` wrote LF with no BOM.
    - (f) Real-repo HEAD is now `32bf85d` and adds `docs/CODE_COMMENTS.md` (untracked). If that commenting convention applies to new code, the plan does not mention it.

## Workarounds applied
None to the plan as written in plan3. While executing plan2, I applied the edits that plan3 later made explicit (comma placement, sorted import merge, 12-space indentation inside `if rc == 0:`). Both versions produce the same result. For plan2's R1 I ran `check.py` with `env -u OPS_SECRETS_DIR`; plan3 makes that unnecessary.

## Cleanup confirmation
- I ran `docker compose --profile dev down` and `docker volume rm ops-copilot-dryrun2_pg-data`; the volume was removed. `ops-srcaddr` and `ops-dev-net` returned "not found" (both already gone).
- I removed the scratch worktree and the extra `planb-base3` worktree (`git worktree remove --force` + `prune`). `git worktree list` now shows only `C:/Users/joeys/Desktop/MLOps 32bf85d [plan-b]`.
- `planb-secrets2` and the simulated `planb-lad` were deleted. `docker ps -a`, `docker volume ls` and `docker network ls` show nothing of mine. `%LOCALAPPDATA%\ops-copilot` does not exist. The temporary `127.0.0.1:18999` probe server exited after 25 s; netstat showed only a TIME_WAIT entry, and the listener was gone at the final check.
- The `portal-*` containers were not touched. No firewall rules, `OLLAMA_HOST` or system settings were touched, and nothing was pushed.

## Final verdict
**EXECUTABLE WITH FIXES:**
1. **B1:** rewrite Task 4 step 6's Expected line, the Facts line and the runbook's "Why not bind 127.0.0.1 only", Step 1 and the attestation columns. On this machine container traffic reaches Ollama from `127.0.0.1` via `com.docker.backend`. The likely simplest compliant design is `OLLAMA_HOST=127.0.0.1:11434`, set by the owner (a loopback-only listener was reachable from a container in my probe), with the firewall scope as an optional second layer. That is the owner's decision under AM-31.
2. **Optional (R-a):** truncate `keycloak-claims.txt` and `bootstrap-admin.txt` at session start, or document that re-runs append.

Everything else in Tasks 1–4 executed exactly as written in the current file (plan3).

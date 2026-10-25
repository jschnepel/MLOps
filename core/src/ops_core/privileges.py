"""The AM-20 privilege matrix as data: roles, per-table grants, the RLS tables and policy text, and each definer
function's callers (SPEC_AMENDMENTS AM-20.1, AM-20.2, AM-20.3, AM-20.5).

One source of truth for two consumers: the migrations render GRANT, REVOKE and POLICY statements from it for the
tables each revision creates or changes (never for "every table": an applied revision must not change when a row is
added here), and the R124/R106 tests enumerate the catalogs against it, so an extra or missing grant fails a test
instead of hiding. Rows exist only for tables that exist; the owner of a later table (operator_resolutions → T22)
adds its rows; T18 added `embeddings`, T21 `feedback`. Ten departures from the printed
table, each a proposed erratum (Plan E rulings 6, 10, 17, 23; Plan F rulings 2, 3 and 17 with erratum 25; Plan G
ruling 4; Plan H rulings 1 and 12; Plan I rulings 12 and 20): the worker (not the sweeper) may UPDATE
jobs.available_at (re-queue after a transport failure), app_definer may UPDATE runs.updated_at, app_definer may
UPDATE run_lease.fence (the fenced definers lock the lease row and mark_unknown bumps it, erratum 45), the
`transitions` table (the T07 table mirrored in SQL) is readable by app_definer only, no definer function takes a row
lock on proposals, decisions, memberships or execution_grant (a lock needs UPDATE, which the matrix withholds), the
sweeper holds SELECT beside its DELETE on sessions, login_state, logout_jti and idempotency_request (a DELETE with a
WHERE reads the row), login_state and logout_jti are rows the printed table lacks, model_permit has no sweeper cell
(an expired permit is free by the same comparison, erratum 50), the outbox has no api or worker cell (only
`_append_event` writes intent, erratum 60), and the sweeper may DELETE from jobs, finished maintenance rows only (a
restrictive policy, SWEEPER_PURGE, erratum 61). Plan L (T17) adds the corpus: AM-20.2's corpus row on `documents` and
`chunks`, and the same cells on the two append-only tables the printed table lacks, `document_states` and
`corpus_ingestions` (erratum 95). Plan P (T19) adds `run_manifests`, a row the printed table lacks (worker INSERT and
SELECT, api SELECT; erratum 120). Plan R (T21, revision 0016) adds `feedback` (SA:428: api INSERT and SELECT), the
worker's UPDATE on `runs.asset_observed_at` and `runs.workflow_version`, app_definer's UPDATE on `runs.authors`,
`checkpoint_id`, `cancel_requested` and `cancel_requested_at`, and app_definer's INSERT on `drafts` (the manual
proposal's own draft row). `test_harness` exists only in the test profile: the main-line revisions grant it
nothing; the testclock branch grants it schema USAGE, EXECUTE on current_time() and its test_clock cells.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Final

SCHEMA: Final = "app"
RUNTIME_ROLES: Final = ("api", "worker", "sweeper", "mcp_read", "mcp_exec", "operator", "test_harness")
DEFINER_ROLE: Final = "app_definer"
OWNER_ROLE: Final = "migrator"
TEST_ONLY_ROLES: Final = ("test_harness",)  # SA:403: created and granted in the test profile only
MAIN_ROLES: Final = tuple(r for r in RUNTIME_ROLES if r not in TEST_ONLY_ROLES)
GRANTEES: Final = (*RUNTIME_ROLES, DEFINER_ROLE)
MAIN_GRANTEES: Final = (*MAIN_ROLES, DEFINER_ROLE)
POLICY_ROLES: Final = ("api", "worker", "sweeper", DEFINER_ROLE)  # SA:514


@dataclass(frozen=True)
class Grant:
    """One cell of AM-20.2: `upd` is True for every column, a tuple for exactly those columns, False for none."""

    sel: bool = False
    ins: bool = False
    upd: tuple[str, ...] | bool = False
    dele: bool = False

    def privileges(self) -> set[tuple[str, str | None]]:
        """(privilege, column) pairs as the catalogs report them; column is None for a whole-table privilege."""
        out: set[tuple[str, str | None]] = set()
        if self.sel:
            out.add(("SELECT", None))
        if self.ins:
            out.add(("INSERT", None))
        if self.dele:
            out.add(("DELETE", None))
        if self.upd is True:
            out.add(("UPDATE", None))
        elif self.upd:
            out.update(("UPDATE", column) for column in self.upd)
        return out


_S = Grant(sel=True)
_SI = Grant(sel=True, ins=True)
_INS = Grant(ins=True)
_JOB_COLUMNS = ("claimed_by", "claimed_at", "done_at", "attempts")  # AM-20.2; the worker alone adds available_at

GRANTS: Final[dict[str, dict[str, Grant]]] = {
    "tenants": {"api": _S, "worker": _S, "sweeper": _S, DEFINER_ROLE: _S},
    "memberships": {
        "api": _S,
        "worker": _S,
        "sweeper": Grant(sel=True, upd=("active", "permission_version", "synced_at")),
        DEFINER_ROLE: _S,
    },
    "sessions": {
        "api": Grant(sel=True, ins=True, upd=("last_seen_at", "revoked_at"), dele=True),
        "sweeper": Grant(sel=True, dele=True),  # erratum 25: a DELETE with a WHERE needs SELECT (spike §4)
    },
    # T11 (Plan F rulings 2 and 17): the pre-login OIDC state and the back-channel logout replay store, both
    # tenant-less; the api role inserts jti rows blind (a target-less ON CONFLICT DO NOTHING, rowcount as verdict).
    "login_state": {"api": Grant(sel=True, ins=True, dele=True), "sweeper": Grant(sel=True, dele=True)},
    "logout_jti": {"api": _INS, "sweeper": Grant(sel=True, dele=True)},
    # T12 (Plan G ruling 4): the scoped Idempotency-Key record; write-once for api (no UPDATE), purged by the sweeper.
    "idempotency_request": {"api": _SI, "sweeper": Grant(sel=True, dele=True)},
    "conversations": {"api": _SI, "worker": _S, DEFINER_ROLE: _S},
    "messages": {"api": _SI, "worker": _S, DEFINER_ROLE: _S},
    "runs": {
        "api": Grant(sel=True, upd=("cancel_requested", "cancel_requested_at")),
        # T21: the asset observation the grant checks (R116) and the run's workflow version (BS:342).
        "worker": Grant(sel=True, upd=("checkpoint_id", "budget_used", "asset_observed_at", "workflow_version")),
        "sweeper": _S,
        DEFINER_ROLE: Grant(
            ins=True,
            sel=True,
            upd=(
                "state",
                "state_version",
                "reason",
                "active_proposal_id",
                "next_event_seq",
                "slot_held",
                "supersedes_run_id",
                "updated_at",
                "authors",  # T21: create_revision and create_manual_proposal append an author (SA:453)
                "checkpoint_id",  # T21: a revision starts a new graph thread (Plan R ruling 1)
                "cancel_requested",  # T21: request_cancel sets the flag (SA:458)
                "cancel_requested_at",
            ),
        ),
    },
    "run_directory": {"api": _S, "worker": _S, "sweeper": _S, DEFINER_ROLE: _SI},
    "run_state_history": {DEFINER_ROLE: _INS},
    "run_lease": {
        "worker": Grant(sel=True, ins=True, upd=True),
        "sweeper": Grant(sel=True, upd=("lease_until",)),
        DEFINER_ROLE: Grant(sel=True, upd=("fence",)),  # erratum 45: the definers lock it; mark_unknown bumps it
    },
    # T13 (Plan H ruling 12): one seeded slot per unit of model concurrency; only the worker takes and frees it.
    "model_permit": {"worker": Grant(sel=True, upd=True)},
    "jobs": {
        "api": _INS,
        "worker": Grant(sel=True, ins=True, upd=(*_JOB_COLUMNS, "available_at")),
        "sweeper": Grant(sel=True, ins=True, upd=_JOB_COLUMNS, dele=True),  # erratum 61: finished maintenance rows
        DEFINER_ROLE: _SI,
    },
    "invocation_context": {"worker": _INS, "sweeper": _S, DEFINER_ROLE: Grant(sel=True, upd=("revoked_at",))},
    "drafts": {"worker": _SI, DEFINER_ROLE: _SI},  # T21: create_manual_proposal inserts its own draft row
    "proposals": {"api": _S, "worker": _S, "sweeper": _S, DEFINER_ROLE: _SI},
    "decisions": {"api": _S, "worker": _S, DEFINER_ROLE: _SI},
    "execution_grant": {"api": _S, "worker": _S, "sweeper": _S, DEFINER_ROLE: _SI},
    "action_attempt": {"api": _S, "worker": _S, "sweeper": _S, DEFINER_ROLE: _SI},
    "action_attempt_state": {"api": _S, "worker": _S, "sweeper": _S, DEFINER_ROLE: _SI},
    "events": {"api": _S, "worker": _S, "sweeper": _S, DEFINER_ROLE: _SI},
    # T14 (Plan I ruling 12, erratum 60): intent is written by _append_event alone (INSERT, no SELECT: its ON
    # CONFLICT names no target); the sweeper claims, leases and records results under its tenant setting.
    "outbox": {
        "sweeper": Grant(sel=True, upd=("leased_until", "attempts", "delivered_at", "result")),
        DEFINER_ROLE: _INS,
    },
    "transitions": {DEFINER_ROLE: _S},
    "test_clock": {DEFINER_ROLE: _S, "test_harness": Grant(ins=True, upd=True, dele=True)},
    # T17 (Plan L ruling 3): AM-20.2's corpus row, extended to the two append-only tables the matrix lacks (erratum
    # 95); ingestion runs as the worker, and only search_procedures_scoped reads the rows.
    "corpus_ingestions": {"worker": _SI, DEFINER_ROLE: _S},
    "documents": {"worker": _SI, DEFINER_ROLE: _S},
    "document_states": {"worker": _SI, DEFINER_ROLE: _S},
    "chunks": {"worker": _SI, DEFINER_ROLE: _S},
    # T18 (Plan N ruling 1): AM-20.2's corpus row (SA:431) for the embeddings; `scripts/skeleton.py embed` inserts as
    # the worker, and only search_procedures_scoped reads them.
    "embeddings": {"worker": _SI, DEFINER_ROLE: _S},
    # T19 (revision 0014, erratum 120): a row AM-20.2 lacks (AM-80 names the manifest, no table); the worker writes each
    # run's manifest once and reads it, the api reads it, and nobody updates it.
    "run_manifests": {"worker": _SI, "api": _S},
    # T21 (revision 0016; SA:428, R113): classified feedback; nobody updates it (`reviewed` has no writer in v1).
    "feedback": {"api": _SI},
}

# AM-20.5 tenant tables (of those that exist); FORCE applies to the owner, who is exempt only through BYPASSRLS.
RLS_TABLES: Final = (
    "memberships",
    "conversations",
    "messages",
    "runs",
    "run_state_history",
    "jobs",
    "drafts",
    "proposals",
    "decisions",
    "execution_grant",
    "action_attempt",
    "action_attempt_state",
    "events",
    "outbox",
    "corpus_ingestions",
    "documents",
    "document_states",
    "chunks",
    "embeddings",  # T18: SA:510 names it
    "run_manifests",  # T19: a tenant's runs' manifests, as its runs
    "feedback",  # T21: SA:510 names it
)
SWEEPER_ALL: Final = ("memberships", "jobs")  # SA:520: the permissive policies besides tenant_isolation
# T14 (Plan I round 1, I6; erratum 61): a restrictive DELETE policy keeps the sweeper's purge to finished maintenance
# rows (sweeper_all would admit every tenant's run jobs). The text is what pg_policies.qual stores, which R106 compares.
SWEEPER_PURGE: Final = ("jobs", "sweeper_purge_maintenance", "((run_id IS NULL) AND (done_at IS NOT NULL))")
NO_RLS: Final = (
    "tenants",
    "run_directory",
    "run_lease",
    "sessions",
    "invocation_context",
    "transitions",
    "test_clock",
    "login_state",
    "logout_jti",
    "idempotency_request",
    "model_permit",
)
AUDIT_TABLES: Final = ("run_state_history", "action_attempt_state", "events")  # AM-20 principle 2
# T20 (revision 0015; SA:434, SA:559-562; R122): LangGraph's checkpoint tables, in schema `checkpoints` outside the
# `app` matrix above. Only the worker's saver reads and writes them, by thread id; no other role has any privilege on
# the schema, and there is no RLS (they are not tenant rows, erratum 123). `checkpoint_migrations` is the library's
# own bookkeeping, written by the revision only, so it has no cell.
CHECKPOINT_SCHEMA: Final = "checkpoints"
CHECKPOINT_GRANTS: Final[dict[str, dict[str, Grant]]] = {
    table: {"worker": Grant(sel=True, ins=True, upd=True, dele=True)}
    for table in ("checkpoints", "checkpoint_blobs", "checkpoint_writes")
}

# The policy expression (SA:446's NULLIF form, not SA:512's bare cast: '' raises 22P02, measured in the spike), and
# the text PostgreSQL stores for it in pg_policies.qual, which R106 compares.
TENANT_EXPR: Final = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
POLICY_QUAL: Final = "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)"

# name -> (argument types, callers granted EXECUTE); the signature text is what GRANT needs to name an overload.
DEFINER_FUNCTIONS: Final[dict[str, tuple[str, tuple[str, ...]]]] = {
    "current_time": ("", RUNTIME_ROLES),
    # resolve_identity: api only; the sweeper's sync writes memberships directly (Plan F ruling 13).
    "resolve_identity": ("text, uuid", ("api",)),
    "create_run": ("uuid, uuid, jsonb, text, uuid", ("api",)),
    "transition_run": ("uuid, text, text, text, integer, jsonb", ("worker",)),
    "append_event": ("uuid, text, jsonb, text", ("api", "worker", "sweeper")),
    "revoke_handles": ("uuid, bigint", ("worker",)),
    "freeze_proposal": ("uuid, uuid, bytea, timestamptz", ("worker",)),
    # T21 (erratum 131): the expected revision is checked under the runs lock with everything else.
    "record_decision": ("uuid, uuid, uuid, integer, text, text, text, text", ("api",)),
    "expire_proposal": ("uuid", ("sweeper", "api")),  # T21: SA:457, the scheduled job and the API's own unit
    "create_revision": ("uuid, uuid, integer, uuid, uuid", ("api",)),  # T21: SA:455 with the tenant first
    "request_cancel": ("uuid, uuid, integer, uuid", ("api",)),  # T21: SA:458 with the tenant and the actor
    # T21 (Plan R ruling 7): the manual proposal in two calls of one API unit, the canonical bytes built between them.
    "prepare_manual_proposal": ("uuid, uuid, uuid, text[]", ("api",)),
    "create_manual_proposal": ("uuid, uuid, bytea, uuid", ("api",)),
    "search_procedures_api": ("uuid, text, integer", ("api",)),  # T21: BS:280's search, lexical only (erratum 135)
    "resolve_invocation": ("text, text", ("mcp_read", "mcp_exec")),
    # T17 (Plan L ruling 1): SA:461 with the caller's azp second, as the write path since T47 (erratum 93).
    "search_procedures_scoped": ("text, text, text, public.vector, text, integer, text", ("mcp_read",)),
    # T16 (Plan M ruling 2): SA:460 with the caller's azp, for the same reason (erratum 104).
    "asset_scope": ("text, text", ("mcp_read",)),
    # T13: the raw handle first, so the fence is checked (erratum 48); T47: the token's azp second (Plan K ruling 12).
    "grant_execution": ("text, text, uuid", ("mcp_exec",)),
    "mark_sent": ("text, text, uuid", ("mcp_exec",)),
    "record_outcome": ("text, text, uuid, text, jsonb", ("mcp_exec",)),
    "lookup_action": ("text, text", ("mcp_exec",)),
    "request_abort": ("text, text, uuid", ("mcp_exec",)),  # T47 (Plan K rulings 2, 3)
    "mark_unknown": ("uuid, bigint", ("worker",)),
    "queued_runs_total": ("", ("api",)),  # T13 (Plan H ruling 13): BS:550's global count, one number
}
# Internal helpers: owned by app_definer, revoked from PUBLIC, granted to nobody (SA:474).
HELPER_FUNCTIONS: Final[dict[str, str]] = {
    "_authority": "text, text[]",
    "_tenant_of_run": "uuid",
    "_tenant_of_action": "uuid",
    "_resolve_handle": "text, text, text",
    "_latest_attempt": "uuid",
    "_grant_row": "uuid",
    "_append_event": "uuid, uuid, text, text, jsonb",
    "_transition": "uuid, text, text, text, integer, text, jsonb",
    "_dispatch_seconds": "",  # T47: the dispatch deadline, 300 s (Plan K ruling 17)
    "_min_rank": "",  # T17: the search's minimum rank, 0.25 (Plan L ruling 18, round 1)
    "_min_similarity": "",  # T18: the vector branch's minimum cosine similarity (Plan N ruling 6)
    # T21 (revision 0016): a run's current revision, the asset guard's lock and its two sets, the cited sections still
    # permitted, and the expiry every caller shares.
    "_run_revision": "uuid",
    "_asset_lock": "uuid, text",
    "_asset_guard": "uuid, text, timestamptz, timestamptz, uuid, uuid",
    "_cited_permitted": "uuid, text[]",
    "_expire": "uuid",
}


def _roles(roles: Iterable[str]) -> str:
    return ", ".join(roles)


def schema_usage_statements(roles: Iterable[str] = MAIN_GRANTEES) -> list[str]:
    """The grantees may see the schema; what they may touch inside is the matrix's business."""
    return [f"GRANT USAGE ON SCHEMA {SCHEMA} TO {_roles(roles)}"]


def grant_statements(
    tables: Iterable[str],
    grants: Mapping[str, Mapping[str, Grant]] = GRANTS,
    *,
    revokees: Iterable[str] | None = None,
) -> list[str]:
    """REVOKE ALL then exactly the given cells for each table.

    A revision passes its own frozen copy of the cells it applies and of the roles it revokes from (an applied
    revision must never change when this module's matrix moves on; round-3 finding N1, final review M2); the tests
    pass the live matrix. Without `revokees` the REVOKE names the live grantees.
    """
    frozen = tuple(revokees) if revokees is not None else None
    out: list[str] = []
    for table in tables:
        # Only roles that exist in every profile are named in a REVOKE: the test-only role's grants live on the branch.
        names = (
            frozen if frozen is not None else [r for r in GRANTEES if r not in TEST_ONLY_ROLES or table == "test_clock"]
        )
        out.append(f"REVOKE ALL ON {SCHEMA}.{table} FROM {_roles(names)}")
        for role, grant in grants[table].items():
            whole = [
                name for name, flag in (("INSERT", grant.ins), ("SELECT", grant.sel), ("DELETE", grant.dele)) if flag
            ]
            if grant.upd is True:
                whole.append("UPDATE")
            if whole:
                out.append(f"GRANT {', '.join(whole)} ON {SCHEMA}.{table} TO {role}")
            if isinstance(grant.upd, tuple) and grant.upd:
                out.append(f"GRANT UPDATE ({', '.join(grant.upd)}) ON {SCHEMA}.{table} TO {role}")
    return out


def rls_statements(tables: Iterable[str], policy_roles: Iterable[str] = POLICY_ROLES) -> list[str]:
    """ENABLE + FORCE and the AM-20.5 policies; DROP IF EXISTS first so a revision can re-apply them."""
    roles = tuple(policy_roles)
    out: list[str] = []
    for table in tables:
        rel = f"{SCHEMA}.{table}"
        out.append(f"ALTER TABLE {rel} ENABLE ROW LEVEL SECURITY")
        out.append(f"ALTER TABLE {rel} FORCE ROW LEVEL SECURITY")
        out.append(f"DROP POLICY IF EXISTS tenant_isolation ON {rel}")
        out.append(
            f"CREATE POLICY tenant_isolation ON {rel} FOR ALL TO {_roles(roles)}"
            f" USING (tenant_id = {TENANT_EXPR}) WITH CHECK (tenant_id = {TENANT_EXPR})"
        )
        if table in SWEEPER_ALL:
            out.append(f"DROP POLICY IF EXISTS sweeper_all ON {rel}")
            out.append(f"CREATE POLICY sweeper_all ON {rel} FOR ALL TO sweeper USING (true) WITH CHECK (true)")
    return out


def function_grant_statements(
    name: str,
    roles: Iterable[str] | None = None,
    *,
    args: str | None = None,
    callers: Iterable[str] | None = None,
) -> list[str]:
    """REVOKE from PUBLIC, then GRANT EXECUTE to the named callers (none for a helper), in that order (SA:446).

    A revision passes the `args` and `callers` it froze (round-3 finding N1); the tests use the live matrix. `roles`
    narrows the callers for a main-line revision (the test-only role gets its EXECUTE on the branch).
    """
    if callers is None and name in HELPER_FUNCTIONS:
        return [f"REVOKE ALL ON FUNCTION {SCHEMA}.{name}({HELPER_FUNCTIONS[name]}) FROM PUBLIC"]
    if name not in DEFINER_FUNCTIONS and name not in HELPER_FUNCTIONS:
        raise KeyError(f"{name} is not a known definer function or helper")  # a typo must not render a REVOKE
    matrix_args, matrix_callers = DEFINER_FUNCTIONS.get(name, (HELPER_FUNCTIONS.get(name, ""), ()))
    signature = f"{SCHEMA}.{name}({matrix_args if args is None else args})"
    wanted = tuple(matrix_callers if callers is None else callers)
    grantees = [r for r in wanted if roles is None or r in roles]
    out = [f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC"]
    if grantees:
        out.append(f"GRANT EXECUTE ON FUNCTION {signature} TO {_roles(grantees)}")
    return out

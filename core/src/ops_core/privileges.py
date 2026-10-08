"""The AM-20 privilege matrix as data: roles, per-table grants, the RLS tables and policy text, and each definer
function's callers (SPEC_AMENDMENTS AM-20.1, AM-20.2, AM-20.3, AM-20.5).

One source of truth for two consumers: the migrations render GRANT, REVOKE and POLICY statements from it for the
tables each revision creates or changes (never for "every table": an applied revision must not change when a row is
added here), and the R124/R106 tests enumerate the catalogs against it, so an extra or missing grant fails a test
instead of hiding. Rows exist only for tables that exist; the owners of later tables (outbox → T14, feedback and
idempotency_request → T12, operator_resolutions → T22, documents/chunks/embeddings → T17, model_permit → T13) add
their rows. Four departures from the printed table, each a proposed erratum (Plan E rulings 6, 10, 17, 23): the worker
(not the sweeper) may UPDATE jobs.available_at (re-queue after a transport failure), app_definer may UPDATE
runs.updated_at, the `transitions` table (the T07 table mirrored in SQL) is readable by app_definer only, and no
definer function takes a row lock on proposals, decisions, memberships or execution_grant (a lock needs UPDATE, which
the matrix withholds). `test_harness` exists only in the test profile: the main-line revisions grant it nothing; the
testclock branch grants it schema USAGE, EXECUTE on current_time() and its test_clock cells.
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
        "sweeper": Grant(dele=True),
    },
    "conversations": {"api": _SI, "worker": _S, DEFINER_ROLE: _S},
    "messages": {"api": _SI, "worker": _S, DEFINER_ROLE: _S},
    "runs": {
        "api": Grant(sel=True, upd=("cancel_requested", "cancel_requested_at")),
        "worker": Grant(sel=True, upd=("checkpoint_id", "budget_used")),
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
            ),
        ),
    },
    "run_directory": {"api": _S, "worker": _S, "sweeper": _S, DEFINER_ROLE: _SI},
    "run_state_history": {DEFINER_ROLE: _INS},
    "run_lease": {
        "worker": Grant(sel=True, ins=True, upd=True),
        "sweeper": Grant(sel=True, upd=("lease_until",)),
        DEFINER_ROLE: _S,
    },
    "jobs": {
        "api": _INS,
        "worker": Grant(sel=True, ins=True, upd=(*_JOB_COLUMNS, "available_at")),
        "sweeper": Grant(sel=True, ins=True, upd=_JOB_COLUMNS),
        DEFINER_ROLE: _SI,
    },
    "invocation_context": {"worker": _INS, "sweeper": _S, DEFINER_ROLE: Grant(sel=True, upd=("revoked_at",))},
    "drafts": {"worker": _SI, DEFINER_ROLE: _S},
    "proposals": {"api": _S, "worker": _S, "sweeper": _S, DEFINER_ROLE: _SI},
    "decisions": {"api": _S, "worker": _S, DEFINER_ROLE: _SI},
    "execution_grant": {"api": _S, "worker": _S, "sweeper": _S, DEFINER_ROLE: _SI},
    "action_attempt": {"api": _S, "worker": _S, "sweeper": _S, DEFINER_ROLE: _SI},
    "action_attempt_state": {"api": _S, "worker": _S, "sweeper": _S, DEFINER_ROLE: _SI},
    "events": {"api": _S, "worker": _S, "sweeper": _S, DEFINER_ROLE: _SI},
    "transitions": {DEFINER_ROLE: _S},
    "test_clock": {DEFINER_ROLE: _S, "test_harness": Grant(ins=True, upd=True, dele=True)},
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
)
SWEEPER_ALL: Final = ("memberships", "jobs")  # SA:520: the only policies besides tenant_isolation
NO_RLS: Final = ("tenants", "run_directory", "run_lease", "sessions", "invocation_context", "transitions", "test_clock")
AUDIT_TABLES: Final = ("run_state_history", "action_attempt_state", "events")  # AM-20 principle 2

# The policy expression (SA:446's NULLIF form, not SA:512's bare cast: '' raises 22P02, measured in the spike), and
# the text PostgreSQL stores for it in pg_policies.qual, which R106 compares.
TENANT_EXPR: Final = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
POLICY_QUAL: Final = "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)"

# name -> (argument types, callers granted EXECUTE); the signature text is what GRANT needs to name an overload.
DEFINER_FUNCTIONS: Final[dict[str, tuple[str, tuple[str, ...]]]] = {
    "current_time": ("", RUNTIME_ROLES),
    "resolve_identity": ("text, uuid", ("api",)),  # the sweeper's membership sync (T11) adds itself
    "create_run": ("uuid, uuid, jsonb, text, uuid", ("api",)),
    "transition_run": ("uuid, text, text, text, integer, jsonb", ("worker",)),
    "append_event": ("uuid, text, jsonb, text", ("api", "worker", "sweeper")),
    "revoke_handles": ("uuid, bigint", ("worker",)),
    "freeze_proposal": ("uuid, uuid, bytea, timestamptz", ("worker",)),
    "record_decision": ("uuid, uuid, uuid, text, text, text, text", ("api",)),
    "resolve_invocation": ("text, text", ("mcp_read", "mcp_exec")),
    "grant_execution": ("text, uuid", ("mcp_exec",)),
    "mark_sent": ("uuid", ("mcp_exec",)),
    "record_outcome": ("uuid, text, jsonb", ("mcp_exec",)),
    "lookup_action": ("text", ("mcp_exec",)),
    "mark_unknown": ("uuid, bigint", ("worker",)),
}
# Internal helpers: owned by app_definer, revoked from PUBLIC, granted to nobody (SA:474).
HELPER_FUNCTIONS: Final[dict[str, str]] = {
    "_authority": "text, text[]",
    "_tenant_of_run": "uuid",
    "_tenant_of_action": "uuid",
    "_resolve_handle": "text, text, text",
    "_latest_attempt": "uuid",
    "_append_event": "uuid, uuid, text, text, jsonb",
    "_transition": "uuid, text, text, text, integer, text, jsonb",
}


def _roles(roles: Iterable[str]) -> str:
    return ", ".join(roles)


def schema_usage_statements(roles: Iterable[str] = MAIN_GRANTEES) -> list[str]:
    """The grantees may see the schema; what they may touch inside is the matrix's business."""
    return [f"GRANT USAGE ON SCHEMA {SCHEMA} TO {_roles(roles)}"]


def grant_statements(tables: Iterable[str], grants: Mapping[str, Mapping[str, Grant]] = GRANTS) -> list[str]:
    """REVOKE ALL then exactly the given cells for each table.

    A revision passes its own frozen copy of the cells it applies (an applied revision must never change when this
    module's matrix moves on; round-3 finding N1); the tests pass the live matrix.
    """
    out: list[str] = []
    for table in tables:
        # Only roles that exist in every profile are named in a REVOKE: the test-only role's grants live on the branch.
        revokees = [r for r in GRANTEES if r not in TEST_ONLY_ROLES or table == "test_clock"]
        out.append(f"REVOKE ALL ON {SCHEMA}.{table} FROM {_roles(revokees)}")
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

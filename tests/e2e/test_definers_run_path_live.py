"""The run-path definer functions as their callers (OPS_LIVE=1; AM-20.3 rows 1–3, 23, R128, R106 part 1).

Catches: a function callable by the wrong role, transition_run accepting a post-grant target or a wrong `from`,
a stale expected_version, a transition that leaves the slot flag wrong, an event that skips a sequence number or
carries a forbidden (type, source), run.* events accepted from append_event, a preset tenant that leaks through
`resolve_identity`, and a plain SET inside any function (the caller's app.tenant_id must be unchanged after a call).
"""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import psycopg
import pytest
from ops_core import persistence
from ops_core.settings import Role
from psycopg.types.json import Jsonb

from tests.e2e.conftest import purge_run

pytestmark = pytest.mark.asyncio

RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
ALPHA = UUID("3ea79c95-914c-52cb-9d10-c4e19dda8ff7")
BETA = UUID("5ab45c2c-1e12-5a0c-a2b9-66cd2ff05201")
ALEX = UUID("2fc05986-c7ec-544c-b628-fdb112bbf18a")
ISSUER_SQL = "SELECT issuer FROM app.memberships LIMIT 1"
CREATE_INVESTIGATE = "SELECT * FROM app.create_run(%s, %s, %s, 'investigate', NULL)"
TRANSITION_TO_RETRIEVING = "SELECT app.transition_run(%s, 'QUEUED', 'RETRIEVING', NULL, 1, '{}')"


@asynccontextmanager
async def as_role(conn: persistence.Conn, preset: UUID | None = None) -> AsyncIterator[persistence.Conn]:
    """A transaction on a role connection, optionally with a preset (hostile) session-level tenant."""
    if preset is not None:
        await conn.execute("SELECT set_config('app.tenant_id', %s, false)", (str(preset),))
    try:
        async with conn.transaction():
            yield conn
    finally:
        if preset is not None:
            await conn.execute("SELECT set_config('app.tenant_id', '', false)")


async def refused(conn: persistence.Conn, statement: str, params: tuple[object, ...]) -> str:
    """The SQLSTATE a call raises, run in its own transaction so the aborted transaction never leaks."""
    try:
        async with conn.transaction():
            await conn.execute(statement, params)
    except psycopg.Error as exc:
        return str(exc.sqlstate)
    raise AssertionError("expected a database error")


async def conversation(app_conn: persistence.Conn, tenant: UUID) -> tuple[UUID, UUID]:
    """Insert a conversation and its first message as the superuser; returns their ids."""
    conv, msg = uuid4(), uuid4()
    await app_conn.execute(
        "INSERT INTO app.conversations (conversation_id, tenant_id, created_by) VALUES (%s, %s, %s)",
        (conv, tenant, ALEX),
    )
    await app_conn.execute(
        "INSERT INTO app.messages (message_id, tenant_id, conversation_id, kind, text, author)"
        " VALUES (%s, %s, %s, 'investigate', 'x', %s)",
        (msg, tenant, conv, ALEX),
    )
    return conv, msg


def request(msg: UUID) -> Jsonb:
    """The request document create_run reads: message, requester, asset and a 24-hour window."""
    end = datetime.now(UTC).replace(microsecond=0)
    return Jsonb(
        {
            "message_id": str(msg),
            "requester": str(ALEX),
            "asset_id": "A17",
            "start_at": (end - timedelta(hours=24)).isoformat(),
            "end_at": end.isoformat(),
        }
    )


async def run_count(app_conn: persistence.Conn, conv: UUID) -> int:
    """How many runs a conversation has, read as the superuser."""
    cur = await app_conn.execute("SELECT count(*) AS n FROM app.runs WHERE conversation_id = %s", (conv,))
    return (await cur.fetchone())["n"]


async def create(api: persistence.Conn, tenant: UUID, conv: UUID, msg: UUID) -> UUID:
    """Create a run through the API door and return its id."""
    cur = await api.execute(CREATE_INVESTIGATE, (tenant, conv, request(msg)))
    row = await cur.fetchone()
    assert row is not None and row["state_version"] == 1
    return row["run_id"]


async def test_create_run_is_the_only_door_and_sets_everything_up(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    api, worker = await role_conn(Role.API), await role_conn(Role.WORKER)
    conv, msg = await conversation(app_conn, ALPHA)
    conv_b, msg_b = await conversation(app_conn, BETA)
    run = None
    try:
        async with as_role(api):
            run = await create(api, ALPHA, conv, msg)
        cur = await app_conn.execute("SELECT * FROM app.runs WHERE run_id = %s", (run,))
        row = await cur.fetchone()
        assert row["state"] == "QUEUED" and row["slot_held"] and row["next_event_seq"] == 1
        assert row["intent"] == "investigate"
        cur = await app_conn.execute("SELECT tenant_id FROM app.run_directory WHERE run_id = %s", (run,))
        assert (await cur.fetchone())["tenant_id"] == ALPHA
        cur = await app_conn.execute("SELECT type, dedup_key FROM app.jobs WHERE run_id = %s", (run,))
        assert [(r["type"], r["dedup_key"]) for r in await cur.fetchall()] == [("investigate", f"{run}:1")]
        cur = await app_conn.execute("SELECT type, source, sequence FROM app.events WHERE run_id = %s", (run,))
        events = [(r["type"], r["source"], r["sequence"]) for r in await cur.fetchall()]
        assert events == [("run.accepted", "application", 1)]
        cur = await app_conn.execute(
            "SELECT seq, from_state, to_state, performer FROM app.run_state_history WHERE run_id = %s", (run,)
        )
        assert [tuple(r.values()) for r in await cur.fetchall()] == [(1, None, "QUEUED", "create_run")]
        # The slot rule is the function's refusal, not a bare unique violation.
        assert await refused(api, CREATE_INVESTIGATE, (ALPHA, conv, request(msg))) == "OC005"
        # Wrong caller, wrong tenant, wrong intent.
        assert await refused(worker, CREATE_INVESTIGATE, (ALPHA, conv, request(msg))) == "42501"  # no EXECUTE
        # The superuser passes the ACL and _authority refuses.
        assert await refused(app_conn, CREATE_INVESTIGATE, (ALPHA, conv, request(msg))) == "OC001"
        assert await refused(api, CREATE_INVESTIGATE, (ALPHA, conv_b, request(msg_b))) == "OC002"
        before = await run_count(app_conn, conv)
        bad_doc = Jsonb({"message_id": "x"})
        assert await refused(api, CREATE_INVESTIGATE, (ALPHA, conv, bad_doc)) == "OC005"
        same_instant = Jsonb(
            {**request(msg).obj, "start_at": "2026-01-01T00:00:00+00:00", "end_at": "2026-01-01T00:00:00+00:00"}
        )
        assert await refused(api, CREATE_INVESTIGATE, (ALPHA, conv, same_instant)) == "OC005"
        assert await run_count(app_conn, conv) == before
        guess = "SELECT * FROM app.create_run(%s, %s, %s, 'guess', NULL)"
        assert await refused(api, guess, (BETA, conv_b, request(msg_b))) == "OC005"
        supersede = "SELECT * FROM app.create_run(%s, %s, %s, 'investigate', %s)"
        assert await refused(api, supersede, (BETA, conv_b, request(msg_b), run)) == "OC002"
    finally:
        if run is not None:
            await purge_run(app_conn, run)
        await app_conn.execute("DELETE FROM app.messages WHERE conversation_id IN (%s, %s)", (conv, conv_b))
        await app_conn.execute("DELETE FROM app.conversations WHERE conversation_id IN (%s, %s)", (conv, conv_b))


async def test_transition_run_is_worker_only_pre_grant_only_and_versioned(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    api, worker = await role_conn(Role.API), await role_conn(Role.WORKER)
    conv, msg = await conversation(app_conn, ALPHA)
    async with as_role(api):
        run = await create(api, ALPHA, conv, msg)
    try:
        # R128: the ACL refuses any role but worker; the superuser passes the ACL and _authority refuses.
        assert await refused(api, TRANSITION_TO_RETRIEVING, (run,)) == "42501"
        assert await refused(app_conn, TRANSITION_TO_RETRIEVING, (run,)) == "OC001"
        # A post-grant target, never.
        assert (
            await refused(worker, "SELECT app.transition_run(%s, 'QUEUED', 'EXECUTING', NULL, 1, '{}')", (run,))
            == "OC005"
        )
        # Not a row of the table.
        assert (
            await refused(worker, "SELECT app.transition_run(%s, 'QUEUED', 'DRAFTING', NULL, 1, '{}')", (run,))
            == "OC004"
        )
        # Stale from-state / version.
        stale_from = "SELECT app.transition_run(%s, 'RETRIEVING', 'DRAFTING', NULL, 1, '{}')"
        assert await refused(worker, stale_from, (run,)) == "OC003"
        stale_version = "SELECT app.transition_run(%s, 'QUEUED', 'RETRIEVING', NULL, 7, '{}')"
        assert await refused(worker, stale_version, (run,)) == "OC003"
        cur = await app_conn.execute("SELECT state, state_version FROM app.runs WHERE run_id = %s", (run,))
        assert dict(await cur.fetchone()) == {"state": "QUEUED", "state_version": 1}  # every refusal left the row alone
        async with as_role(worker):
            cur = await worker.execute(TRANSITION_TO_RETRIEVING + " AS v", (run,))
            assert (await cur.fetchone())["v"] == 2
            cur = await worker.execute(
                "SELECT app.transition_run(%s, 'RETRIEVING', 'FAILED', NULL, 2, %s) AS v",
                (run, Jsonb({"message": "retrieval failed"})),
            )
            assert (await cur.fetchone())["v"] == 3
        cur = await app_conn.execute(
            "SELECT state, state_version, slot_held, reason FROM app.runs WHERE run_id = %s", (run,)
        )
        assert dict(await cur.fetchone()) == {"state": "FAILED", "state_version": 3, "slot_held": False, "reason": None}
        cur = await app_conn.execute(
            "SELECT type, sequence, payload FROM app.events WHERE run_id = %s ORDER BY sequence", (run,)
        )
        rows = await cur.fetchall()
        assert [(r["type"], r["sequence"]) for r in rows] == [("run.accepted", 1), ("run.failed", 2)]
        assert rows[1]["payload"] == {"message": "retrieval failed"}
        cur = await app_conn.execute(
            "SELECT seq, to_state, performer FROM app.run_state_history WHERE run_id = %s ORDER BY seq", (run,)
        )
        assert [tuple(r.values()) for r in await cur.fetchall()] == [
            (1, "QUEUED", "create_run"),
            (2, "RETRIEVING", "transition_run"),
            (3, "FAILED", "transition_run"),
        ]
    finally:
        await purge_run(app_conn, run)


async def test_append_event_rules_and_sequence(app_conn: persistence.Conn, role_conn: RoleConn) -> None:
    api, worker, sweeper = await role_conn(Role.API), await role_conn(Role.WORKER), await role_conn(Role.SWEEPER)
    conv, msg = await conversation(app_conn, ALPHA)
    async with as_role(api):
        run = await create(api, ALPHA, conv, msg)
    try:
        append = "SELECT * FROM app.append_event(%s, %s, %s, %s)"
        async with as_role(worker):
            cur = await worker.execute(append, (run, "tool.started", Jsonb({"message": "search"}), "application"))
            assert (await cur.fetchone())["sequence"] == 2
            summary = Jsonb({"message": "m", "evidence_refs": ["a:v1:s"]})
            cur = await worker.execute(append, (run, "explanation.ready", summary, "model_summary"))
            assert (await cur.fetchone())["sequence"] == 3
        for conn, event_type, source, payload in (
            (worker, "Run.failed", "application", {}),  # the allowlist is exact: no case games
            (worker, "made.up", "application", {}),
            (worker, "", "application", {}),
            (worker, "run.failed", "application", {}),  # run.* only from the transition functions (SA:452)
            (worker, "action.granted", "application", {}),
            (worker, "review.blocked", "application", {}),
            (api, "explanation.ready", "model_summary", {"message": "m"}),  # only the worker may say model_summary
            (worker, "tool.started", "model_summary", {"message": "m"}),
            (worker, "tool.started", "destination", {}),
            (worker, "tool.completed", "application", {"receipt": {}}),  # evidence keys on a non-outcome type
            # Refs must be non-empty strings.
            (worker, "explanation.ready", "model_summary", {"message": "m", "evidence_refs": [1, ""]}),
            (sweeper, "tool.started", "application", []),
        ):
            assert await refused(conn, append, (run, event_type, Jsonb(payload), source)) == "OC006", event_type
        async with as_role(sweeper):
            cur = await sweeper.execute(
                "SELECT * FROM app.append_event(%s, 'tool.completed', '{}', 'application')", (run,)
            )
            assert (await cur.fetchone())["sequence"] == 4
        cur = await app_conn.execute("SELECT next_event_seq FROM app.runs WHERE run_id = %s", (run,))
        assert (await cur.fetchone())["next_event_seq"] == 4
        cur = await app_conn.execute(
            "SELECT sequence, type, source FROM app.events WHERE run_id = %s ORDER BY sequence", (run,)
        )
        assert [tuple(r.values()) for r in await cur.fetchall()] == [
            (1, "run.accepted", "application"),
            (2, "tool.started", "application"),
            (3, "explanation.ready", "model_summary"),
            (4, "tool.completed", "application"),
        ]
        # A run of another tenant, by id: not found, never a leak.
        unknown = "SELECT * FROM app.append_event(%s, 'tool.started', '{}', 'application')"
        assert await refused(worker, unknown, (uuid4(),)) == "OC002"
    finally:
        await purge_run(app_conn, run)


async def test_resolve_identity_ignores_a_preset_tenant_and_restores_it(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    api = await role_conn(Role.API)
    issuer = (await (await app_conn.execute(ISSUER_SQL)).fetchone())["issuer"]
    async with as_role(api, preset=BETA):  # a hostile preset: alex is alpha's requester, beta must not hide him
        cur = await api.execute("SELECT * FROM app.resolve_identity(%s, %s)", (issuer, ALEX))
        assert [(r["tenant_id"], r["role"]) for r in await cur.fetchall()] == [(ALPHA, "requester")]
        cur = await api.execute("SELECT current_setting('app.tenant_id', true) AS t")
        assert (await cur.fetchone())["t"] == str(BETA)  # restored by the function attribute (spike §1 D)
    async with as_role(api):
        cur = await api.execute("SELECT * FROM app.resolve_identity(%s, %s)", (issuer, uuid4()))
        assert await cur.fetchall() == []
    worker = await role_conn(Role.WORKER)
    assert await refused(worker, "SELECT * FROM app.resolve_identity(%s, %s)", (issuer, ALEX)) == "42501"


async def test_every_run_path_function_leaves_the_callers_tenant_unchanged(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    """T09 DoD 5: a plain SET in a body would survive the call; the attribute plus set_config(.., true) does not."""
    api, worker = await role_conn(Role.API), await role_conn(Role.WORKER)
    conv, msg = await conversation(app_conn, ALPHA)
    async with as_role(api, preset=BETA):
        run = await create(api, ALPHA, conv, msg)
        cur = await api.execute("SELECT current_setting('app.tenant_id', true) AS t")
        assert (await cur.fetchone())["t"] == str(BETA)
    try:
        calls = (
            (worker, TRANSITION_TO_RETRIEVING, (run,)),
            (worker, "SELECT * FROM app.append_event(%s, 'tool.started', '{}', 'application')", (run,)),
            (worker, "SELECT app.revoke_handles(%s, 1)", (run,)),
        )
        for conn, statement, params in calls:
            async with as_role(conn, preset=BETA):
                await conn.execute(statement, params)
                cur = await conn.execute("SELECT current_setting('app.tenant_id', true) AS t")
                assert (await cur.fetchone())["t"] == str(BETA), statement
    finally:
        await purge_run(app_conn, run)


async def test_revoke_handles_marks_the_runs_live_handles(app_conn: persistence.Conn, role_conn: RoleConn) -> None:
    api, worker = await role_conn(Role.API), await role_conn(Role.WORKER)
    conv, msg = await conversation(app_conn, ALPHA)
    async with as_role(api):
        run = await create(api, ALPHA, conv, msg)
    try:
        job = (await (await app_conn.execute("SELECT id FROM app.jobs WHERE run_id = %s", (run,))).fetchone())["id"]
        for digest in ("a" * 64, "b" * 64):
            await app_conn.execute(
                "INSERT INTO app.invocation_context (handle_sha256, run_id, job_id, server, azp, expires_at)"
                " VALUES (%s, %s, %s, 'read', 'ops-worker', now() + interval '1 minute')",
                (digest, run, job),
            )
        async with as_role(worker):
            cur = await worker.execute("SELECT app.revoke_handles(%s, 1) AS n", (run,))
            assert (await cur.fetchone())["n"] == 2
            cur = await worker.execute("SELECT app.revoke_handles(%s, 1) AS n", (run,))
            assert (await cur.fetchone())["n"] == 0
        cur = await app_conn.execute(
            "SELECT count(*) AS n FROM app.invocation_context WHERE run_id = %s AND revoked_at IS NULL", (run,)
        )
        assert (await cur.fetchone())["n"] == 0
        assert await refused(api, "SELECT app.revoke_handles(%s, 1)", (run,)) == "42501"
    finally:
        await purge_run(app_conn, run)


async def test_function_catalog_shape(app_conn: persistence.Conn) -> None:
    """R106: owner app_definer, SECURITY DEFINER, search_path pinned, the tenant attribute on every granted function,
    PUBLIC revoked everywhere, helpers granted to nobody and carrying no tenant attribute."""
    from ops_core import privileges as p

    cur = await app_conn.execute(
        "SELECT p.proname, p.proowner::regrole::text AS owner, p.prosecdef, p.proconfig, p.proacl::text AS acl"
        " FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = 'app'"
    )
    rows = {r["proname"]: r for r in await cur.fetchall()}
    # Equality, not a subset: a function a later revision drops, or one nobody listed, fails here (final review M4).
    assert set(rows) == set(p.DEFINER_FUNCTIONS) | set(p.HELPER_FUNCTIONS), sorted(rows)
    for name in list(p.DEFINER_FUNCTIONS) + list(p.HELPER_FUNCTIONS):
        row = rows[name]
        assert row["owner"] == "app_definer", name
        assert "search_path=app, pg_temp" in row["proconfig"], name
        entries = row["acl"].strip("{}").split(",")
        assert not any(entry.startswith("=") for entry in entries), (name, row["acl"])  # no PUBLIC entry
        grantees = {entry.split("=")[0] for entry in entries} - {"app_definer"}
        if name.startswith("_"):
            assert grantees == set() and "app.tenant_id=" not in row["proconfig"], name
        else:
            assert row["prosecdef"] and "app.tenant_id=" in row["proconfig"], name
            assert grantees == set(p.DEFINER_FUNCTIONS[name][1]), (name, grantees)


async def test_the_transitions_table_equals_the_python_table(app_conn: persistence.Conn) -> None:
    """R082 one table: the rows the migrations wrote equal ops_core.states.TRANSITIONS (final review I2)."""
    from ops_core.states import TRANSITIONS

    cur = await app_conn.execute("SELECT src, dst, performer, reasons FROM app.transitions")
    stored = sorted((r["src"], r["dst"], r["performer"], tuple(sorted(r["reasons"]))) for r in await cur.fetchall())
    live = sorted(
        (
            row.src.value if row.src is not None else "",
            row.dst.value,
            row.performer.value,
            tuple(sorted(x.value for x in row.reasons)),
        )
        for row in TRANSITIONS
    )
    assert stored == live

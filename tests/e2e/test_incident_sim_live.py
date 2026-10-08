"""The destination's key table as role `incident` on the per-session database (OPS_LIVE=1): first-writer-wins under
real concurrency (R047), POST-vs-abort races and tombstone permanence (R096), the role's inability to delete or
rewrite a key (R096, SA:265), the CHECKs, and the independence of the destination store (R010: the application
database is dropped and recreated every session while incident_test keeps what this test wrote until its own reset).
"""

import asyncio
from collections.abc import Awaitable
from uuid import uuid4

import psycopg
import pytest
from ops_core import persistence, settings
from ops_core.canonical import canonical_sha256
from ops_incident_sim import keys

pytestmark = pytest.mark.asyncio


async def test_commit_replay_conflict_and_isolation(incident_conn: persistence.Conn) -> None:
    action = uuid4()
    payload = {"title": "live", "n": 1}
    first = await keys.commit(
        incident_conn, action_id=action, payload_sha256=canonical_sha256(payload), payload=payload
    )
    again = await keys.commit(
        incident_conn, action_id=action, payload_sha256=canonical_sha256(payload), payload=payload
    )
    assert first == again and first.incident_id.startswith("INC-") and first.state == "COMMITTED"
    other = await keys.commit(incident_conn, action_id=action, payload_sha256="0" * 64, payload={"x": 1})
    assert other == first and keys.document(other, presented_sha256="0" * 64)[0] == 409
    # The real boundary: the destination's credentials cannot even open the application database (ensure_roles
    # narrowed CONNECT); inside its own database there is no `app` schema to see.
    creds = settings.incident_postgres()
    app_db = settings.superuser_postgres().dbname
    foreign = settings.Postgres(creds.host, creds.port, creds.user, app_db, creds.password)
    with pytest.raises(psycopg.OperationalError, match="permission denied for database"):
        await psycopg.AsyncConnection.connect(foreign.conninfo())


async def test_r096_keys_are_permanent_for_the_runtime_role(incident_conn: persistence.Conn) -> None:
    action = uuid4()
    await keys.abort(incident_conn, action_id=action, payload_sha256="a" * 64, reason="expired")
    for statement in (
        "DELETE FROM incident.action_key WHERE action_id = %s",
        "UPDATE incident.action_key SET state = 'COMMITTED' WHERE action_id = %s",
        "UPDATE incident.action_key SET reason = 'x' WHERE action_id = %s",
    ):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            await incident_conn.execute(statement, (action,))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        await incident_conn.execute("TRUNCATE incident.action_key")
    tombstone = await keys.lookup(incident_conn, action)
    assert tombstone is not None and tombstone.state == "ABORTED"
    # A tombstone never carries a receipt or an incident id, even if someone tries.
    with pytest.raises(psycopg.errors.CheckViolation):
        await incident_conn.execute(
            "INSERT INTO incident.action_key (action_id, payload_sha256, state, incident_id)"
            " VALUES (%s, %s, 'REJECTED', 'INC-1')",
            (uuid4(), "b" * 64),
        )
    cur = await incident_conn.execute(
        "SELECT tableowner FROM pg_tables WHERE schemaname = 'incident' AND tablename = 'action_key'"
    )
    owner = await cur.fetchone()
    assert owner is not None and owner["tableowner"] == "incident_owner"


async def in_unit(conn: persistence.Conn, call: Awaitable[keys.KeyRow]) -> keys.KeyRow:
    """Key and incident commit together, as the service does it (BUILD_SPEC §10), so the race is the real one."""
    async with conn.transaction():
        return await call


async def count_incidents(conn: persistence.Conn, action: object) -> int:
    """How many incident rows exist for an action."""
    cur = await conn.execute("SELECT count(*) AS n FROM incident.incidents WHERE action_id = %s", (action,))
    row = await cur.fetchone()
    assert row is not None
    return int(row["n"])


async def test_r047_r096_races_yield_one_terminal_state(incident_conn: persistence.Conn) -> None:
    """Twenty create-vs-abort races and twenty create-vs-create races on two connections (spike §6)."""
    second = await persistence.connect(settings.incident_postgres())
    try:
        for i in range(20):
            action, payload = uuid4(), {"i": i}
            sha = canonical_sha256(payload)
            created, aborted = await asyncio.gather(
                in_unit(
                    incident_conn, keys.commit(incident_conn, action_id=action, payload_sha256=sha, payload=payload)
                ),
                in_unit(second, keys.abort(second, action_id=action, payload_sha256=sha, reason="deadline")),
            )
            final = await keys.lookup(incident_conn, action)
            assert created == aborted == final
            assert final is not None and final.state in ("COMMITTED", "ABORTED")
            assert await count_incidents(incident_conn, action) == (1 if final.state == "COMMITTED" else 0)
        for i in range(20):
            action, payload = uuid4(), {"j": i}
            sha = canonical_sha256(payload)
            a, b = await asyncio.gather(
                in_unit(
                    incident_conn, keys.commit(incident_conn, action_id=action, payload_sha256=sha, payload=payload)
                ),
                in_unit(second, keys.commit(second, action_id=action, payload_sha256=sha, payload=payload)),
            )
            assert a == b and a.state == "COMMITTED"
            assert await count_incidents(incident_conn, action) == 1
    finally:
        await second.close()


async def test_r010_destination_rows_outlive_the_application_store(
    incident_conn: persistence.Conn, app_conn: persistence.Conn
) -> None:
    """Per session, ops_test is dropped and recreated (conftest) while incident_test is only reset by its own fixture;
    inside one session the two stores share nothing: a key exists with no grant anywhere in the application store."""
    action = uuid4()
    await keys.commit(incident_conn, action_id=action, payload_sha256="c" * 64, payload={"r010": True})
    cur = await app_conn.execute("SELECT count(*) AS n FROM app.execution_grant WHERE action_id = %s", (action,))
    grants = await cur.fetchone()
    found = await keys.lookup(incident_conn, action)
    assert grants is not None and grants["n"] == 0 and found is not None and found.state == "COMMITTED"
    from scripts.skeleton import keys as detective

    assert detective() == 1  # the orphan this test planted is reported, exit 1

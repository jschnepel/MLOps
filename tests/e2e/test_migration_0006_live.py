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
    conv: UUID | None = None
    try:
        downgrade("app", superuser, "0005_sessions_login_logout")
        conv = await conversation(app_conn)
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
        try:
            assert migrate(Profile.TEST) == 0  # every later test needs the head
        finally:
            if conv is not None:  # nested, so a failing migrate or a failing first downgrade leaks nothing
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

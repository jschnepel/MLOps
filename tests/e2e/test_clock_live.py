"""app.current_time() and app.test_clock under the test profile (OPS_LIVE=1; AM-20.6, R126).

Catches: a GUC that moves the clock, a runtime role that can write or even read the offset, a harness that cannot,
a clock function that stops working when the table is absent (dev), and a dev skeleton that would start against a
database carrying the table.
"""

from collections.abc import Awaitable, Callable
from datetime import timedelta

import psycopg
import pytest
from ops_core import persistence, settings
from ops_core.settings import Profile, Role

pytestmark = pytest.mark.asyncio

RoleConn = Callable[[Role], Awaitable[persistence.Conn]]


async def clock(conn: persistence.Conn) -> timedelta:
    cur = await conn.execute("SELECT app.current_time() - clock_timestamp() AS delta")
    return (await cur.fetchone())["delta"]


async def test_r126_only_the_harness_moves_the_clock_and_no_guc_does(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    harness = await role_conn(Role.TEST_HARNESS)
    api = await role_conn(Role.API)
    try:
        assert abs(await clock(api)) < timedelta(seconds=1)
        await api.execute("SELECT set_config('app.clock_offset', '99 days', false)")
        await api.execute("SELECT set_config('app.test_clock', '99 days', false)")
        assert abs(await clock(api)) < timedelta(seconds=1)  # GUCs are never read (SA:530)
        await harness.execute("UPDATE app.test_clock SET clock_offset = interval '3 days'")
        for conn in (api, await role_conn(Role.WORKER), await role_conn(Role.MCP_EXEC)):
            assert abs(await clock(conn) - timedelta(days=3)) < timedelta(seconds=1)
        for conn in (api, await role_conn(Role.WORKER), await role_conn(Role.SWEEPER)):
            for statement in (
                "UPDATE app.test_clock SET clock_offset = interval '0'",
                "DELETE FROM app.test_clock",
                "SELECT clock_offset FROM app.test_clock",
            ):
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    await conn.execute(statement)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):  # ins/upd/del, not sel (AM-20.2)
            await harness.execute("SELECT clock_offset FROM app.test_clock")
        with pytest.raises(psycopg.errors.UniqueViolation):  # one row, ever
            await harness.execute("INSERT INTO app.test_clock (clock_offset) VALUES (interval '1 day')")
    finally:
        await harness.execute("UPDATE app.test_clock SET clock_offset = interval '0'")
    assert abs(await clock(api)) < timedelta(seconds=1)


async def test_dev_profile_refuses_a_database_with_the_test_clock(migrated: None) -> None:
    from scripts.skeleton import clock_guard

    superuser = settings.superuser_postgres()
    clock_guard(superuser, Profile.TEST)  # the test profile may run against it
    with pytest.raises(RuntimeError, match="test_clock"):
        clock_guard(superuser, Profile.DEV)

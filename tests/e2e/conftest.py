"""Live fixtures: only with OPS_LIVE=1 and the dev profile up. Secrets are read from files, never printed.

Every live test runs against two per-session databases, `ops_test` and `incident_test`, dropped and recreated here and
migrated under the test profile (so `app.test_clock` exists in them and never in the dev `ops` database, SA:529);
the skeleton processes the R105 module starts inherit the same environment. Seeding and clean-up use the superuser
connection (`app_conn`); assertions about what a role may do use `role_conn`.
"""

import asyncio
import os
import sys
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path

import psycopg
import pytest
import pytest_asyncio
from ops_core import persistence, settings
from ops_core.settings import Profile, Role
from psycopg import sql

if sys.platform == "win32":
    # psycopg async refuses the Proactor loop, and Python's default policy on Windows (and uvicorn.run) picks it
    # (measured in the Plan D spike and its round-1 review). pytest-asyncio builds its loops from the policy, so the
    # selector policy is installed once, here, for every live test on the Windows dev machine.
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

ROOT = Path(__file__).resolve().parent.parent.parent
TEST_DATABASES = {"OPS_PG_DB": "ops_test", "OPS_INCIDENT_PG_DB": "incident_test"}


@pytest.fixture(scope="session")
def live() -> None:
    if os.environ.get("OPS_LIVE") != "1":
        pytest.skip("live walking-skeleton tests run only with OPS_LIVE=1")


@pytest.fixture(scope="session")
def env(live: None) -> dict[str, str]:
    sys.path.insert(0, str(ROOT))
    from scripts.skeleton import export_environment, load_dotenv

    # Before anything reads settings: the per-session databases and the test profile, inherited by child processes.
    os.environ.update(TEST_DATABASES)
    os.environ["PROFILE"] = Profile.TEST.value
    dotenv = load_dotenv(ROOT / ".env")
    export_environment(dotenv)
    return dotenv


@pytest.fixture(scope="session")
def secret(env: dict[str, str]) -> Callable[[str], str]:
    return lambda name: settings.read_secret(name)


def recreate_databases() -> None:
    """Drop and create both test databases from the maintenance database; FORCE ends any leftover session."""
    admin = settings.superuser_postgres()
    maintenance = settings.Postgres(admin.host, admin.port, admin.user, "postgres", admin.password)
    with psycopg.connect(maintenance.conninfo(), autocommit=True) as conn:
        for name in TEST_DATABASES.values():
            conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))
            conn.execute(
                sql.SQL("CREATE DATABASE {} OWNER {}").format(sql.Identifier(name), sql.Identifier(admin.user))
            )


@pytest.fixture(scope="session")
def migrated(env: dict[str, str]) -> None:
    from scripts.skeleton import migrate

    recreate_databases()
    assert migrate(Profile.TEST) == 0


@pytest_asyncio.fixture
async def app_conn(migrated: None) -> AsyncIterator[persistence.Conn]:
    """The superuser on ops_test (bypasses RLS and grants): seeding, purging and catalog assertions. A test that must
    leave nothing behind wraps itself in `async with app_conn.transaction(force_rollback=True)`."""
    conn = await persistence.connect(settings.superuser_postgres())
    try:
        yield conn
    finally:
        await conn.close()


@pytest_asyncio.fixture
async def role_conn(migrated: None) -> AsyncIterator[Callable[[Role], Awaitable[persistence.Conn]]]:
    """A factory of autocommit connections as a runtime role; every connection it opened is closed afterwards."""
    opened: list[persistence.Conn] = []

    async def open_as(role: Role) -> persistence.Conn:
        conn = await persistence.connect(settings.app_postgres(role))
        opened.append(conn)
        return conn

    try:
        yield open_as
    finally:
        for conn in opened:
            await conn.close()


@pytest_asyncio.fixture
async def incident_conn(migrated: None) -> AsyncIterator[persistence.Conn]:
    """Role `incident` on incident_test, the destination's own credentials."""
    conn = await persistence.connect(settings.incident_postgres())
    try:
        yield conn
    finally:
        await conn.close()


PURGE_ORDER = (
    "DELETE FROM app.invocation_context WHERE run_id = %s",
    "DELETE FROM app.events WHERE run_id = %s",
    (
        "DELETE FROM app.action_attempt_state WHERE action_id IN "
        "(SELECT action_id FROM app.execution_grant WHERE run_id = %s)"
    ),
    "DELETE FROM app.action_attempt WHERE action_id IN (SELECT action_id FROM app.execution_grant WHERE run_id = %s)",
    "DELETE FROM app.execution_grant WHERE run_id = %s",
    "DELETE FROM app.decisions WHERE proposal_id IN (SELECT proposal_id FROM app.proposals WHERE run_id = %s)",
    "DELETE FROM app.proposals WHERE run_id = %s",
    "DELETE FROM app.drafts WHERE run_id = %s",
    "DELETE FROM app.jobs WHERE run_id = %s",
    "DELETE FROM app.run_state_history WHERE run_id = %s",
    "DELETE FROM app.run_directory WHERE run_id = %s",  # the directory references runs
)


async def purge_run(conn: persistence.Conn, run_id: object) -> None:
    """Remove one test run, everything hanging off it, and the message and conversation `new_run` made for it
    (reverse foreign-key order). A random tenant is removed by `purge_tenant`; a seeded tenant is never touched.
    This runs as the superuser on the per-session test database, so the grants do not apply; the database is
    dropped at the next session anyway."""
    async with conn.transaction():
        for statement in PURGE_ORDER:
            await conn.execute(statement, (run_id,))
        cur = await conn.execute(
            "DELETE FROM app.runs WHERE run_id = %s RETURNING message_id, conversation_id", (run_id,)
        )
        row = await cur.fetchone()
        if row is not None:
            await conn.execute("DELETE FROM app.messages WHERE message_id = %s", (row["message_id"],))
            await conn.execute("DELETE FROM app.conversations WHERE conversation_id = %s", (row["conversation_id"],))


SEEDED_TENANTS = {"3ea79c95-914c-52cb-9d10-c4e19dda8ff7", "5ab45c2c-1e12-5a0c-a2b9-66cd2ff05201"}


async def purge_tenant(conn: persistence.Conn, tenant_id: object) -> None:
    if str(tenant_id) in SEEDED_TENANTS:
        return  # seeded by the migration; never deleted by a test
    async with conn.transaction():
        await conn.execute("DELETE FROM app.memberships WHERE tenant_id = %s", (tenant_id,))
        await conn.execute("DELETE FROM app.tenants WHERE tenant_id = %s", (tenant_id,))

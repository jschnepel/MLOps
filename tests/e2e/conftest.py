"""Live fixtures for the walking skeleton: only with OPS_LIVE=1 and the dev profile up. Secrets are read from files,
never printed. Task 9 adds the `skeleton` fixture that starts the five processes."""

import asyncio
import os
import sys
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import pytest
import pytest_asyncio
from ops_core import persistence, settings

if sys.platform == "win32":
    # psycopg async refuses the Proactor loop, and Python's default policy on Windows (and uvicorn.run) picks it
    # (measured in the Plan D spike and its round-1 review). pytest-asyncio builds its loops from the policy, so the
    # selector policy is installed once, here, for every live test on the Windows dev machine.
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture(scope="session")
def live() -> None:
    if os.environ.get("OPS_LIVE") != "1":
        pytest.skip("live walking-skeleton tests run only with OPS_LIVE=1")


@pytest.fixture(scope="session")
def env(live: None) -> dict[str, str]:
    sys.path.insert(0, str(ROOT))
    from scripts.skeleton import export_environment, load_dotenv

    dotenv = load_dotenv(ROOT / ".env")
    export_environment(dotenv)
    return dotenv


@pytest.fixture(scope="session")
def secret(env: dict[str, str]) -> Callable[[str], str]:
    return lambda name: settings.read_secret(name)


@pytest.fixture(scope="session")
def migrated(env: dict[str, str]) -> None:
    from scripts.skeleton import migrate

    assert migrate() == 0


@pytest_asyncio.fixture
async def app_conn(migrated: None) -> AsyncIterator[persistence.Conn]:
    """An autocommit connection: a test that must leave nothing behind wraps itself in
    `async with app_conn.transaction(force_rollback=True)`; a test whose rows another process must see cleans up with
    `purge_run` in a `finally`."""
    conn = await persistence.connect(settings.app_postgres())
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
)


async def purge_run(conn: persistence.Conn, run_id: object) -> None:
    """Remove one test run, everything hanging off it, and the message and conversation `new_run` made for it
    (reverse foreign-key order). A random tenant is removed by `purge_tenant`; a seeded tenant is never touched.
    This deletes test-created rows from append-only audit tables as the owner role (ruling 27); T09's grants will
    refuse that, and the live tests then get a per-session schema or a reset."""
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

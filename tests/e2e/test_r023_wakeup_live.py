"""R023 live (OPS_LIVE=1; T21, Plan R ruling 13): an approval's wake-up survives a worker that dies between the
resume's checkpoint and the job's final unit, on LangGraph's Postgres saver against the per-session test database.

The worker resumes the reviewer wait with the decision's event, the saver stores that step, and the process dies
before the execute job's final unit: the job stays claimed and the lease runs out. The sweeper's reclaim hands the
job back, and the next worker (a new graph instance on a new saver connection) carries on from the stored step, whose
one resume write is the accepted `approval.recorded` event, and grants exactly the decided proposal. Catches: a
wake-up lost with the dead worker, a resume with another event, or a grant of anything but the accepted proposal. The
worker has no fault hook (Plan H ruling 20), so the death is a `BaseException` the scripted read raises, which no node
and no handler catches, as a killed process would leave it. The crash points before and after this one are the unit
tests' (`tests/plan_r/test_worker_review.py`).
"""

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any
from uuid import UUID

import psycopg
import pytest
import pytest_asyncio
from ops_core import persistence, settings
from ops_core.outcomes import EventType
from ops_core.settings import Role
from ops_sweeper import leases
from ops_worker import handlers
from ops_worker.drafting import FakeDraftGenerator
from ops_worker.graph import build

from tests.e2e.conftest import expire_lease, purge_conversation
from tests.e2e.test_migrations_and_persistence import new_run
from tests.e2e.test_worker_live import (
    ALPHA,
    GrantThenDownMcp,
    ScriptedMcp,
    approve,
    granting_reads,
    own_job,
    proposal_of,
)

pytestmark = pytest.mark.asyncio
RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
ASSET = "A23"  # an asset of its own: no other module's run can meet this one in the asset guard


class Died(BaseException):
    """The worker process dying: not an Exception, so no node, handler or final unit sees it."""


class DiesAtTheReRead(ScriptedMcp):
    """Answers the investigation's reads; the execute job's asset status read (the first call after the resume's
    checkpoint was stored) kills the worker."""

    async def call(self, url: str, *, handle: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if tool == "get_asset_status" and any(c[1] == "search_procedures" for c in self.calls):
            self.calls.append((url, tool, arguments))
            raise Died
        return await super().call(url, handle=handle, tool=tool, arguments=arguments)


Worker = Callable[[type[ScriptedMcp]], Awaitable[tuple[handlers.Deps, ScriptedMcp]]]


@pytest_asyncio.fixture
async def worker(app_conn: persistence.Conn, role_conn: RoleConn) -> AsyncIterator[Worker]:
    """A factory of worker Deps on the Postgres saver, each on its own connections (a fresh process as far as the graph
    can tell), with a read script the grant accepts; every saver connection is closed at the end."""
    opened: list[psycopg.AsyncConnection[Any]] = []

    async def build_deps(mcp_class: type[ScriptedMcp]) -> tuple[handlers.Deps, ScriptedMcp]:
        conn, saver = await build.open_saver(settings.app_postgres(Role.WORKER))
        opened.append(conn)
        mcp = mcp_class(await role_conn(Role.MCP_READ), await role_conn(Role.MCP_EXEC))
        await granting_reads(app_conn, mcp, ASSET)
        deps = handlers.Deps(
            conn=await role_conn(Role.WORKER),
            mcp=mcp,
            generator=FakeDraftGenerator(),
            urls=settings.urls(),
            worker_name="t",
            workload_azp="ops-worker",
            saver=saver,
        )
        return deps, mcp

    yield build_deps
    for conn in opened:
        await conn.close()


async def test_r023_a_lost_execute_wakeup_resumes_exactly_the_accepted_event(
    app_conn: persistence.Conn,
    role_conn: RoleConn,
    worker: Worker,
    ingested: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resumed_with: list[UUID | None] = []
    real = handlers._approval

    async def spied(*args: Any, **kwargs: Any) -> UUID | None:
        found = await real(*args, **kwargs)
        resumed_with.append(found)
        return found

    monkeypatch.setattr(handlers, "_approval", spied)
    run = None
    try:
        first, first_mcp = await worker(DiesAtTheReRead)
        _, _, run = await new_run(app_conn, ALPHA, api=await role_conn(Role.API), asset_id=ASSET)
        await handlers.handle(first, *await own_job(app_conn, first.conn, run, "investigate"))
        proposal = await proposal_of(app_conn, run)
        await approve(await role_conn(Role.API), proposal)
        cur = await app_conn.execute(
            "SELECT event_id, payload FROM app.events WHERE run_id = %s AND type = %s",
            (run, EventType.APPROVAL_RECORDED.value),
        )
        (accepted,) = await cur.fetchall()
        waiting = str((await persistence.run_row(app_conn, run))["checkpoint_id"])  # the reviewer wait
        job, lease = await own_job(app_conn, first.conn, run, "execute")
        with pytest.raises(Died):
            await handlers.handle(first, job, lease)
        assert [c[1] for c in first_mcp.calls][-1] == "get_asset_status"  # it died at the re-read, before the grant
        # The resume's step was stored, and its id recorded on the run, before the death (SA:211).
        resumed = str((await persistence.run_row(app_conn, run))["checkpoint_id"])
        cur = await app_conn.execute(
            "SELECT count(*) AS n FROM checkpoints.checkpoints WHERE thread_id = %s AND checkpoint_id = %s",
            (build.thread_id(run, 1), resumed),
        )
        assert resumed > waiting and (await cur.fetchone())["n"] == 1  # ids are time-ordered (uuid6)
        cur = await app_conn.execute("SELECT claimed_by, done_at FROM app.jobs WHERE id = %s", (job["id"],))
        assert dict(await cur.fetchone()) == {"claimed_by": "t", "done_at": None}  # no final unit ran
        # The sweeper's reclaim hands the job back once the dead worker's lease has run out (SA:471).
        await expire_lease(app_conn, run)
        assert job["id"] in await leases.reclaim(await role_conn(Role.SWEEPER))
        second, _ = await worker(GrantThenDownMcp)
        await handlers.handle(second, *await own_job(app_conn, second.conn, run, "execute"))
        # The event was consumed once: the second job forks from the stored step after the resume (SA:214) and
        # never resumes again, and the saver's one resume write carries the accepted event's id.
        assert resumed_with == [accepted["event_id"]]
        cur = await app_conn.execute(
            "SELECT blob FROM checkpoints.checkpoint_writes WHERE thread_id = %s AND channel = '__resume__'",
            (build.thread_id(run, 1),),
        )
        (write,) = await cur.fetchall()
        assert str(accepted["event_id"]).encode() in bytes(write["blob"])
        cur = await app_conn.execute("SELECT proposal_id FROM app.execution_grant WHERE run_id = %s", (run,))
        grants = [r["proposal_id"] for r in await cur.fetchall()]
        assert grants == [proposal["proposal_id"]] == [UUID(accepted["payload"]["proposal_id"])]
        assert (await persistence.run_row(app_conn, run))["state"] == "EXECUTING"
    finally:
        if run is not None:
            for table in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
                await app_conn.execute(
                    f"DELETE FROM checkpoints.{table} WHERE thread_id = %s", (build.thread_id(run, 1),)
                )
            cur = await app_conn.execute("SELECT conversation_id FROM app.runs WHERE run_id = %s", (run,))
            found = await cur.fetchone()
            if found is not None:
                await purge_conversation(app_conn, found["conversation_id"])

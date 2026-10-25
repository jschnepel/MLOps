"""A stale sync defers execution instead of failing it (ruling 14): mcp-write maps MEMBERSHIP_STALE to the
retryable tool error GRANT_DEFERRED and the worker re-queues such an envelope the way it re-queues a transport
failure; every other refusal stays GRANT_REFUSED and final."""

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID, uuid4

import pytest
from ops_core import persistence, settings
from ops_core.lease import Lease
from ops_core.states import Intent, RunState
from ops_mcp_write.server import refusal_error
from ops_worker import handlers
from ops_worker.handlers import EXECUTE_RETRY_SECONDS, is_deferred


def test_stale_membership_is_the_one_deferred_refusal() -> None:
    deferred = refusal_error("MEMBERSHIP_STALE")
    assert deferred == {"code": "GRANT_DEFERRED", "message": "grant deferred: MEMBERSHIP_STALE", "retryable": True}
    for code in ("MEMBERSHIP_INACTIVE", "NO_APPROVAL", "CANCELLED", "OTHER_PROPOSAL"):
        refused = refusal_error(code)
        assert refused["code"] == "GRANT_REFUSED" and refused["retryable"] is False and code in refused["message"]


def test_worker_recognises_a_deferred_envelope_only() -> None:
    assert is_deferred({"status": "error", "error": {"code": "GRANT_DEFERRED", "retryable": True}})
    assert not is_deferred({"status": "error", "error": {"code": "GRANT_REFUSED", "retryable": False}})
    assert not is_deferred({"status": "ok", "data": {"status": "SUCCEEDED"}})
    assert not is_deferred({"status": "outcome", "data": {"status": "UNKNOWN"}, "error": None})


class FakeConn:
    """A connection whose transactions do nothing; the persistence calls are replaced in the test."""

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        """An empty unit of work."""
        yield


class DeferringMcp:
    """mcp-write answering a stale membership sync with the GRANT_DEFERRED envelope."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def call(self, url: str, *, handle: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Record the tool and defer."""
        self.calls.append(tool)
        return {"status": "error", "error": refusal_error("MEMBERSHIP_STALE")}


@pytest.mark.asyncio
async def test_execute_requeues_a_deferred_grant_and_releases_its_lease(monkeypatch: pytest.MonkeyPatch) -> None:
    """Parked item 4, under T13's lease: the deferred branch re-queues in 30 s through the job's final unit (handles
    revoked, lease released, Plan H ruling 28), records no UNKNOWN and returns False, so `handle` does not finish
    the job a second time."""
    calls: dict[str, list[Any]] = {"release_lease": [], "mark_unknown": [], "fenced": []}
    run_id, job_id, tenant = uuid4(), uuid4(), uuid4()
    lease = Lease(run_id=run_id, owner="worker:test", fence=2, lease_seconds=30, started=time.monotonic())

    async def run_row(_conn: Any, rid: UUID, *, lock: bool = False) -> dict[str, Any]:
        return {"run_id": rid, "state": RunState.APPROVED.value, "active_proposal_id": uuid4()}

    async def mint_handle(_conn: Any, **kwargs: Any) -> str:
        assert kwargs["fence"] == 2  # the handle carries the lease's fence
        return "handle"

    async def set_tenant(_conn: Any, _tid: UUID) -> None:
        return None

    async def fenced(_conn: Any, held: Lease) -> None:
        calls["fenced"].append(held.fence)

    async def release_lease(
        _conn: Any, held: Lease, *, job: dict[str, Any], requeue_seconds: int | None = None
    ) -> None:
        calls["release_lease"].append((held.fence, job["id"], requeue_seconds))

    async def mark_unknown(*args: Any) -> None:
        calls["mark_unknown"].append(args)

    async def graph_facts(_conn: Any, _rid: UUID) -> persistence.GraphFacts:  # T20: the graph's router reads these
        return persistence.GraphFacts(RunState.APPROVED, Intent.INVESTIGATE, True, None, None)

    async def store_checkpoint_id(_conn: Any, _rid: UUID, _checkpoint_id: str) -> None:
        return None

    for name, fn in {
        "run_row": run_row,
        "mint_handle": mint_handle,
        "set_tenant": set_tenant,
        "fenced": fenced,
        "release_lease": release_lease,
        "mark_unknown": mark_unknown,
        "graph_facts": graph_facts,
        "store_checkpoint_id": store_checkpoint_id,
    }.items():
        monkeypatch.setattr(persistence, name, fn)
    conn: Any = FakeConn()
    mcp = DeferringMcp()
    no_generator: Any = None  # the execute path never drafts
    deps = handlers.Deps(
        conn=conn,
        mcp=mcp,
        generator=no_generator,
        urls=settings.urls(),
        worker_name="worker:test",
        workload_azp="ops-worker",
    )
    job = {"id": job_id, "run_id": run_id, "tenant_id": tenant, "type": "execute"}
    assert await handlers.execute(deps, job, lease) is False
    assert mcp.calls == ["create_incident"] and set(calls["fenced"]) == {2}  # every unit at the job's fence
    assert calls["release_lease"] == [(2, job_id, EXECUTE_RETRY_SECONDS)]
    assert EXECUTE_RETRY_SECONDS == 30 and calls["mark_unknown"] == []

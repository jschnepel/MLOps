"""A stale sync defers execution instead of failing it (ruling 14): mcp-write maps MEMBERSHIP_STALE to the
retryable tool error GRANT_DEFERRED and the worker re-queues such an envelope the way it re-queues a transport
failure; every other refusal stays GRANT_REFUSED and final."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID, uuid4

import pytest
from ops_core import persistence, settings
from ops_core.states import RunState
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
async def test_execute_requeues_a_deferred_grant_and_revokes_its_handles(monkeypatch: pytest.MonkeyPatch) -> None:
    """Parked item 4: the worker's deferred branch re-queues in 30 s with the handles revoked, records no UNKNOWN
    and leaves the job open (execute returns False, so `handle` does not finish it)."""
    calls: dict[str, list[Any]] = {"revoke_handles": [], "requeue_job": [], "mark_unknown": [], "set_tenant": []}
    run_id, job_id, tenant = uuid4(), uuid4(), uuid4()

    async def run_row(_conn: Any, rid: UUID, *, lock: bool = False) -> dict[str, Any]:
        return {"run_id": rid, "state": RunState.APPROVED.value, "active_proposal_id": uuid4()}

    async def mint_handle(_conn: Any, **_: Any) -> str:
        return "handle"

    async def record(name: str, *args: Any) -> None:
        calls[name].append(args)

    async def set_tenant(_conn: Any, tid: UUID) -> None:
        await record("set_tenant", tid)

    async def revoke_handles(_conn: Any, rid: UUID) -> int:
        await record("revoke_handles", rid)
        return 1

    async def requeue_job(_conn: Any, jid: UUID, delay: int) -> None:
        await record("requeue_job", jid, delay)

    async def mark_unknown(_conn: Any, rid: UUID) -> RunState:
        await record("mark_unknown", rid)
        return RunState.OUTCOME_UNKNOWN

    for name, fn in {
        "run_row": run_row,
        "mint_handle": mint_handle,
        "set_tenant": set_tenant,
        "revoke_handles": revoke_handles,
        "requeue_job": requeue_job,
        "mark_unknown": mark_unknown,
    }.items():
        monkeypatch.setattr(persistence, name, fn)
    conn: Any = FakeConn()
    mcp = DeferringMcp()
    no_generator: Any = None  # the execute path never drafts
    deps = handlers.Deps(conn=conn, mcp=mcp, generator=no_generator, urls=settings.urls(), worker_name="worker:test")
    job = {"id": job_id, "run_id": run_id, "tenant_id": tenant, "type": "execute"}
    assert await handlers.execute(deps, job) is False
    assert mcp.calls == ["create_incident"]
    assert calls["revoke_handles"] == [(run_id,)] and calls["requeue_job"] == [(job_id, EXECUTE_RETRY_SECONDS)]
    assert EXECUTE_RETRY_SECONDS == 30 and calls["mark_unknown"] == []

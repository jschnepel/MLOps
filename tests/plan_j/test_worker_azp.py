"""The worker binds every handle it mints to its own workload client, not to a literal (Plan J ruling 17), and never
hands a handle to the model (R027: "handle absent from model").

Catches: an `azp` written into `invocation_context` that differs from the client id the worker's tokens are issued
to, which `_resolve_handle` compares with the presented token's `azp`: a renamed client would refuse every call, and
a literal would keep accepting a client the worker no longer uses; and a field added to the model's request that could
carry a handle.
"""

import asyncio
from dataclasses import fields
from typing import Any

import pytest
from ops_core import persistence
from ops_worker import handlers
from ops_worker.drafting import DraftRequest

from tests.plan_h.test_worker_units import JOB, RUN, Log, make, patch


def capture_mints(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Replace mint_handle (after `patch`) with one that records its keyword arguments."""
    minted: list[dict[str, Any]] = []

    async def mint_handle(_conn: Any, **kwargs: Any) -> str:
        minted.append(kwargs)
        return "handle"

    monkeypatch.setattr(persistence, "mint_handle", mint_handle)
    return minted


@pytest.mark.parametrize(("job_type", "state"), [("investigate", "QUEUED"), ("execute", "APPROVED")])
def test_a_minted_handle_carries_the_workload_client(
    monkeypatch: pytest.MonkeyPatch, job_type: str, state: str
) -> None:
    log = Log()
    patch(monkeypatch, log)
    minted = capture_mints(monkeypatch)

    async def run_row(_conn: Any, _run_id: Any, *, lock: bool = False) -> dict[str, Any]:
        return {**RUN, "state": state}

    monkeypatch.setattr(persistence, "run_row", run_row)
    deps, lease = make(log)
    deps.workload_azp = "ops-worker-renamed"
    asyncio.run(handlers.handle(deps, {**JOB, "type": job_type}, lease))
    assert [m["azp"] for m in minted] == ["ops-worker-renamed"]


def test_the_model_request_has_no_field_for_a_handle() -> None:
    assert [f.name for f in fields(DraftRequest)] == ["asset_id", "text", "start_at", "end_at"]

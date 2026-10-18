"""The worker binds every handle it mints to its own workload client, not to a literal (Plan J ruling 17), and never
hands a handle to the model (R027: "handle absent from model").

Catches: an `azp` written into `invocation_context` that is not the client id of the token source the worker presents
(`_resolve_handle` compares the two), and a field added to the model's request that could carry a handle. It proves
only that the mint follows the token source. The mint is one of four places a rename of the worker client touches; the
other three follow `settings.workload_client_id()` since T47 (the token source and both verifiers,
tests/plan_k/test_workload_client.py) or compare the presented token's `azp` (the write-path definers, revision 0010).
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

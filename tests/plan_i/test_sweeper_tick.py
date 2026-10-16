"""The sweeper's tick after T14 (Plan I rulings 15 and 19; round 1, I1), without a database: this minute's audit row,
then the outbox's delivery, then its dead letters' events, and the default sink.

Catches: a dead letter announced before its result unit, a maintenance row left unrecorded when a delivery fails,
and a production sink that carries a fault hook.
"""

import asyncio
from typing import Any
from uuid import UUID

import pytest
from ops_sweeper import main, outbox


def deps() -> main.Deps:
    none: Any = None
    return main.Deps(conn=none, admin=none, issuer="iss", tick_seconds=30.0, worker_name="sweeper:test")


def test_the_default_sink_is_the_log_sink_without_faults() -> None:
    sink = deps().sink
    assert isinstance(sink, outbox.LogSink) and sink.faults is None  # no fault outside a test's own sink


def test_the_record_comes_first_then_delivery_then_the_announcements(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []

    async def deliver(_conn: Any, _sink: Any, _chosen: Any) -> list[outbox.Result]:
        order.append("deliver")
        return []

    async def notify(_conn: Any) -> list[UUID]:
        order.append("notify")
        return []

    async def record(_deps: Any, job_type: Any) -> None:
        order.append(f"record {job_type.value}")

    monkeypatch.setattr(outbox, "deliver", deliver)
    monkeypatch.setattr(outbox, "notify_dead_letters", notify)
    monkeypatch.setattr(main, "record", record)
    asyncio.run(main.deliver_outbox(deps()))
    assert order == ["record deliver_outbox", "deliver", "notify"]

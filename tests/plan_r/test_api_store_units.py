"""T21's database unit (`DbUnit`) mapping of the definers' refusals, without a database: the persistence functions are
replaced, so only the unit's own decisions are under test (Plan R rulings 2, 6, 7 and 12; note 4).

Catches: a refusal that can only come from a payload the API built itself (PAYLOAD_RUN_MISMATCH, INTERVAL,
SUPERSEDES_MISMATCH, WORKFLOW_VERSION, EXPIRY) answered as the client's recorded 409 instead of a server defect; a
client refusal (NOT_AUTHOR, AUTHOR_LIMIT) that is recorded when it is the caller's or unrecorded when it is the run's;
a manual proposal whose interval is not the run's answered with anything but the asset mismatch's 404; a
superseded-run 404 told apart from the run's by the wording of an exception instead of its DETAIL.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

import pytest
from ops_api import store
from ops_core import persistence
from ops_core.contracts import ErrorCode, ManualProposalRequest, RevisionRequest
from ops_core.states import RunState

START = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
END = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
TENANT = uuid4()
AUTHOR = uuid4()


class FakeConn:
    """Only what the unit asks of its connection: a savepoint that counts its rollbacks."""

    def __init__(self) -> None:
        self.rollbacks = 0

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        try:
            yield
        except BaseException:
            self.rollbacks += 1
            raise


def unit() -> tuple[store.DbUnit, FakeConn]:
    conn = FakeConn()
    return store.DbUnit(cast("persistence.Conn", conn), TENANT), conn


def request(asset: str = "A17", start: datetime = START, end: datetime = END) -> ManualProposalRequest:
    return ManualProposalRequest(
        run_id=uuid4(),
        asset_id=asset,
        start_at=start,
        end_at=end,
        title="Review the warnings",
        summary="Two warnings in the interval.",
        evidence_refs=["ALPHA-INCIDENT:v2:review"],
        assumptions=[],
        limitations=["Written by a person."],
    )


def facts() -> persistence.ManualFacts:
    snapshot = {"evidence_id": "ALPHA-INCIDENT:v2:review", "content_sha256": "a" * 64, "version": "v2"}
    return persistence.ManualFacts(1, "wf-1", None, "A17", START, END, END, [snapshot])


def script(monkeypatch: pytest.MonkeyPatch, *, freeze: Exception | None) -> list[bytes]:
    """The definers' two calls: the facts, then a freeze that raises `freeze` (or returns a frozen proposal)."""
    frozen_payloads: list[bytes] = []

    async def prepare(conn: object, **_: Any) -> persistence.ManualFacts:
        return facts()

    async def create(conn: object, *, payload_canonical: bytes, **_: Any) -> persistence.Frozen:
        frozen_payloads.append(payload_canonical)
        if freeze is not None:
            raise freeze
        return persistence.Frozen(uuid4(), 1, RunState.AWAITING_APPROVAL, None, 6)

    monkeypatch.setattr(persistence, "prepare_manual_proposal", prepare)
    monkeypatch.setattr(persistence, "create_manual_proposal", create)
    return frozen_payloads


@pytest.mark.parametrize(
    "code", ["PAYLOAD_RUN_MISMATCH", "INTERVAL", "SUPERSEDES_MISMATCH", "WORKFLOW_VERSION", "EXPIRY"]
)
@pytest.mark.asyncio
async def test_a_refusal_of_a_payload_the_api_built_is_a_server_defect(
    monkeypatch: pytest.MonkeyPatch, code: str
) -> None:
    script(monkeypatch, freeze=persistence.Refused(code))
    the_unit, conn = unit()
    with pytest.raises(store.Internal) as raised:
        await the_unit.manual_proposal(author=AUTHOR, request=request())
    assert not isinstance(raised.value, store.Recorded) and conn.rollbacks == 1  # unrecorded, the savepoint undone


@pytest.mark.asyncio
async def test_a_refusal_of_the_caller_is_forbidden_and_one_of_the_runs_state_is_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script(monkeypatch, freeze=persistence.Refused("NOT_AUTHOR"))
    with pytest.raises(store.Forbidden):
        await unit()[0].manual_proposal(author=AUTHOR, request=request())
    script(monkeypatch, freeze=persistence.Refused("AUTHOR_LIMIT"))
    with pytest.raises(store.Recorded) as raised:
        await unit()[0].manual_proposal(author=AUTHOR, request=request())
    assert raised.value.status == 409 and raised.value.code is ErrorCode.AUTHOR_LIMIT


@pytest.mark.asyncio
async def test_another_asset_or_another_interval_is_the_same_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent = script(monkeypatch, freeze=None)
    answers = []
    for asked in (request("B22"), request(start=START.replace(hour=13))):
        the_unit, conn = unit()
        with pytest.raises(store.Recorded) as raised:
            await the_unit.manual_proposal(author=AUTHOR, request=asked)
        answers.append((raised.value.status, raised.value.code, raised.value.message))
        assert conn.rollbacks == 1
    assert answers[0] == answers[1] == (404, ErrorCode.NOT_FOUND, "no such run, asset or permitted section")
    assert sent == []  # the freeze was never reached


@pytest.mark.asyncio
async def test_a_matching_manual_proposal_is_frozen(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = script(monkeypatch, freeze=None)
    frozen = await unit()[0].manual_proposal(author=AUTHOR, request=request())
    assert frozen.proposal_id is not None and len(sent) == 1


@pytest.mark.asyncio
async def test_the_superseded_runs_404_is_told_from_the_runs_by_its_detail(monkeypatch: pytest.MonkeyPatch) -> None:
    async def gone(conn: object, **_: Any) -> persistence.Revised:
        raise persistence.NotFound("not_found: supersedes_run_id", detail="supersedes_run_id")

    monkeypatch.setattr(persistence, "create_revision", gone)
    with pytest.raises(store.Recorded) as raised:
        await unit()[0].revise(run_id=uuid4(), author=AUTHOR, request=RevisionRequest(expected_version=5))
    assert raised.value.status == 404 and raised.value.message == "no such superseded run"

    async def no_run(conn: object, **_: Any) -> persistence.Revised:
        raise persistence.NotFound("run not found supersedes_run_id")  # a message that merely ends alike

    monkeypatch.setattr(persistence, "create_revision", no_run)
    with pytest.raises(store.Recorded) as other:
        await unit()[0].revise(run_id=uuid4(), author=AUTHOR, request=RevisionRequest(expected_version=5))
    assert other.value.message == "no such run"


def test_a_translated_not_found_carries_the_definers_detail() -> None:
    class Diag:
        message_primary = "not_found"
        message_detail = "supersedes_run_id"

    class Error:
        sqlstate = "OC002"
        diag = Diag()

    mapped = persistence.translate(cast("Any", Error()))
    assert isinstance(mapped, persistence.NotFound) and mapped.detail == "supersedes_run_id"

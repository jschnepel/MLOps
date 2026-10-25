"""The evidence bundle's code rule, what reaches the model, and how a failed read is told apart (T20; SA:377; BS:419,
BS:552; Plan Q ruling 3), without a database or a network.

Catches: a sufficiency verdict that is a judgement rather than SA:377's rule (an `unavailable` status, a stale status,
a stale or empty search counted as evidence); an alert list that reaches the model unbounded or without its
truncation notice; a status or alert that the model could cite; an answer_only run whose payload does not say so; a
fake route that proposes on an answer_only run; and a 401 from the read server that the client cannot tell apart from
a transport failure (one is final, the other worth a retry).
"""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx2
import pytest
from ops_core import draft_validation
from ops_core.routing import ModelRoute
from ops_worker import evidence
from ops_worker.drafting import DraftRequest, EvidenceItem, FakeDraftGenerator, Observation
from ops_worker.mcp import HTTP_REJECTED, TRANSPORT, UNAUTHENTICATED, HttpMcpCaller, McpCallFailed
from ops_worker.ollama_drafting import ANSWER_ONLY_NOTE, payload

from tests.plan_h.test_worker_units import SEARCH
from tests.plan_q.fixtures import ALERTS, AT, STATUS

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


def status(**data: Any) -> dict[str, Any]:
    return {**STATUS, "data": {**STATUS["data"], **data}}


def test_sufficiency_is_the_code_rule() -> None:
    assert evidence.sufficient(STATUS, SEARCH)
    assert not evidence.sufficient(status(state="unavailable"), SEARCH)  # observes nothing
    assert not evidence.sufficient(status(observed_at="2026-10-08T11:54:59Z"), SEARCH)  # 5 min 1 s old
    assert evidence.sufficient(status(observed_at="2026-10-08T11:55:00Z"), SEARCH)  # exactly at the bound
    assert not evidence.sufficient(STATUS, {**SEARCH, "data": {**SEARCH["data"], "results": []}})
    stale = [{**SEARCH["data"]["results"][0], "retrieved_at": "2026-10-08T11:00:00Z"}]
    assert not evidence.sufficient(STATUS, {**SEARCH, "data": {**SEARCH["data"], "results": stale}})


def test_alerts_are_bounded_newest_first_with_a_truncation_notice() -> None:
    alert = ALERTS["data"]["alerts"][0]
    many = [{**alert, "occurred_at": f"2026-10-08T0{h}:00:00Z", "code": f"C{h}"} for h in range(6)]
    seen = evidence.observations(STATUS, {**ALERTS, "data": {**ALERTS["data"], "alerts": many, "next_cursor": "n"}})
    assert [o.section for o in seen] == ["asset status", *["alert"] * evidence.ALERTS_SHOWN, "alerts not shown"]
    assert seen[1].excerpt.startswith("2026-10-08T05:00:00Z C5")  # newest first
    assert seen[-1].excerpt == "2 more alert records were not shown; further pages were not read"
    assert len(seen) - 1 + 3 <= 8  # BS:551: at most 8 references with the three procedure sections


def request(answer_only: bool) -> DraftRequest:
    shown = (Observation("asset status", "3", "warning at " + AT),)
    return DraftRequest("A17", "Is A17 fine?", NOW - timedelta(hours=24), NOW, answer_only, None, shown)


ITEM = EvidenceItem("ALPHA-INCIDENT:v2:review", "ALPHA-INCIDENT", "2", "review", "0" * 64, "text")


def test_the_payload_shows_observations_uncitable_and_says_answer_only() -> None:
    sent = payload(request(answer_only=True), [ITEM])
    assert sent["confirmed_request"] == f"Is A17 fine?\n\n{ANSWER_ONLY_NOTE}"
    assert sent["allowed_evidence_ids"] == ["ALPHA-INCIDENT:v2:review"]  # the status is not citable
    assert sent["permitted_evidence"][1] == {
        "document_id": "asset-sim",
        "version": "3",
        "section": "asset status",
        "excerpt": "warning at " + AT,
    }
    assert payload(request(answer_only=False), [ITEM])["confirmed_request"] == "Is A17 fine?"
    assert set(sent) == {
        "confirmed_request",
        "asset_id",
        "interval",
        "permitted_evidence",
        "allowed_evidence_ids",
        "requested_output_schema",
    }  # the starter's keys, unchanged (no new prompt version)


def test_the_fake_route_answers_an_answer_only_run_and_proposes_otherwise() -> None:
    fake = FakeDraftGenerator()
    assert fake.route is ModelRoute.FAKE
    answer = asyncio.run(fake.generate(request(answer_only=True), [ITEM]))
    assert answer.kind == "answer"
    # The claim the starter makes: what the fake answers on an answer_only run passes the validator that runs there.
    checked = draft_validation.validate(
        answer.model_dump_json(exclude_none=True),
        reasoning=None,
        allowed_ids=frozenset({ITEM.evidence_id}),
        answer_only=True,
    )
    assert checked.kind == "answer"
    assert asyncio.run(fake.generate(request(answer_only=False), [ITEM])).kind == "proposal"


def test_a_401_from_the_read_server_is_told_apart_from_a_transport_failure() -> None:
    class Token:
        async def token(self) -> str:
            return "workload-token"

    def answer(code: int) -> Any:
        return httpx2.MockTransport(lambda _request: httpx2.Response(code))

    async def call(code: int) -> McpCallFailed:
        caller = HttpMcpCaller(Token(), transport=answer(code))
        with pytest.raises(McpCallFailed) as failed:
            await caller.call("http://127.0.0.1:9/mcp", handle="h", tool="get_asset_status", arguments={})
        return failed.value

    refused, broken = asyncio.run(call(401)), asyncio.run(call(503))
    assert (refused.code, refused.retryable) == (UNAUTHENTICATED, False)
    assert (broken.code, broken.retryable) == (TRANSPORT, True)


def test_alerts_sort_by_instant_whatever_their_spelling() -> None:
    """T3 review, M3: `...:00.5Z` is later than `...:00Z`, and `+00:00` is `Z`; sorted as text they are not."""
    alert = ALERTS["data"]["alerts"][0]
    spellings = ["2026-10-08T09:00:00Z", "2026-10-08T09:00:00.5Z", "2026-10-08T10:00:00+00:00", "2026-10-08T08:00:00Z"]
    rows = [{**alert, "occurred_at": at, "code": f"C{i}"} for i, at in enumerate(spellings)]
    seen = evidence.observations(STATUS, {**ALERTS, "data": {**ALERTS["data"], "alerts": rows}})
    assert [o.excerpt.split(": ")[0].split()[1] for o in seen[1:]] == ["C2", "C1", "C0", "C3"]


def test_a_further_page_with_nothing_left_out_says_so_plainly() -> None:
    """T3 review, M4: four or fewer alerts in hand and a next page is not "0 more alert records were not shown"."""
    paged = {**ALERTS, "data": {**ALERTS["data"], "next_cursor": "n"}}
    notice = evidence.observations(STATUS, paged)[-1]
    assert (notice.section, notice.excerpt) == ("alerts not shown", "further alert records exist and were not read")
    assert evidence.observations(STATUS, ALERTS)[-1].section == "alert"  # no next page, nothing left out: no notice


def test_a_4xx_is_final_and_a_write_failure_is_never_marked_retryable() -> None:
    """T3 review, M1 and M2 (BS:552): connection errors, timeouts and 5xx are worth a retry; any other 4xx is a
    refusal of the request itself, with its own code; a write tool's failure never sets `retryable`."""

    class Token:
        async def token(self) -> str:
            return "workload-token"

    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused", request=request)

    async def failure(tool: str, transport: httpx2.MockTransport) -> McpCallFailed:
        caller = HttpMcpCaller(Token(), transport=transport)
        with pytest.raises(McpCallFailed) as failed:
            await caller.call("http://127.0.0.1:9/mcp", handle="h", tool=tool, arguments={})
        return failed.value

    def answers(code: int) -> httpx2.MockTransport:
        return httpx2.MockTransport(lambda _request: httpx2.Response(code))

    def outcome(tool: str, transport: httpx2.MockTransport) -> tuple[str | None, bool]:
        failed = asyncio.run(failure(tool, transport))
        return failed.code, failed.retryable

    read = "get_asset_status"
    assert outcome(read, answers(400)) == (HTTP_REJECTED, False)  # a protocol-version mismatch is permanent
    assert outcome(read, answers(404)) == (HTTP_REJECTED, False)
    assert outcome(read, answers(429)) == (TRANSPORT, True)  # "too many requests" is worth a later try
    assert outcome(read, answers(503)) == (TRANSPORT, True)
    assert outcome(read, httpx2.MockTransport(refuse)) == (TRANSPORT, True)
    assert outcome(read, answers(401)) == (UNAUTHENTICATED, False)
    assert outcome("create_incident", answers(503)) == (TRANSPORT, False)  # a write's outcome is never a plain retry
    assert outcome("create_incident", httpx2.MockTransport(refuse)) == (TRANSPORT, False)

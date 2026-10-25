"""T21's contracts and wrappers without a database (Plan R rulings 3, 7, 8, 9, 11; errata 131-137).

Catches: a decision conflict whose code is lost on its way from the definer (the API could only answer one generic
409); a grant whose committed refusal reads as a grant, or whose reason is not an AM-10 grant reason; a manual
proposal without its run or a search with a vector mode or an unbounded limit; a feedback key that another event type
may carry; the new error codes missing from `error.schema.json`; an execute job that cannot read the asset status
before its grant; and a manual-path run that the graph router would send back to the model.
"""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from ops_core import contracts as c
from ops_core import persistence
from ops_core.jobs import JOB_RULES, JobType, Tool
from ops_core.outcomes import EventRuleViolation, EventSource, EventType, event_rules_ok
from ops_core.routing import DraftKind, Evidence, GraphKey, GraphRoute, route_graph
from ops_core.states import GRANT_REFUSALS, TRANSITIONS, AttemptState, Intent, Performer, Reason, RunState
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)


def refusal(sqlstate: str, detail: str) -> Exception | None:
    """The typed exception `translate` makes of a definer's refusal."""
    diag = SimpleNamespace(message_detail=detail, message_primary="version_conflict")
    exc = type("FakeError", (psycopg.DatabaseError,), {"diag": property(lambda self: diag)})("x")
    exc.sqlstate = sqlstate
    return persistence.translate(exc)


@pytest.mark.parametrize("code", ["ALREADY_DECIDED", "STALE_REVISION", "STALE_HASH", "EXPIRED"])
def test_each_decision_conflict_keeps_its_code(code: str) -> None:
    mapped = refusal("OC003", code)
    assert isinstance(mapped, persistence.VersionConflict) and mapped.code == code
    assert c.ErrorCode(code).value == code  # the API answers it under its own name (ruling 3)


@pytest.mark.parametrize("detail", ["revision", "run 7 is DRAFTING at version 3", "already_decided", ""])
def test_a_conflict_detail_that_is_not_a_decision_code_has_no_code(detail: str) -> None:
    mapped = refusal("OC003", detail)  # `code` feeds ErrorCode(...): only the four decision codes may reach it
    assert isinstance(mapped, persistence.VersionConflict) and mapped.code is None
    assert persistence.DECISION_CONFLICTS == {"ALREADY_DECIDED", "STALE_REVISION", "STALE_HASH", "EXPIRED"}


def test_the_new_codes_are_in_the_error_schema() -> None:
    schema = json.loads((ROOT / "schemas" / "error.schema.json").read_text(encoding="utf-8"))
    codes = set(schema["properties"]["code"]["enum"])
    assert {"ALREADY_DECIDED", "STALE_REVISION", "STALE_HASH", "EXPIRED", "AUTHOR_LIMIT"} <= codes


class OneRow:
    """A connection whose one statement returns `row`."""

    def __init__(self, row: dict[str, Any]) -> None:
        self.row = row

    async def execute(self, _query: str, _params: tuple[object, ...]) -> "OneRow":
        return self

    async def fetchone(self) -> dict[str, Any]:
        return self.row


def test_a_committed_grant_refusal_is_blocked_never_a_grant() -> None:
    run, proposal = uuid4(), uuid4()
    row = {key: None for key in ("action_id", "conversation_id", "payload_sha256", "payload_canonical", "detail")}
    row |= {"run_id": run, "proposal_id": proposal, "tenant_id": uuid4(), "attempt_state": None}
    conn: Any = OneRow(row | {"refusal": "asset_incident_exists"})
    got = asyncio.run(persistence.grant_execution(conn, handle="h", azp="ops-worker", proposal_id=proposal))
    assert got == persistence.Blocked(run, proposal, Reason.ASSET_INCIDENT_EXISTS)
    granting = {r.reasons for r in TRANSITIONS if r.performer is Performer.GRANT_EXECUTION and r.reasons}
    assert granting == {GRANT_REFUSALS}  # mcp-write's `reason` names exactly the table's grant refusals


def test_a_blocked_freeze_has_no_proposal() -> None:
    row = {"proposal_id": None, "revision": 2, "state": "BLOCKED_REVIEW", "reason": "asset_action_unresolved"}
    conn: Any = OneRow(row | {"state_version": 7})
    frozen = asyncio.run(
        persistence.freeze_proposal(conn, run_id=uuid4(), draft_id=uuid4(), payload_canonical=b"{}", expires_at=NOW)
    )
    assert frozen.proposal_id is None and frozen.state is RunState.BLOCKED_REVIEW
    assert frozen.reason is Reason.ASSET_ACTION_UNRESOLVED and frozen.revision == 2


def test_the_manual_proposal_names_its_run_and_the_search_is_bounded() -> None:
    body = {
        "asset_id": "A17",
        "start_at": "2026-10-05T12:00:00Z",
        "end_at": "2026-10-06T12:00:00Z",
        "title": "t",
        "summary": "s",
        "evidence_refs": ["ALPHA-INCIDENT:v2:review"],
        "assumptions": [],
        "limitations": [],
    }
    with pytest.raises(ValidationError):
        c.load(c.ManualProposalRequest, json.dumps(body))  # contract erratum 133: the run is required
    assert c.load(c.ManualProposalRequest, json.dumps({**body, "run_id": str(uuid4())})).asset_id == "A17"
    assert c.load(c.SearchRequest, '{"query": "bearing temperature"}').limit == 5
    for bad in ('{"query": "x", "limit": 11}', '{"query": ""}', '{"query": "x", "mode": "vector_exact"}'):
        with pytest.raises(ValidationError):
            c.load(c.SearchRequest, bad)


def test_only_feedback_recorded_names_a_subject_and_a_category() -> None:
    payload = {"subject_kind": "run", "subject_id": str(uuid4()), "category": "unclear"}
    event_rules_ok(EventType.FEEDBACK_RECORDED, EventSource.APPLICATION, payload)
    with pytest.raises(EventRuleViolation):
        event_rules_ok(EventType.TOOL_COMPLETED, EventSource.APPLICATION, {"category": "unclear"})


def test_an_execute_job_reads_the_asset_status_and_a_manual_run_ends_its_graph_run() -> None:
    persistence.allowed_tool(JobType.EXECUTE, RunState.APPROVED, None, Tool.GET_ASSET_STATUS)
    for attempt in AttemptState:  # only before the grant: any attempt means the grant exists (erratum 137)
        with pytest.raises(persistence.HandleRejected):
            persistence.allowed_tool(JobType.EXECUTE, RunState.EXECUTING, attempt, Tool.GET_ASSET_STATUS)
    assert Tool.GET_RECENT_ALERTS not in JOB_RULES[JobType.EXECUTE].allowed_tools  # only the status (erratum 137)
    key = GraphKey(RunState.DRAFTING, Intent.INVESTIGATE, True, Evidence.SUFFICIENT, DraftKind.MANUAL, False, None)
    assert route_graph(key) is GraphRoute.PUBLISH  # never `draft` again: the run waits for a person

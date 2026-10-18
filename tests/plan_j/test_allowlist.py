"""The AM-15 allowlist in Python: the job type's tools and the job type's run states (Plan J ruling 6, erratum 19). The
third dimension, the attempt state (T47), is tabled in tests/plan_k/test_attempt_allowlist.py; here every call passes
an attempt state the attempt rule admits, so only the first two decide.

Catches: a read handle still honoured once its run awaits approval, input or a decision (or ended), an execute handle
honoured once its run succeeded, a tool outside the job type's set (R085: the worker names the tool, the server
decides), a refusal whose message says which check failed or whose log line carries the handle, and a resolution
that reads the run state but does not hand it to the check.
"""

import asyncio
import logging
from typing import Any

import pytest
from ops_core import persistence
from ops_core.jobs import ATTEMPT_STATES, JOB_RULES, JobType, Server, Tool
from ops_core.states import AttemptState, RunState

HANDLE_JOBS = [t for t, rule in JOB_RULES.items() if rule.server is not None]


def admitted(job_type: JobType, tool: Tool) -> AttemptState | None:
    """An attempt state the attempt rule admits for the pair (any, for a pair it does not govern)."""
    allowed = ATTEMPT_STATES.get((job_type, tool))
    return None if allowed is None or None in allowed else min(a for a in allowed if a is not None)


@pytest.mark.parametrize("job_type", HANDLE_JOBS, ids=[t.value for t in HANDLE_JOBS])
def test_every_state_and_tool_pair_follows_the_job_rule(job_type: JobType) -> None:
    rule = JOB_RULES[job_type]
    for state in RunState:
        for tool in Tool:
            attempt = admitted(job_type, tool)
            if tool in rule.allowed_tools and state in rule.run_states:
                persistence.allowed_tool(job_type, state, attempt, tool)
            else:
                with pytest.raises(persistence.HandleRejected) as refused:
                    persistence.allowed_tool(job_type, state, attempt, tool)
                assert str(refused.value) == "invocation handle rejected"  # one message for every refusal


def test_the_read_jobs_run_where_the_worker_calls_mcp_read() -> None:
    assert JOB_RULES[JobType.INVESTIGATE].run_states == {RunState.QUEUED, RunState.RETRIEVING, RunState.DRAFTING}
    assert JOB_RULES[JobType.RESUME_INPUT].run_states == {RunState.AWAITING_INPUT, RunState.QUEUED}
    assert {JOB_RULES[t].server for t in (JobType.INVESTIGATE, JobType.RESUME_INPUT)} == {Server.READ}


class OneRow:
    """A connection whose one statement returns `row` (the definer's answer)."""

    def __init__(self, row: dict[str, Any]) -> None:
        self.row = row
        self.params: tuple[object, ...] = ()

    async def execute(self, _query: str, params: tuple[object, ...]) -> "OneRow":
        self.params = params
        return self

    async def fetchone(self) -> dict[str, Any]:
        return self.row


def resolved_row(state: str) -> dict[str, Any]:
    ids = "00000000-0000-4000-8000-00000000000"
    return {
        "run_id": f"{ids}1",
        "job_id": f"{ids}2",
        "job_type": "investigate",
        "tenant_id": f"{ids}3",
        "conversation_id": f"{ids}4",
        "run_state": state,
        "attempt_state": None,
    }


def test_resolution_hands_the_run_state_to_the_check(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    conn: Any = OneRow(resolved_row("RETRIEVING"))
    handle = "a-raw-handle-that-must-never-be-logged"
    got = asyncio.run(
        persistence.resolve_invocation(conn, handle=handle, azp="ops-worker", tool=Tool.SEARCH_PROCEDURES)
    )
    passed = conn.params == (handle, "ops-worker")
    assert got.run_state is RunState.RETRIEVING and passed
    conn.row = resolved_row("AWAITING_APPROVAL")
    with pytest.raises(persistence.HandleRejected):
        asyncio.run(persistence.resolve_invocation(conn, handle=handle, azp="ops-worker", tool=Tool.SEARCH_PROCEDURES))
    leaked = handle in caplog.text  # a verdict, not an operand (Global Constraints: secrets)
    assert "does not run in state AWAITING_APPROVAL" in caplog.text and not leaked

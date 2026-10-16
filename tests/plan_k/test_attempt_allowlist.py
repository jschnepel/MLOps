"""The attempt-state dimension of the AM-15 allowlist, in Python (SA:338; Plan K rulings 4, 5 and 26; erratum 19).

Catches: a receipt lookup or an abort honoured for an execute handle, or a lookup before anything could have been sent
(R030: "unavailable outside recover jobs"); a recover job redispatching an attempt already SENT (SA:345) or anything
after an abort request; an execute job's re-send of a SENT attempt refused (Plan E ruling 6, the re-queue after a lost
reply); an abort of a resolved attempt; a recovery tool for a run with no grant at all (it would have nothing to
recover, and must create nothing); a refusal whose message says which check failed or whose log carries the handle;
and a resolution that reads the attempt state but does not hand it to the check.
"""

import asyncio
import logging
from typing import Any

import pytest
from ops_core import persistence
from ops_core.jobs import ATTEMPT_STATES, JOB_RULES, JobType, Tool
from ops_core.states import AttemptState, RunState

from tests.plan_j.test_allowlist import HANDLE_JOBS, OneRow, resolved_row

A = AttemptState
ATTEMPTS: list[AttemptState | None] = [None, *AttemptState]
WRITE = {Tool.CREATE_INCIDENT, Tool.GET_INCIDENT_RECEIPT, Tool.ABORT_INCIDENT}


def test_the_attempt_rules_are_the_rulings() -> None:
    assert ATTEMPT_STATES == {
        (JobType.EXECUTE, Tool.CREATE_INCIDENT): {None, A.INTENT, A.SENT},  # the SENT re-send stays (ruling 5)
        (JobType.RECOVER, Tool.CREATE_INCIDENT): {A.INTENT},  # SA:345 over SA:334
        (JobType.RECOVER, Tool.GET_INCIDENT_RECEIPT): {A.SENT, A.ABORT_REQUESTED, A.RESOLVED},
        (JobType.RECOVER, Tool.ABORT_INCIDENT): {A.INTENT, A.SENT, A.ABORT_REQUESTED},
    }
    # Every write tool a job type may call has a rule; no read tool has one.
    governed = {(t, tool) for t in HANDLE_JOBS for tool in JOB_RULES[t].allowed_tools if tool in WRITE}
    assert governed == set(ATTEMPT_STATES)


@pytest.mark.parametrize("job_type", HANDLE_JOBS, ids=[t.value for t in HANDLE_JOBS])
def test_every_state_attempt_and_tool_follows_the_three_rules(job_type: JobType) -> None:
    rule = JOB_RULES[job_type]
    for state in RunState:
        for attempt in ATTEMPTS:
            for tool in Tool:
                admitted = ATTEMPT_STATES.get((job_type, tool))
                ok = tool in rule.allowed_tools and state in rule.run_states
                ok = ok and (admitted is None or attempt in admitted)
                if ok:
                    persistence.allowed_tool(job_type, state, attempt, tool)
                else:
                    with pytest.raises(persistence.HandleRejected) as refused:
                        persistence.allowed_tool(job_type, state, attempt, tool)
                    assert str(refused.value) == "invocation handle rejected"  # one message for every refusal


def test_receipt_lookup_is_for_recover_jobs_with_something_to_look_up() -> None:
    """R030 in the allowlist: an execute job never looks up or aborts; a recover job with no grant gets nothing."""
    for tool in (Tool.GET_INCIDENT_RECEIPT, Tool.ABORT_INCIDENT):
        for attempt in ATTEMPTS:
            with pytest.raises(persistence.HandleRejected):
                persistence.allowed_tool(JobType.EXECUTE, RunState.EXECUTING, attempt, tool)
    for tool in WRITE:
        with pytest.raises(persistence.HandleRejected):
            persistence.allowed_tool(JobType.RECOVER, RunState.OUTCOME_UNKNOWN, None, tool)  # no grant, no recovery
    persistence.allowed_tool(JobType.RECOVER, RunState.ESCALATED, A.RESOLVED, Tool.GET_INCIDENT_RECEIPT)


def recover_row(state: str, attempt: str | None) -> dict[str, Any]:
    return {**resolved_row(state), "job_type": "recover", "attempt_state": attempt}


def test_resolution_hands_the_attempt_state_to_the_check(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    handle = "a-raw-handle-that-must-never-be-logged"
    conn: Any = OneRow(recover_row("OUTCOME_UNKNOWN", "SENT"))
    got = asyncio.run(
        persistence.resolve_invocation(conn, handle=handle, azp="ops-worker", tool=Tool.GET_INCIDENT_RECEIPT)
    )
    assert got.attempt_state == "SENT" and got.job_type is JobType.RECOVER
    with pytest.raises(persistence.HandleRejected):  # the same run and attempt: a recover job does not re-send SENT
        asyncio.run(persistence.resolve_invocation(conn, handle=handle, azp="ops-worker", tool=Tool.CREATE_INCIDENT))
    leaked = handle in caplog.text  # a verdict, not an operand
    assert "tool create_incident is not allowed for job type recover with attempt SENT" in caplog.text and not leaked
    conn.row = recover_row("OUTCOME_UNKNOWN", None)
    with pytest.raises(persistence.HandleRejected):
        asyncio.run(
            persistence.resolve_invocation(conn, handle=handle, azp="ops-worker", tool=Tool.GET_INCIDENT_RECEIPT)
        )
    assert "with attempt none" in caplog.text

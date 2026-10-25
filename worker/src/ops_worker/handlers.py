"""Job handlers (AM-20.4 job types; AM-10 states): each claimed job runs one LangGraph graph run for its run, under the
run lease its claim took (AM-12, T13), and its final unit closes the job and releases the lease (`persistence.
release_lease`), after the graph run ends or interrupts, so a run waiting for a person holds no lease (R022).

`investigate` starts the run's graph (QUEUED), or resumes it from `runs.checkpoint_id` when an earlier owner was
interrupted mid-run (SA:214); `resume_input` resumes a run waiting for a clarification with the reply's event id
(`Command(resume=...)`, SA:213); `execute` resumes the run waiting for its reviewer, or re-runs its execute node after
a re-queue. The graph's nodes do the work (`ops_worker.graph`); here are only the entry decisions and the failures no
node can record. A lost lease raises LeaseLost to the caller, which hands the job back (`abandon`).

T21 (Plan R ruling 1): each revision of a run is its own graph thread, `run_id:revision`. The run's revision is read in
the job's first unit (`persistence.run_revision`); an investigate job names the revision it wakes in its dedup key,
and a job for an older revision ends without a graph run. `create_revision` clears the stored checkpoint, so a
revision's QUEUED starts a new graph run while a clarification's QUEUED resumes. The first unit also pins the run's
workflow version (ruling 18). A run left in DRAFTING by the manual path (erratum 134) waits for a person; no job
resumes or fails it.
"""

from __future__ import annotations

import logging
from typing import Any, Final
from uuid import UUID

import psycopg
from langgraph.types import Command
from ops_core import persistence
from ops_core.jobs import JOB_RULES, JobType
from ops_core.lease import Lease, LeaseLost
from ops_core.outcomes import EventType
from ops_core.states import RunState
from psycopg.pq import TransactionStatus

from ops_worker.deps import Deps
from ops_worker.drafting import WORKFLOW_VERSION
from ops_worker.graph import build, nodes
from ops_worker.graph.nodes import (  # re-exported: the templates the tests and the records name
    ABSTAINED,
    BUDGET_MARGIN_SECONDS,
    MODEL_INVALID,
    MODEL_UNAVAILABLE,
    Requeue,
    is_deferred,
)
from ops_worker.graph.state import Context, initial

__all__ = [
    "ABSTAINED",
    "BUDGET_MARGIN_SECONDS",
    "INTERRUPTED",
    "MODEL_INVALID",
    "MODEL_UNAVAILABLE",
    "Deps",
    "abandon",
    "execute",
    "handle",
    "investigate",
    "is_deferred",
    "resume_input",
]

log = logging.getLogger("ops_worker")
EXECUTE_RETRY_SECONDS = 30  # how long an execute job waits after mcp-write could not be reached
FAILURE_RETRY_SECONDS = 30  # how long a job waits after a failure no node recorded (it is re-queued, not done)
# A run found RETRIEVING or DRAFTING with no stored checkpoint (it stopped before its first checkpoint was stored, or
# before T20) cannot be resumed; it is failed, which frees its conversation slot.
INTERRUPTED: Final = "interrupted; the run was not resumed"
_MID_RUN: Final = (RunState.RETRIEVING, RunState.DRAFTING)


async def _drive(
    deps: Deps,
    job: dict[str, Any],
    lease: Lease,
    graph_input: build.GraphInput,
    checkpoint_id: str | None,
    revision: int,
) -> None:
    """One graph run on the revision's thread. A failure no node recorded fails a run still RETRIEVING or DRAFTING, so
    its slot is freed (as Plan P's "drafting failed"); any other failure propagates to `handle`, which releases the
    lease and re-queues the job. A graph run that ends with the run still DRAFTING took the manual path: its stored
    checkpoint is cleared, the state a person's proposal waits for (T21, erratum 134)."""
    ctx = Context(deps, job, lease, revision)
    try:
        await build.run_graph(ctx, graph_input, checkpoint_id=checkpoint_id, revision=revision)
    except (LeaseLost, Requeue):
        raise
    except persistence.RevisionMoved as moved:
        # T21 (Plan R round 1, I1): a revision committed while this graph run was working. Nothing more is written for
        # the old thread; the job ends and its final unit releases the lease, and the revision's own job runs its graph.
        log.info("job %s: run %s was revised; this graph run ends (%s)", job["id"], lease.run_id, moved)
        return
    except Exception:
        async with nodes.unit(ctx) as conn:
            run = await persistence.run_row(conn, lease.run_id, lock=True)
            state = RunState(run["state"])
            if state not in _MID_RUN:
                raise
            log.exception("job %s: the graph run failed in %s", job["id"], state.value)
            await nodes.fail_from(conn, lease.run_id, state, nodes.WORKFLOW_FAILED)
        return
    async with nodes.unit(ctx) as conn:
        run = await persistence.run_row(conn, lease.run_id, lock=True)
        if RunState(run["state"]) is RunState.DRAFTING:
            await persistence.clear_checkpoint_id(conn, lease.run_id)


async def _waits_for_person(conn: persistence.Conn, run: dict[str, Any]) -> bool:
    """A DRAFTING run with no stored checkpoint whose newest explanation is the manual path's (T21, erratum 134)."""
    if RunState(run["state"]) is not RunState.DRAFTING or run.get("checkpoint_id") is not None:
        return False
    explained = await persistence.run_events(conn, run["run_id"], EventType.EXPLANATION_READY)
    return bool(explained) and explained[-1][1].get("message") == nodes.MANUAL_PATH


async def _older_thread(deps: Deps, lease: Lease, stored: str | None, revision: int) -> bool:
    """True when `stored` is a checkpoint of an earlier revision's thread and not of this one (T21, Plan R round 1,
    I1): an older graph run stored it before the revision moved the run on, so the revision starts its own thread."""
    if stored is None or await build.known(deps.saver, build.thread_id(lease.run_id, revision), stored):
        return False
    for older in range(revision - 1, 0, -1):
        if await build.known(deps.saver, build.thread_id(lease.run_id, older), stored):
            return True
    return False


async def _resumable(
    deps: Deps, job: dict[str, Any], lease: Lease, state: RunState, stored: str | None, revision: int
) -> bool:
    """True when the stored checkpoint exists; otherwise the run is failed with a template (T20 review note 2)."""
    if stored is not None and await build.known(deps.saver, build.thread_id(lease.run_id, revision), stored):
        return True
    log.warning("job %s: run %s has no stored checkpoint to resume (%s)", job["id"], lease.run_id, stored)
    async with nodes.unit(Context(deps, job, lease)) as conn:
        await nodes.fail_from(conn, lease.run_id, state, nodes.CHECKPOINT_MISSING)
    return False


async def _first_unit(deps: Deps, job: dict[str, Any], lease: Lease) -> dict[str, Any]:
    """The job's first fenced unit: the run row under its lock with its revision, the run's workflow version pinned
    (ruling 18), and an unresumable interrupted run failed in it; a run waiting for a person is left alone."""
    async with deps.conn.transaction():
        await persistence.set_tenant(deps.conn, job["tenant_id"])  # the worker's own reads are RLS-scoped
        await persistence.fenced(deps.conn, lease)  # run_lease before runs (SA:188, ruling 29)
        run = dict(await persistence.run_row(deps.conn, job["run_id"], lock=True))
        run["revision"] = await persistence.run_revision(deps.conn, job["run_id"])
        pinned = await persistence.record_workflow_version(deps.conn, job["run_id"], WORKFLOW_VERSION)
        if pinned != WORKFLOW_VERSION:  # its freeze refuses this worker's payloads; routing across a bump is T36's
            log.warning(
                "job %s: run %s is pinned to workflow %s, this worker runs %s",
                job["id"],
                job["run_id"],
                pinned,
                WORKFLOW_VERSION,
            )
        state = RunState(run["state"])
        run["manual"] = await _waits_for_person(deps.conn, run)
        if state in _MID_RUN and run.get("checkpoint_id") is None and not run["manual"]:
            log.warning("job %s: run was interrupted in %s before a checkpoint was stored; failed", job["id"], state)
            await persistence.transition_run(
                deps.conn, run_id=run["run_id"], src=state, dst=RunState.FAILED, detail={"message": INTERRUPTED}
            )
            run["state"] = RunState.FAILED.value
    return run


async def investigate(deps: Deps, job: dict[str, Any], lease: Lease) -> None:
    """Start the run's graph, or resume it from its stored checkpoint after an interruption (SA:214). The job's key
    names the revision it wakes (`run_id:revision`, SA:455); a job for an older revision ends here (T21 ruling 1)."""
    run = await _first_unit(deps, job, lease)
    woken = int(str(job["dedup_key"]).rpartition(":")[2])
    if woken != run["revision"]:
        log.info(
            "job %s: it wakes revision %s; run %s is at revision %s", job["id"], woken, lease.run_id, run["revision"]
        )
        return
    await _carry_on(deps, job, lease, run)


async def _carry_on(deps: Deps, job: dict[str, Any], lease: Lease, run: dict[str, Any]) -> None:
    """A run in QUEUED, RETRIEVING or DRAFTING: a new graph run, or crash recovery from the stored checkpoint."""
    state, stored, revision = RunState(run["state"]), run.get("checkpoint_id"), int(run["revision"])
    if run.get("manual"):
        log.info("job %s: run %s waits for a manual proposal", job["id"], lease.run_id)
    elif state is RunState.QUEUED and await _older_thread(deps, lease, stored, revision):
        await _drive(deps, job, lease, initial(lease.run_id), None, revision)
    elif state in _MID_RUN or (state is RunState.QUEUED and stored is not None):
        # An earlier owner stopped mid-run, or after a clarification moved the run back to QUEUED: resume from the
        # stored checkpoint, never from the thread's newest one (a stray head is ignored, R108). One that is the end of
        # a graph run has nothing to resume: the run starts a new graph run.
        if await _resumable(deps, job, lease, state, stored, revision):
            assert stored is not None  # _resumable found it
            if await build.ended(Context(deps, job, lease), build.thread_id(lease.run_id, revision), stored):
                await _drive(deps, job, lease, initial(lease.run_id), None, revision)
            else:
                await _drive(deps, job, lease, None, stored, revision)
    elif state is RunState.QUEUED:
        await _drive(deps, job, lease, initial(lease.run_id), None, revision)
    else:
        log.info("job %s: run already %s", job["id"], state.value)


async def resume_input(deps: Deps, job: dict[str, Any], lease: Lease) -> None:
    """Resume a run waiting for a clarification with the reply's `clarification.received` event id (SA:213). The
    job's key names the question it answers (`run_id:clarification_event_id`, SA:501), so a replay is a duplicate
    the queue refuses, and a reply that is not the latest is refused by the resumed node (RESUME_REFUSED). A job
    whose question is no longer the run's newest is stale (its own graph run asked the next one before the job ran
    again): it ends without a graph run, and the newer reply's job resumes the run."""
    run = await _first_unit(deps, job, lease)
    state, stored = RunState(run["state"]), run.get("checkpoint_id")
    if state is not RunState.AWAITING_INPUT:
        # An earlier owner of this job already took the reply (the run is QUEUED, RETRIEVING or DRAFTING): carry on
        # as an investigate job would; any other state has nothing left for this job.
        await _carry_on(deps, job, lease, run)
        return
    question = str(job["dedup_key"]).partition(":")[2]
    async with nodes.unit(Context(deps, job, lease), fence=False) as conn:
        requested = await persistence.run_events(conn, lease.run_id, EventType.CLARIFICATION_REQUESTED)
    newest = str(requested[-1][0]) if requested else None
    if newest is not None and newest != question:
        # No transition and no checkpoint: resuming the newer question with this job's older reply would fail the
        # run, which is legitimately waiting (the API refuses a reply to the superseded question).
        log.info(
            "job %s: run %s waits on question %s; this job answers the earlier question %s and ends",
            job["id"],
            lease.run_id,
            newest,
            question,
        )
        return
    if not await _resumable(deps, job, lease, state, stored, run["revision"]):
        return
    async with nodes.unit(Context(deps, job, lease), fence=False) as conn:
        received = await persistence.run_events(conn, lease.run_id, EventType.CLARIFICATION_RECEIVED)
    reply = next((event_id for event_id, p in reversed(received) if p.get("question_id") == question), None)
    if reply is None:
        async with nodes.unit(Context(deps, job, lease)) as conn:
            await nodes.fail_from(conn, lease.run_id, state, nodes.RESUME_REFUSED)
        return
    await _drive(deps, job, lease, Command(resume=str(reply)), stored, run["revision"])


async def _approval(deps: Deps, job: dict[str, Any], lease: Lease, run: dict[str, Any]) -> UUID | None:
    """The decision's committed event, the resume value (SA:213), checked against the database first: the run's
    latest decision event is an `approval.recorded` (no `run.rejected`) whose `proposal_id` is the run's active
    proposal (record_decision's payload, 0004). None when it is not, with the three ids logged (round 1, M1)."""
    async with nodes.unit(Context(deps, job, lease), fence=False) as conn:
        approved = await persistence.run_events(conn, lease.run_id, EventType.APPROVAL_RECORDED)
        rejected = await persistence.run_events(conn, lease.run_id, EventType.RUN_REJECTED)
    event_id, payload = approved[-1] if approved else (None, {})
    active = str(run["active_proposal_id"])
    if event_id is None or rejected or payload.get("proposal_id") != active:
        log.error(
            "execute job %s: run %s has no approval of its active proposal to resume with (event %s for proposal %s,"
            " active proposal %s); the job ends without a graph run",
            job["id"],
            lease.run_id,
            event_id,
            payload.get("proposal_id"),
            active,
        )
        return None
    return event_id


async def execute(deps: Deps, job: dict[str, Any], lease: Lease) -> bool:
    """Run the approved run's graph to `create_incident` (ruling 14); True when the job is finished by `handle`, False
    when it was re-queued (its final unit already ran and released the lease).

    The stored checkpoint is the reviewer wait: resumed with the decision's event id, checked first (`_approval`),
    the waiting node rereads the decision. After a re-queue it is the checkpoint before the execute node, which runs
    again (a fork, SA:214). A run with no stored checkpoint (approved before T20) starts a graph run, whose router reads
    APPROVED."""
    run = await _first_unit(deps, job, lease)
    # APPROVED or EXECUTING (JOB_RULES[EXECUTE].run_states): after a transport failure past the grant, the re-queued
    # job resends under the same action id (grant_execution's replay rule; Plan E ruling 6).
    if RunState(run["state"]) not in JOB_RULES[JobType.EXECUTE].run_states:
        log.info("execute job %s: run is %s, nothing to dispatch", job["id"], run["state"])
        return True
    stored, revision = run.get("checkpoint_id"), int(run["revision"])
    thread = build.thread_id(lease.run_id, revision)
    ctx = Context(deps, job, lease, revision)
    graph_input: build.GraphInput = initial(lease.run_id)
    checkpoint = None
    if stored is not None and await build.known(deps.saver, thread, stored):
        if await build.interrupted(ctx, thread, stored):
            approval = await _approval(deps, job, lease, run)
            if approval is None:
                # No transition (the worker may not move an APPROVED run, SA:451) and no retry for ever: the job is
                # closed by `handle`'s final unit. TODO(T22): recovery of a run approved without a matching decision.
                return True
            checkpoint, graph_input = stored, Command(resume=str(approval))
        elif not await build.ended(ctx, thread, stored):
            checkpoint, graph_input = stored, None  # the checkpoint before the execute node: a fork runs it again
        # else the stored checkpoint ended its graph run (a final refusal): a new graph run, whose router reads the
        # run's APPROVED or EXECUTING again, instead of a fork that would run nothing
    try:
        await _drive(deps, job, lease, graph_input, checkpoint, revision)
    except Requeue:
        await persistence.release_lease(deps.conn, lease, job=job, requeue_seconds=EXECUTE_RETRY_SECONDS)
        return False
    return True


async def handle(deps: Deps, job: dict[str, Any], lease: Lease) -> None:
    """Dispatch a claimed job by type under its lease; the final unit closes the job and releases the lease. After a
    failure no node recorded, the lease is released and the job re-queued, never finished (the job may be the only
    wake-up its run has; bounded retries are T22's); the failure is re-raised for the poll loop to log. A lost lease
    is not released again: `main.run_job` hands that job back."""
    kind = JobType(job["type"])
    try:
        if kind is JobType.INVESTIGATE:
            await investigate(deps, job, lease)
        elif kind is JobType.RESUME_INPUT:
            await resume_input(deps, job, lease)
        elif kind is JobType.EXECUTE:
            if not await execute(deps, job, lease):
                return  # re-queued: its final unit already released the lease
        else:
            # TODO(T22): recover jobs (the graph's recover route reaches reconcile_outcome, which only logs in v1).
            log.info("job %s of type %s is not handled before T22", job["id"], kind.value)
    except Exception:
        await _release_after_failure(deps, job, lease)
        raise
    await persistence.release_lease(deps.conn, lease, job=job)


async def _release_after_failure(deps: Deps, job: dict[str, Any], lease: Lease) -> None:
    """The final unit for a job that failed: it releases the lease and re-queues the job after FAILURE_RETRY_SECONDS.
    Skipped when the lease is already lost (the loop hands the job back); a lease found lost only now (a refusal that
    did not mark it, as `mint_handle`'s) is one INFO line; any other failure of its own is logged, and none replaces the
    failure being raised."""
    if lease.lost is not None:
        return
    try:
        await persistence.release_lease(deps.conn, lease, job=job, requeue_seconds=FAILURE_RETRY_SECONDS)
    except LeaseLost:
        log.info("job %s: the lease was already lost; the loop hands the job back", job["id"])
    except Exception:
        log.exception("job %s: the lease could not be released after the failure", job["id"])


async def abandon(deps: Deps, job: dict[str, Any], lease: Lease) -> None:
    """The lease is lost (Plan H ruling 19): revoke the handles minted under this fence and hand the job back, in one
    unit, with no transition here (the next owner resumes the run from its stored checkpoint, or fails it as
    INTERRUPTED when none was stored). `revoke_handles` never refuses a stale fence (ruling 8), so this works whoever
    holds the lease now.

    Raises:
        psycopg.OperationalError: the loop connection was not idle. Only effects are ever cancelled, so this should
            not happen; if it does, a hand-back on that connection would nest in the open transaction and never
            commit, so the connection is closed instead, the poll loop ends and the supervisor restarts the worker
            (review round 1, B1).
    """
    if deps.conn.info.transaction_status is not TransactionStatus.IDLE:
        await deps.conn.close()
        raise psycopg.OperationalError("the loop connection was not idle when its lease was lost; it was closed")
    async with deps.conn.transaction():
        await persistence.set_tenant(deps.conn, job["tenant_id"])  # jobs is under RLS
        await persistence.revoke_handles(deps.conn, lease.run_id, lease.fence)
        await persistence.unclaim_job(deps.conn, job["id"], worker_name=deps.worker_name)

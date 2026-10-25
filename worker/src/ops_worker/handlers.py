"""Job handlers (AM-20.4 job types; AM-10 states): every state change goes through the definer functions as role
`worker` (`transition_run`, `freeze_proposal`, `mark_unknown`), and every network call happens outside a transaction
(BUILD_SPEC §11).

`investigate`: QUEUED → RETRIEVING → (read tool) → DRAFTING, with the run manifest → the model route's draft → by its
kind: a proposal is frozen → AWAITING_APPROVAL; an abstention without a question → INSUFFICIENT_EVIDENCE; an answer or
a clarifying question → FAILED until T20 routes them; a model outage, or a draft still invalid after its one repair →
FAILED with a templated message (BS:516). `execute`: mint a write handle and call `create_incident`; mcp-write
performs the grant, the dispatch and the outcome, while the worker records an UNKNOWN envelope through `mark_unknown`.
Every handler runs under the run lease its claim took (AM-12, T13): each unit that writes for the run opens with
`persistence.fenced` (the lease row FOR SHARE; owner, fence and expiry compared after the lock), every MCP and model
call runs as a lease effect (`Lease.effect`: none starts past the lease's local deadline, SA:195, and a lost lease
cancels it; database units are never cancelled), and the job's final unit revokes the job's handles, closes the job and
releases the lease together (`persistence.release_lease`). A lost lease raises LeaseLost to the caller, which hands the
job back (`abandon`). No LangGraph (→ T20).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID, uuid4

import psycopg
from ops_core import persistence
from ops_core.jobs import JOB_RULES, JobType, Server
from ops_core.lease import Lease, LeaseLost
from ops_core.outcomes import EventSource, EventType
from ops_core.routing import RunManifest
from ops_core.settings import LeaseSettings, Urls
from ops_core.states import Intent, RunState, freeze_allowed
from psycopg.pq import TransactionStatus
from pydantic import ValidationError

from ops_worker import permit, proposals
from ops_worker.drafting import (
    PROMPT_VERSION,
    DraftGenerator,
    DraftRequest,
    EvidenceItem,
    ModelOutputInvalid,
    ModelUnavailable,
)
from ops_worker.heartbeat import Heartbeat
from ops_worker.mcp import McpCaller, McpCallFailed

log = logging.getLogger("ops_worker")
EXECUTE_RETRY_SECONDS = 30  # how long an execute job waits after mcp-write could not be reached
QUERY_CHARS = 500  # schemas/tools/search_procedures.input.schema.json maxLength
INTERRUPTED = "interrupted; the run was not resumed"  # TODO(T20): resume from the checkpoint instead
# Templated outcomes of a draft (BS:516): never the model's text, never an exception's.
MODEL_UNAVAILABLE = "the model route did not answer in time or could not be reached"
MODEL_INVALID = "the model's draft failed validation after its one repair"
NOT_ROUTED = "the draft was an answer or a clarifying question, which this build does not route yet"
ABSTAINED = "the model found the evidence insufficient"
RETRIEVAL_MODE: Final = "lexical"  # the only mode the worker asks for; choosing it per run is TODO(T25)
# The draft stops this long before the run's compute budget ends, so the freeze or the failure unit after it still
# runs inside the budget, before the heartbeat's own gate ("compute budget spent") could cancel the call.
BUDGET_MARGIN_SECONDS: Final = 5.0


def is_deferred(doc: dict[str, Any]) -> bool:
    """An `error` envelope whose code is GRANT_DEFERRED: the gate found the membership sync stale (T11), so the job
    is retried rather than closed."""
    error = doc.get("error") or {}
    return doc.get("status") == "error" and error.get("code") == "GRANT_DEFERRED"


@dataclass
class Deps:
    """What a handler needs: the loop's connection, the MCP client, the model route, the server URLs, the worker's
    name (the lease owner), the workload client its tokens are issued to (the `azp` a handle is bound to), the lease
    settings and the heartbeat that renews the lease while a job runs."""

    conn: persistence.Conn
    mcp: McpCaller
    generator: DraftGenerator
    urls: Urls
    worker_name: str
    workload_azp: str  # the token source's client id (Plan J ruling 17): _resolve_handle compares it with the token's
    leases: LeaseSettings = field(default_factory=LeaseSettings)
    heartbeat: Heartbeat | None = None  # main.run_job hands it each claimed lease; tests may run without one


async def _event(
    deps: Deps,
    lease: Lease,
    type: EventType,
    payload: dict[str, Any],
    source: EventSource = EventSource.APPLICATION,
) -> None:
    """One event in its own fenced unit; the function finds the tenant itself (run_directory)."""
    async with deps.conn.transaction():
        await persistence.fenced(deps.conn, lease)
        await persistence.append_event(deps.conn, run_id=lease.run_id, type=type, payload=payload, source=source)


async def _fail(deps: Deps, lease: Lease, src: RunState, dst: RunState, message: str) -> None:
    """A pre-grant failure state through transition_run, which emits the matching run.* event itself (SA:451)."""
    async with deps.conn.transaction():
        await persistence.fenced(deps.conn, lease)
        await persistence.transition_run(deps.conn, run_id=lease.run_id, src=src, dst=dst, detail={"message": message})


async def investigate(deps: Deps, job: dict[str, Any], lease: Lease) -> None:
    """Retrieve evidence, draft with the model route, freeze the proposal and await approval."""
    tenant_id: UUID = job["tenant_id"]
    async with deps.conn.transaction():
        await persistence.set_tenant(deps.conn, tenant_id)  # the worker's own reads and inserts are RLS-scoped
        await persistence.fenced(deps.conn, lease)  # run_lease before runs (SA:188, ruling 29)
        run = dict(await persistence.run_row(deps.conn, job["run_id"], lock=True))
        state = RunState(run["state"])
        if state in (RunState.RETRIEVING, RunState.DRAFTING):
            # A previous holder was interrupted (a lost lease, a crash, a lock timeout) and nothing resumes a run yet:
            # fail it, which frees its conversation slot, rather than close the job and leave the run active for good.
            log.warning("investigate job %s: run was interrupted in %s; failed", job["id"], state.value)
            await persistence.transition_run(
                deps.conn, run_id=run["run_id"], src=state, dst=RunState.FAILED, detail={"message": INTERRUPTED}
            )
            return
        if state is not RunState.QUEUED:
            log.info("investigate job %s: run already %s", job["id"], run["state"])
            return
        cur = await deps.conn.execute("SELECT text FROM app.messages WHERE message_id = %s", (run["message_id"],))
        message = await cur.fetchone()
        if message is None:
            raise persistence.NotFound("message not found")
        text = str(message["text"])
        await persistence.transition_run(deps.conn, run_id=run["run_id"], src=RunState.QUEUED, dst=RunState.RETRIEVING)
        handle = await persistence.mint_handle(
            deps.conn,
            run_id=run["run_id"],
            job_id=job["id"],
            server=Server.READ,
            azp=deps.workload_azp,
            fence=lease.fence,
        )
    await _event(deps, lease, EventType.TOOL_STARTED, {"message": "search_procedures"})
    try:
        # An MCP call is an effect: none starts past the local deadline (SA:195), and a lost lease cancels it.
        # The tool input caps `query` at 500 characters (schemas/tools); the message itself may be 4,000.
        doc = await lease.effect(
            deps.mcp.call(
                deps.urls.mcp_read,
                handle=handle,
                tool="search_procedures",
                arguments={"query": text[:QUERY_CHARS], "limit": 3, "mode": RETRIEVAL_MODE},
            )
        )
        evidence = proposals.evidence_from_search(doc)
        # The manifest records the corpus version and the mode the tool reports it ran (mcp-read's `retrieval_mode`),
        # so a tool result without them, or with values the manifest refuses, is a retrieval failure like any other.
        manifest = RunManifest(
            run_id=run["run_id"],
            model_route=deps.generator.route,
            model_digest=deps.generator.digest,
            prompt_version=PROMPT_VERSION,
            corpus_version=doc["data"]["corpus_version"],
            retrieval_mode=doc["data"]["retrieval_mode"],
        )
    except (McpCallFailed, KeyError, ValidationError, ValueError) as exc:
        log.warning("investigate job %s: retrieval failed: %s", job["id"], exc)
        await _fail(deps, lease, RunState.RETRIEVING, RunState.FAILED, "retrieval failed")
        return
    await _event(deps, lease, EventType.TOOL_COMPLETED, {"message": "search_procedures"})
    if not evidence:
        await _fail(deps, lease, RunState.RETRIEVING, RunState.INSUFFICIENT_EVIDENCE, "no procedure section matched")
        return
    async with deps.conn.transaction():
        await persistence.set_tenant(deps.conn, run["tenant_id"])  # the manifest INSERT is RLS-scoped
        await persistence.fenced(deps.conn, lease)
        await persistence.transition_run(
            deps.conn, run_id=run["run_id"], src=RunState.RETRIEVING, dst=RunState.DRAFTING
        )
        # Written before the model is called, so a run whose draft fails still records the route, digest, prompt and
        # corpus it used (R130); one immutable row per run.
        await persistence.insert_run_manifest(deps.conn, tenant_id=run["tenant_id"], manifest=manifest)
    try:
        await _draft_and_freeze(deps, lease, run, text, evidence, manifest)
    except LeaseLost:
        raise  # the lease is gone: the job is handed back, and its next owner fails the interrupted run (INTERRUPTED)
    except ModelUnavailable as exc:
        log.warning("investigate job %s: %s", job["id"], exc)
        await _fail(deps, lease, RunState.DRAFTING, RunState.FAILED, MODEL_UNAVAILABLE)
    except ModelOutputInvalid as exc:
        # Rule names only: the invalid text is never logged or stored (SA:496).
        log.warning("investigate job %s: draft invalid after one repair (%s)", job["id"], exc)
        await _fail(deps, lease, RunState.DRAFTING, RunState.FAILED, MODEL_INVALID)
    except Exception:
        # A failure here fails the run at once with its own reason; handed back instead, the next owner would only
        # find the run interrupted in DRAFTING and fail it as INTERRUPTED.
        log.exception("investigate job %s: drafting or freezing failed", job["id"])
        await _fail(deps, lease, RunState.DRAFTING, RunState.FAILED, "drafting failed")


async def _draft_and_freeze(
    deps: Deps, lease: Lease, run: dict[str, Any], text: str, evidence: list[EvidenceItem], manifest: RunManifest
) -> None:
    """Draft from the evidence and act on the draft's kind; any failure here is the caller's to turn into FAILED."""
    # One hold spans the first pass and its repair (model concurrency 1, BS:549; the TTL covers both, permit.py).
    async with permit.model_permit(deps.conn, holder=deps.worker_name, lease=lease):
        request = DraftRequest(
            asset_id=run["asset_id"],
            text=text,
            start_at=run["start_at"],
            end_at=run["end_at"],
            answer_only=Intent(run["intent"]) is Intent.ANSWER_ONLY,
            # BS:555's 90 s are the run's, counted from the claim as the heartbeat counts them, so the draft gets what
            # retrieval and the permit wait left, less a margin for the unit that follows it.
            remaining_seconds=deps.leases.compute_budget_seconds - lease.held_for() - BUDGET_MARGIN_SECONDS,
        )
        draft = await lease.effect(deps.generator.generate(request, evidence))  # a lease effect (SA:195)
    if draft.kind == "abstain" and not draft.clarification_requested:
        await _fail(deps, lease, RunState.DRAFTING, RunState.INSUFFICIENT_EVIDENCE, ABSTAINED)  # SA:147
        return
    if draft.kind != "proposal":
        # TODO(T20): the graph router sends an answer to ANSWERED and a question to AWAITING_INPUT (SA:137, SA:153).
        await _fail(deps, lease, RunState.DRAFTING, RunState.FAILED, NOT_ROUTED)
        return
    freeze_allowed(Intent(run["intent"]))  # an answer_only run never freezes a proposal (SA:453)
    now = datetime.now(UTC).replace(microsecond=0)
    proposal_id, draft_id = uuid4(), uuid4()
    frozen = proposals.build_proposal(
        tenant_id=run["tenant_id"],
        run_id=run["run_id"],
        proposal_id=proposal_id,
        revision=1,
        asset_id=run["asset_id"],
        start_at=run["start_at"],
        end_at=run["end_at"],
        draft=draft,
        evidence=evidence,
        now=now,
        supersedes_run_id=run["supersedes_run_id"],
    )
    async with deps.conn.transaction():
        await persistence.set_tenant(deps.conn, run["tenant_id"])
        # The share lock before anything else (SA:453's run_lease FOR SHARE, taken here rather than inside
        # freeze_proposal, erratum 47); the drafts INSERT is a fresh row and waits on nobody.
        await persistence.fenced(deps.conn, lease)
        # The worker's own INSERT (AM-20.2 drafts: ins); draft_sha256 is what freeze_proposal recomputes over the
        # bytes it receives and compares (SA:453). The payload itself is never written here (SA:496).
        await deps.conn.execute(
            "INSERT INTO app.drafts (id, tenant_id, run_id, draft_sha256, validated, kind)"
            " VALUES (%s, %s, %s, %s, true, %s)",
            (draft_id, run["tenant_id"], run["run_id"], frozen.sha256, draft.kind),
        )
        await persistence.append_event(
            deps.conn,
            run_id=run["run_id"],
            type=EventType.EXPLANATION_READY,
            payload={
                # A template naming the route and the prompt version (erratum 117), never the model's own summary.
                "message": f"Drafted by model route {manifest.model_route.value} (prompt {manifest.prompt_version}).",
                "evidence_refs": list(frozen.payload.evidence_refs),
            },
            source=EventSource.MODEL_SUMMARY,
        )
        await persistence.freeze_proposal(
            deps.conn,
            run_id=run["run_id"],
            draft_id=draft_id,
            payload_canonical=frozen.canonical,
            expires_at=frozen.payload.expires_at,
        )


async def execute(deps: Deps, job: dict[str, Any], lease: Lease) -> bool:
    """Call `create_incident` on mcp-write for an approved run; True when the job is finished by `handle`, False when
    it was re-queued (its final unit already ran and released the lease).

    Any other envelope counts as final, an `INVALID_HANDLE` included. When that refusal came from this worker's own
    lease lapsing during the call, `handle`'s final unit finds the lease not live and raises LeaseLost, so the job is
    handed back and the next owner runs it again instead of closing it with the run still APPROVED (final review, I1).
    """
    async with deps.conn.transaction():
        await persistence.set_tenant(deps.conn, job["tenant_id"])
        await persistence.fenced(deps.conn, lease)
        run = dict(await persistence.run_row(deps.conn, job["run_id"], lock=True))
        # APPROVED or EXECUTING (JOB_RULES[EXECUTE].run_states): after a transport failure past the grant, the
        # re-queued job resends under the same action id (grant_execution's replay rule; Plan E ruling 6).
        if RunState(run["state"]) not in JOB_RULES[JobType.EXECUTE].run_states:
            log.info("execute job %s: run is %s, nothing to dispatch", job["id"], run["state"])
            return True
        proposal_id: UUID = run["active_proposal_id"]
        handle = await persistence.mint_handle(
            deps.conn,
            run_id=run["run_id"],
            job_id=job["id"],
            server=Server.WRITE,
            azp=deps.workload_azp,
            fence=lease.fence,
        )
    try:
        doc = await lease.effect(
            deps.mcp.call(
                deps.urls.mcp_write, handle=handle, tool="create_incident", arguments={"proposal_id": str(proposal_id)}
            )
        )
    except McpCallFailed as exc:
        # mcp-write owns the grant and the outcome. Before a grant the run is still APPROVED; after one it is EXECUTING
        # and the retry resends under the same action id, which is safe because the grant is one per run. The worker
        # records nothing it did not observe (BUILD_SPEC §1). TODO(T22): bounded retries, reconciliation and AM-13's
        # timeout path (the run is APPROVED or EXECUTING, which the worker may not move, SA:451).
        log.warning("execute job %s: %s; re-queued in %s s", job["id"], exc, EXECUTE_RETRY_SECONDS)
        await persistence.release_lease(deps.conn, lease, job=job, requeue_seconds=EXECUTE_RETRY_SECONDS)
        return False
    data = doc.get("data") or {}
    if is_deferred(doc):
        # TODO(T22): bounded retries (a sweeper that never returns re-queues this job every 30 s for ever).
        log.warning(
            "execute job %s: grant deferred (stale membership sync); re-queued in %s s",
            job["id"],
            EXECUTE_RETRY_SECONDS,
        )
        await persistence.release_lease(deps.conn, lease, job=job, requeue_seconds=EXECUTE_RETRY_SECONDS)
        return False
    log.info("execute job %s: %s %s", job["id"], doc.get("status"), data.get("status"))
    if doc.get("status") == "outcome" and data.get("status") == "UNKNOWN":  # an `error` envelope is never UNKNOWN
        # mcp-write reports uncertainty after SENT but may not record it (SA:467: mark_unknown is the worker's).
        await _mark_unknown(deps, lease)
    return True


async def _mark_unknown(deps: Deps, lease: Lease) -> None:
    """EXECUTING → OUTCOME_UNKNOWN through `mark_unknown`, which takes the lease row FOR UPDATE itself and bumps the
    fence (AM-13, Plan H ruling 9): no `fenced` share lock precedes it in its unit, because a transaction that writes
    the lease takes FOR UPDATE from the start (SA:191). The new fence reaches the shared Lease before anything else
    runs, and a renewal meeting it meanwhile retries instead of declaring the lease lost (ruling 10).

    Raises:
        LeaseLost: the fence was stale, told apart from a run that is not EXECUTING by a fresh `fenced` check rather
            than by the refusal's text.
        VersionConflict: the fence holds, so the run itself is not EXECUTING.
    """
    lease.check()
    lease.begin_refence()
    try:
        async with deps.conn.transaction():
            unknown = await persistence.mark_unknown(deps.conn, lease.run_id, lease.fence)
    except persistence.VersionConflict:
        lease.end_refence(None)
        async with deps.conn.transaction():
            await persistence.fenced(deps.conn, lease)  # a stale fence raises LeaseLost here
        raise
    except BaseException:
        lease.end_refence(None)
        raise
    lease.end_refence(unknown.fence)


async def handle(deps: Deps, job: dict[str, Any], lease: Lease) -> None:
    """Dispatch a claimed job by type under its lease; the final unit closes the job and releases the lease."""
    kind = JobType(job["type"])
    if kind is JobType.INVESTIGATE:
        await investigate(deps, job, lease)
    elif kind is JobType.EXECUTE:
        if not await execute(deps, job, lease):
            return  # re-queued: its final unit already released the lease
    else:
        log.info("job %s of type %s is not handled by the walking skeleton", job["id"], kind.value)
    await persistence.release_lease(deps.conn, lease, job=job)


async def abandon(deps: Deps, job: dict[str, Any], lease: Lease) -> None:
    """The lease is lost (Plan H ruling 19): revoke the handles minted under this fence and hand the job back, in one
    unit, with no transition here (the next owner fails a run it finds interrupted, INTERRUPTED). `revoke_handles`
    never refuses a stale fence (ruling
    8), so this works whoever holds the lease now.

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

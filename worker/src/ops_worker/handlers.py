"""Job handlers (AM-20.4 job types; AM-10 states): every state change goes through the definer functions as role
`worker` (`transition_run`, `freeze_proposal`, `mark_unknown`), and every network call happens outside a transaction
(BUILD_SPEC §11).

`investigate`: QUEUED → RETRIEVING → (read tool) → DRAFTING → fake draft → freeze → AWAITING_APPROVAL. `execute`: mint
a write handle and call `create_incident`; mcp-write performs the grant, the dispatch and the outcome, so the worker
only closes the job. No lease, fence or heartbeat (debt → T13), no LangGraph (→ T20).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from ops_core import persistence
from ops_core.jobs import JOB_RULES, JobType, Server
from ops_core.outcomes import EventSource, EventType
from ops_core.settings import Urls
from ops_core.states import Intent, RunState, freeze_allowed

from ops_worker import proposals
from ops_worker.drafting import DraftGenerator, DraftRequest, EvidenceItem
from ops_worker.mcp import McpCaller, McpCallFailed

log = logging.getLogger("ops_worker")
EXECUTE_RETRY_SECONDS = 30  # how long an execute job waits after mcp-write could not be reached
QUERY_CHARS = 500  # schemas/tools/search_procedures.input.schema.json maxLength


@dataclass
class Deps:
    """What a handler needs: the loop's connection, the MCP client, the model route and the server URLs."""

    conn: persistence.Conn
    mcp: McpCaller
    generator: DraftGenerator
    urls: Urls
    worker_name: str


async def _event(
    deps: Deps,
    run: dict[str, Any],
    type: EventType,
    payload: dict[str, Any],
    source: EventSource = EventSource.APPLICATION,
) -> None:
    async with deps.conn.transaction():  # the function finds the tenant itself (run_directory)
        await persistence.append_event(deps.conn, run_id=run["run_id"], type=type, payload=payload, source=source)


async def _fail(deps: Deps, run: dict[str, Any], src: RunState, dst: RunState, message: str) -> None:
    """A pre-grant failure state through transition_run, which emits the matching run.* event itself (SA:451)."""
    async with deps.conn.transaction():
        await persistence.transition_run(deps.conn, run_id=run["run_id"], src=src, dst=dst, detail={"message": message})


async def investigate(deps: Deps, job: dict[str, Any]) -> None:
    """Retrieve evidence, draft with the model route, freeze the proposal and await approval."""
    tenant_id: UUID = job["tenant_id"]
    async with deps.conn.transaction():
        await persistence.set_tenant(deps.conn, tenant_id)  # the worker's own reads and inserts are RLS-scoped
        run = dict(await persistence.run_row(deps.conn, job["run_id"], lock=True))
        if run["state"] != RunState.QUEUED.value:
            log.info("investigate job %s: run already %s", job["id"], run["state"])
            return
        cur = await deps.conn.execute("SELECT text FROM app.messages WHERE message_id = %s", (run["message_id"],))
        message = await cur.fetchone()
        if message is None:
            raise persistence.NotFound("message not found")
        text = str(message["text"])
        await persistence.transition_run(deps.conn, run_id=run["run_id"], src=RunState.QUEUED, dst=RunState.RETRIEVING)
        handle = await persistence.mint_handle(
            deps.conn, run_id=run["run_id"], job_id=job["id"], server=Server.READ, azp="ops-worker"
        )
    await _event(deps, run, EventType.TOOL_STARTED, {"message": "search_procedures"})
    try:
        # The tool input caps `query` at 500 characters (schemas/tools); the message itself may be 4,000.
        doc = await deps.mcp.call(
            deps.urls.mcp_read,
            handle=handle,
            tool="search_procedures",
            arguments={"query": text[:QUERY_CHARS], "limit": 3, "mode": "lexical"},
        )
        evidence = proposals.evidence_from_search(doc)
    except (McpCallFailed, ValueError) as exc:
        log.warning("investigate job %s: retrieval failed: %s", job["id"], exc)
        await _fail(deps, run, RunState.RETRIEVING, RunState.FAILED, "retrieval failed")
        return
    await _event(deps, run, EventType.TOOL_COMPLETED, {"message": "search_procedures"})
    if not evidence:
        await _fail(deps, run, RunState.RETRIEVING, RunState.INSUFFICIENT_EVIDENCE, "no procedure section matched")
        return
    async with deps.conn.transaction():
        await persistence.transition_run(
            deps.conn, run_id=run["run_id"], src=RunState.RETRIEVING, dst=RunState.DRAFTING
        )
    try:
        await _draft_and_freeze(deps, run, text, evidence, str(doc["data"]["corpus_version"]))
    except Exception:
        # No reclaim until T13: a run left in DRAFTING would hold its conversation slot with the job claimed forever.
        log.exception("investigate job %s: drafting or freezing failed", job["id"])
        await _fail(deps, run, RunState.DRAFTING, RunState.FAILED, "drafting failed")


async def _draft_and_freeze(
    deps: Deps, run: dict[str, Any], text: str, evidence: list[EvidenceItem], corpus_version: str
) -> None:
    """Draft from the evidence and freeze the proposal; any failure here is the caller's to turn into FAILED."""
    request = DraftRequest(asset_id=run["asset_id"], text=text, start_at=run["start_at"], end_at=run["end_at"])
    draft = await deps.generator.generate(request, evidence)
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
        corpus_version=corpus_version,
        now=now,
        supersedes_run_id=run["supersedes_run_id"],
    )
    async with deps.conn.transaction():
        await persistence.set_tenant(deps.conn, run["tenant_id"])
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
                "message": f"Drafted by model route {frozen.manifest.model_route.value} "
                f"(prompt {frozen.manifest.prompt_version}).",
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


async def execute(deps: Deps, job: dict[str, Any]) -> bool:
    """Call `create_incident` on mcp-write for an approved run; True when the job is finished, False when re-queued."""
    async with deps.conn.transaction():
        await persistence.set_tenant(deps.conn, job["tenant_id"])
        run = dict(await persistence.run_row(deps.conn, job["run_id"], lock=True))
        # APPROVED or EXECUTING (JOB_RULES[EXECUTE].run_states): after a transport failure past the grant, the
        # re-queued job resends under the same action id (grant_execution's replay rule; Plan E ruling 6).
        if RunState(run["state"]) not in JOB_RULES[JobType.EXECUTE].run_states:
            log.info("execute job %s: run is %s, nothing to dispatch", job["id"], run["state"])
            return True
        proposal_id: UUID = run["active_proposal_id"]
        handle = await persistence.mint_handle(
            deps.conn, run_id=run["run_id"], job_id=job["id"], server=Server.WRITE, azp="ops-worker"
        )
    try:
        doc = await deps.mcp.call(
            deps.urls.mcp_write, handle=handle, tool="create_incident", arguments={"proposal_id": str(proposal_id)}
        )
    except McpCallFailed as exc:
        # mcp-write owns the grant and the outcome; the run stays APPROVED and the job retries, which is safe because
        # create_incident is idempotent per run. The worker records nothing it did not observe (BUILD_SPEC §1).
        # TODO(T13): bounded retries; TODO(T22): reconciliation.
        log.warning("execute job %s: %s; re-queued in %s s", job["id"], exc, EXECUTE_RETRY_SECONDS)
        async with deps.conn.transaction():
            await persistence.set_tenant(deps.conn, job["tenant_id"])  # RLS: without it the UPDATE touches no row
            await persistence.requeue_job(deps.conn, job["id"], EXECUTE_RETRY_SECONDS)
        return False
    data = doc.get("data") or {}
    log.info("execute job %s: %s %s", job["id"], doc.get("status"), data.get("status"))
    if data.get("status") == "UNKNOWN":
        # mcp-write reports uncertainty after SENT but may not record it (SA:467: mark_unknown is the worker's).
        async with deps.conn.transaction():
            await persistence.mark_unknown(deps.conn, run["run_id"])
    return True


async def handle(deps: Deps, job: dict[str, Any]) -> None:
    """Dispatch a claimed job by type, then revoke its handles and mark it done unless the handler re-queued it."""
    kind = JobType(job["type"])
    if kind is JobType.INVESTIGATE:
        await investigate(deps, job)
    elif kind is JobType.EXECUTE:
        if not await execute(deps, job):
            return
    else:
        log.info("job %s of type %s is not handled by the walking skeleton", job["id"], kind.value)
    async with deps.conn.transaction():
        if job.get("run_id") is not None:
            await persistence.revoke_handles(deps.conn, job["run_id"])  # BS:364: handles die with the job
        await persistence.set_tenant(deps.conn, job["tenant_id"])
        await persistence.finish_job(deps.conn, job["id"])

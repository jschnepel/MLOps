"""Job handlers (AM-20.4 job types; AM-10 states): every state change goes through `persistence.transition` with the
performer the spec names, and every network call happens outside a transaction (BUILD_SPEC §11).

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
from ops_core.jobs import JobType, Server
from ops_core.outcomes import EventSource, EventType
from ops_core.settings import Urls
from ops_core.states import Intent, Performer, RunState, freeze_allowed
from psycopg.types.json import Jsonb

from ops_worker import proposals
from ops_worker.drafting import DraftGenerator, DraftRequest
from ops_worker.mcp import McpCaller, McpCallFailed

log = logging.getLogger("ops_worker")
QUERY_CHARS = 500  # schemas/tools/search_procedures.input.schema.json maxLength


@dataclass
class Deps:
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
    async with deps.conn.transaction():
        await persistence.append_event(
            deps.conn,
            tenant_id=run["tenant_id"],
            conversation_id=run["conversation_id"],
            run_id=run["run_id"],
            type=type,
            source=source,
            payload=payload,
        )


async def _fail(deps: Deps, run: dict[str, Any], dst: RunState, type: EventType, message: str) -> None:
    async with deps.conn.transaction():
        await persistence.transition(deps.conn, run_id=run["run_id"], dst=dst, performer=Performer.TRANSITION_RUN)
        await persistence.append_event(
            deps.conn,
            tenant_id=run["tenant_id"],
            conversation_id=run["conversation_id"],
            run_id=run["run_id"],
            type=type,
            source=EventSource.APPLICATION,
            payload={"message": message},
        )


async def investigate(deps: Deps, job: dict[str, Any]) -> None:
    """Retrieve evidence, draft with the model route, freeze the proposal and await approval."""
    async with deps.conn.transaction():
        run = dict(await persistence.run_row(deps.conn, job["run_id"], lock=True))
        if run["state"] != RunState.QUEUED.value:
            log.info("investigate job %s: run already %s", job["id"], run["state"])
            return
        cur = await deps.conn.execute("SELECT text FROM app.messages WHERE message_id = %s", (run["message_id"],))
        message = await cur.fetchone()
        if message is None:
            raise persistence.NotFound("message not found")
        text = str(message["text"])
        await persistence.transition(
            deps.conn, run_id=run["run_id"], dst=RunState.RETRIEVING, performer=Performer.TRANSITION_RUN
        )
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
        await _fail(deps, run, RunState.FAILED, EventType.RUN_FAILED, "retrieval failed")
        return
    await _event(deps, run, EventType.TOOL_COMPLETED, {"message": "search_procedures"})
    if not evidence:
        await _fail(
            deps,
            run,
            RunState.INSUFFICIENT_EVIDENCE,
            EventType.RUN_INSUFFICIENT_EVIDENCE,
            "no procedure section matched",
        )
        return
    async with deps.conn.transaction():
        await persistence.transition(
            deps.conn, run_id=run["run_id"], dst=RunState.DRAFTING, performer=Performer.TRANSITION_RUN
        )
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
        corpus_version=str(doc["data"]["corpus_version"]),
        now=now,
    )
    async with deps.conn.transaction():
        # drafts.draft_sha256 is the hash freeze_proposal (T09) recomputes and compares: the payload's hash.
        await deps.conn.execute(
            "INSERT INTO app.drafts (id, run_id, draft_sha256, validated, kind) VALUES (%s, %s, %s, true, %s)",
            (draft_id, run["run_id"], frozen.sha256, draft.kind),
        )
        await deps.conn.execute(
            "INSERT INTO app.proposals (proposal_id, tenant_id, run_id, revision, draft_id, payload, payload_canonical,"
            " payload_sha256, canonicalization_version, authored_by, expires_at)"
            " VALUES (%s, %s, %s, 1, %s, %s, %s, %s, 1, %s, %s)",
            (
                proposal_id,
                run["tenant_id"],
                run["run_id"],
                draft_id,
                Jsonb(frozen.payload.canonical_dict()),
                frozen.canonical,
                frozen.sha256,
                [run["requester"]],
                frozen.payload.expires_at,
            ),
        )
        await deps.conn.execute(
            "UPDATE app.runs SET active_proposal_id = %s WHERE run_id = %s", (proposal_id, run["run_id"])
        )
        await persistence.transition(
            deps.conn, run_id=run["run_id"], dst=RunState.AWAITING_APPROVAL, performer=Performer.FREEZE_PROPOSAL
        )
        await persistence.append_event(
            deps.conn,
            tenant_id=run["tenant_id"],
            conversation_id=run["conversation_id"],
            run_id=run["run_id"],
            type=EventType.EXPLANATION_READY,
            source=EventSource.MODEL_SUMMARY,
            payload={
                "message": f"Drafted by model route {frozen.manifest.model_route.value} "
                f"(prompt {frozen.manifest.prompt_version}).",
                "evidence_refs": list(frozen.payload.evidence_refs),
            },
        )
        await persistence.append_event(
            deps.conn,
            tenant_id=run["tenant_id"],
            conversation_id=run["conversation_id"],
            run_id=run["run_id"],
            type=EventType.PROPOSAL_READY,
            source=EventSource.APPLICATION,
            payload={"proposal_id": str(proposal_id)},
        )


async def execute(deps: Deps, job: dict[str, Any]) -> None:
    """Call `create_incident` on mcp-write for an approved run; mcp-write owns the grant and the outcome."""
    async with deps.conn.transaction():
        run = dict(await persistence.run_row(deps.conn, job["run_id"], lock=True))
        if run["state"] != RunState.APPROVED.value:
            log.info("execute job %s: run is %s, nothing to dispatch", job["id"], run["state"])
            return
        proposal_id: UUID = run["active_proposal_id"]
        handle = await persistence.mint_handle(
            deps.conn, run_id=run["run_id"], job_id=job["id"], server=Server.WRITE, azp="ops-worker"
        )
    try:
        doc = await deps.mcp.call(
            deps.urls.mcp_write, handle=handle, tool="create_incident", arguments={"proposal_id": str(proposal_id)}
        )
    except McpCallFailed as exc:
        # mcp-write owns the grant and the outcome; if the call never reached it nothing happened, and if it did the
        # outcome is recorded there. The worker records nothing it did not observe (BUILD_SPEC §1). TODO(T22).
        log.warning("execute job %s: %s", job["id"], exc)
        return
    data = doc.get("data") or {}
    log.info("execute job %s: %s %s", job["id"], doc.get("status"), data.get("status"))


async def handle(deps: Deps, job: dict[str, Any]) -> None:
    """Dispatch a claimed job by type, then mark it done."""
    kind = JobType(job["type"])
    if kind is JobType.INVESTIGATE:
        await investigate(deps, job)
    elif kind is JobType.EXECUTE:
        await execute(deps, job)
    else:
        log.info("job %s of type %s is not handled by the walking skeleton", job["id"], kind.value)
    async with deps.conn.transaction():
        await persistence.finish_job(deps.conn, job["id"])

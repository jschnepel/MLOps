"""The worker graph's nodes (AM-12 SA:207): deterministic Python around the definer functions, one model call and the
MCP reads and writes.

Every node rereads the run before it acts (SA:215: LangGraph re-runs a node from its start on resume, so each must be
idempotent against authoritative state) and returns the run state it left, so `route_request` routes on what the
database says. Every unit that writes opens with `persistence.fenced`; every MCP call, model call and back-off sleep
is a lease effect (`Lease.effect`, SA:195); state changes go through `transition_run`, `freeze_proposal` and
`mark_unknown` as role `worker` (AM-20.3). Only `draft_with_langchain` calls the model; only `retrieve_evidence` calls
mcp-read and only `execute_approved_proposal` calls mcp-write (`reconcile_outcome`'s calls arrive with T22).

Text stays out of graph state (R091): the evidence bundle and a validated draft are held in the graph run's
`Context.held` between the node that makes them and the node that consumes them; `route_request` notices a hold that
a resumed graph run no longer has and routes the run back through retrieval (BS:423). A question reaches the requester
inside its `clarification.requested` event and an answer inside its `explanation.ready` event (erratum 124); the
interrupts carry event and proposal ids only (SA:563).
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID, uuid4

from langgraph.runtime import Runtime
from langgraph.types import interrupt
from ops_core import persistence
from ops_core.canonical import canonical_sha256
from ops_core.contracts import ModelDraft
from ops_core.jobs import JobType, Server, Tool
from ops_core.lease import LeaseLost
from ops_core.outcomes import EventSource, EventType
from ops_core.routing import DraftKind, Evidence, GraphRoute, RunManifest, route_graph
from ops_core.states import Intent, RunState, freeze_allowed
from pydantic import ValidationError

from ops_worker import evidence, permit, proposals
from ops_worker.drafting import PROMPT_VERSION, DraftRequest, ModelOutputInvalid, ModelUnavailable
from ops_worker.evidence import Bundle
from ops_worker.graph.state import Context, HeldDraft, RunGraphState, key
from ops_worker.mcp import TRANSPORT, UNAUTHENTICATED, McpCallFailed

log = logging.getLogger("ops_worker")
QUERY_CHARS: Final = 500  # schemas/tools/search_procedures.input.schema.json maxLength
ALERT_LIMIT: Final = 20  # one page of the run's alerts; the bundle shows evidence.ALERTS_SHOWN of them
RETRIEVAL_MODE: Final = "lexical"  # the only mode the worker asks for; choosing it per run is TODO(T25)
READ_CALLS: Final = 6  # BS:552: at most 6 read calls per graph run, retries included
READ_RETRIES: Final = 2  # BS:552: at most 2 retries of one transient read
RETRY_SECONDS: Final = 0.5  # BS:562: the first back-off; doubled per retry, with jitter
CLARIFY_ROUNDS: Final = 2  # SA:137: at most two clarification rounds; a third question ends INSUFFICIENT_EVIDENCE
REPLY_CHARS: Final = 4000  # the message contract's bound (contracts.MessageText); the API checked it on the way in
ASSET_UNKNOWN: Final = "NOT_FOUND"  # mcp-read's code for an asset the asset service does not know (T16 ruling 15)
# The draft stops this long before the run's compute budget ends, so the freeze or the failure unit after it still
# runs inside the budget, before the heartbeat's own gate ("compute budget spent") could cancel the call.
BUDGET_MARGIN_SECONDS: Final = 5.0

# Templated outcomes (BS:516): never the model's text, never an exception's.
MODEL_UNAVAILABLE: Final = "the model route did not answer in time or could not be reached"
MODEL_INVALID: Final = "the model's draft failed validation after its one repair"
ABSTAINED: Final = "the model found the evidence insufficient"
DRAFTING_FAILED: Final = "drafting failed"
RETRIEVAL_FAILED: Final = "retrieval failed"
READ_REFUSED: Final = "retrieval failed: the read server refused the worker's token"
CONTEXT_MISSING: Final = "the asset is not known to the asset service"
EVIDENCE_INSUFFICIENT: Final = "no fresh asset status or no procedure section matched"
CLARIFY_LIMIT: Final = "the model asked a third clarifying question; the evidence stays insufficient"
ANSWERED: Final = "answered from the retrieved evidence; no incident was proposed"
RESUME_REFUSED: Final = "the clarification reply is not the latest answer to the run's latest question"
CHECKPOINT_MISSING: Final = "the stored checkpoint is missing; the run was not resumed"
WORKFLOW_FAILED: Final = "the workflow failed"

_S = RunState
# The worker's only ways to FAILED from a state that waits or works (transition_run, SA:451): AWAITING_INPUT may only
# go back to QUEUED, and QUEUED only on to RETRIEVING, so a run that cannot be resumed walks there first.
PATH_TO_FAILED: Final[dict[RunState, tuple[RunState, ...]]] = {
    _S.AWAITING_INPUT: (_S.QUEUED, _S.RETRIEVING, _S.FAILED),
    _S.QUEUED: (_S.RETRIEVING, _S.FAILED),
    _S.RETRIEVING: (_S.FAILED,),
    _S.DRAFTING: (_S.FAILED,),
}


# What a node returns when the graph run does not hold the draft or bundle the state names: the run goes back
# through retrieval and drafting (a second model call; nothing text-bearing was persisted, SA:496).
LOST: Final[dict[str, Any]] = {"draft_kind": DraftKind.NONE.value, "draft_id": None, "evidence": Evidence.UNKNOWN.value}


class Requeue(Exception):
    """mcp-write could not be reached, or deferred the grant: the execute job goes back on the queue (the handler's
    final unit re-queues it) and the graph run ends with its checkpoint before `execute_approved_proposal`."""


def _run_id(state: RunGraphState) -> UUID:
    return UUID(state["run_id"])


@asynccontextmanager
async def unit(ctx: Context, *, fence: bool = True) -> AsyncIterator[persistence.Conn]:
    """One transaction on the loop connection under the job's tenant; a writing unit opens with the fence (SA:176)."""
    conn = ctx.deps.conn
    async with conn.transaction():
        await persistence.set_tenant(conn, ctx.job["tenant_id"])  # the worker's reads and inserts are RLS-scoped
        if fence:
            await persistence.fenced(conn, ctx.lease)  # run_lease before runs (SA:188)
        yield conn


async def facts(ctx: Context, run_id: UUID) -> dict[str, Any]:
    """The router's authoritative dimensions, reread (SA:215)."""
    async with unit(ctx, fence=False) as conn:
        found = await persistence.graph_facts(conn, run_id)
    return {
        "run_state": found.state.value,
        "intent": found.intent.value,
        "decision_present": found.decision_present,
        "attempt_state": None if found.attempt_state is None else found.attempt_state.value,
    }


async def event(
    ctx: Context, type: EventType, payload: dict[str, Any], source: EventSource = EventSource.APPLICATION
) -> None:
    """One event in its own fenced unit."""
    async with unit(ctx) as conn:
        await persistence.append_event(conn, run_id=ctx.lease.run_id, type=type, payload=payload, source=source)


async def fail(ctx: Context, src: RunState, dst: RunState, message: str) -> dict[str, Any]:
    """A pre-grant end through transition_run, which emits the matching run.* event itself (SA:451)."""
    async with unit(ctx) as conn:
        await persistence.transition_run(conn, run_id=ctx.lease.run_id, src=src, dst=dst, detail={"message": message})
    return {"run_state": dst.value}


async def fail_from(conn: persistence.Conn, run_id: UUID, current: RunState, message: str) -> None:
    """FAILED with `message` from a waiting or working state, inside the caller's fenced unit (PATH_TO_FAILED)."""
    src = current
    for dst in PATH_TO_FAILED[current]:
        detail = {"message": message} if dst is RunState.FAILED else None
        await persistence.transition_run(conn, run_id=run_id, src=src, dst=dst, detail=detail)
        src = dst


async def insert_draft(conn: persistence.Conn, run: dict[str, Any], held: HeldDraft, sha256: str) -> None:
    """The `drafts` row (AM-20.2 drafts: ins): the draft's id, kind and hash, never its text (SA:496)."""
    await conn.execute(
        "INSERT INTO app.drafts (id, tenant_id, run_id, draft_sha256, validated, kind)"
        " VALUES (%s, %s, %s, %s, true, %s)",
        (held.draft_id, run["tenant_id"], run["run_id"], sha256, held.draft.kind),
    )


def draft_sha256(draft: ModelDraft) -> str:
    """The hash of a validated draft that is not a proposal (a proposal's is its frozen payload's)."""
    return canonical_sha256(draft.model_dump(mode="json"))


def _instant(value: Any) -> str:
    return str(value.isoformat()).replace("+00:00", "Z")


async def load_run(state: RunGraphState, runtime: Runtime[Context]) -> dict[str, Any]:
    """The graph run's first node: the run's facts from the database, nothing from the job."""
    runtime.context.trace.append("load_run")
    return await facts(runtime.context, _run_id(state))


async def route_request(state: RunGraphState, runtime: Runtime[Context]) -> dict[str, Any]:
    """The graph router's node (AM-16). The route itself is `ops_core.routing.route_graph`, read by the conditional
    edges `build.py` generates from the table. This node rereads the run's state, intent, decision and attempt on every
    hop (BS:305, SA:215: the router routes on authoritative dimensions only, whatever an earlier node or a forked
    checkpoint left in state; Plan Q round 1, I1), and drops a draft kind or an evidence verdict whose hold this graph
    run does not have (a resumed run in a new process), so the run retrieves again before it drafts (BS:423)."""
    ctx = runtime.context
    ctx.trace.append("route_request")
    update: dict[str, Any] = await facts(ctx, _run_id(state))
    if state["draft_kind"] != DraftKind.NONE.value and _held(ctx, state) is None:
        update |= LOST
    if state["evidence"] == Evidence.SUFFICIENT.value and ctx.held.bundle is None:
        update["evidence"] = Evidence.UNKNOWN.value
    return update


async def read(ctx: Context, handle: str, tool: Tool, arguments: dict[str, Any], calls: list[int]) -> dict[str, Any]:
    """One read tool, bracketed by its tool events, retried while the failure is transient (BS:552, BS:562).

    Raises:
        McpCallFailed: the read failed for good, or the run's read budget is spent.
    """
    await event(ctx, EventType.TOOL_STARTED, {"message": tool.value})
    retries = 0
    while True:
        if calls[0] <= 0:  # before every call, the first of a read included: the seventh call is never made
            raise McpCallFailed(f"{tool.value}: the run's {READ_CALLS}-call read budget is spent", code=TRANSPORT)
        calls[0] -= 1
        try:
            doc = await ctx.lease.effect(
                ctx.deps.mcp.call(ctx.deps.urls.mcp_read, handle=handle, tool=tool.value, arguments=arguments)
            )
            break
        except McpCallFailed as exc:
            if not exc.retryable or retries >= READ_RETRIES or calls[0] <= 0:
                raise  # with the budget spent, the failure itself is what is reported, without a back-off first
            retries += 1
            log.info("read %s failed (%s); retry %s", tool.value, exc.code, retries)
            await ctx.lease.effect(asyncio.sleep(RETRY_SECONDS * 2 ** (retries - 1) * random.uniform(0.5, 1.0)))
    await event(ctx, EventType.TOOL_COMPLETED, {"message": tool.value})
    return doc


async def request_text(conn: persistence.Conn, run: dict[str, Any]) -> str:
    """The confirmed request: the run's message and every clarification reply, oldest first (read, never held)."""
    text = await persistence.message_text(conn, run["message_id"])
    for _, payload in await persistence.run_events(conn, run["run_id"], EventType.CLARIFICATION_RECEIVED):
        reply = await persistence.message_text(conn, UUID(str(payload["message_id"])))
        text += f"\n\nClarification from the requester: {reply}"
    return text


async def retrieve_evidence(state: RunGraphState, runtime: Runtime[Context]) -> dict[str, Any]:
    """QUEUED → RETRIEVING, the three reads (status, the interval's alerts, the procedure search), the code rule, and
    RETRIEVING → DRAFTING with the run manifest when the evidence suffices (R038: every read completes first)."""
    ctx = runtime.context
    ctx.trace.append("retrieve_evidence")
    deps, lease, job = ctx.deps, ctx.lease, ctx.job
    async with unit(ctx) as conn:
        run = dict(await persistence.run_row(conn, _run_id(state), lock=True))
        current = RunState(run["state"])
        if current is RunState.QUEUED:
            await persistence.transition_run(conn, run_id=run["run_id"], src=current, dst=RunState.RETRIEVING)
            current = RunState.RETRIEVING
        elif current not in (RunState.RETRIEVING, RunState.DRAFTING):
            return {"run_state": current.value}
        text = await request_text(conn, run)
        handle = await persistence.mint_handle(
            conn, run_id=run["run_id"], job_id=job["id"], server=Server.READ, azp=deps.workload_azp, fence=lease.fence
        )
    calls = [READ_CALLS]
    try:
        try:
            status = await read(ctx, handle, Tool.GET_ASSET_STATUS, {"asset_id": run["asset_id"]}, calls)
        except McpCallFailed as exc:
            if exc.code != ASSET_UNKNOWN:
                raise
            return {"run_state": current.value, "context_resolved": False}  # contract erratum 4: no draft without it
        window = {"start_at": _instant(run["start_at"]), "end_at": _instant(run["end_at"])}
        alerts = await read(
            ctx, handle, Tool.GET_RECENT_ALERTS, {"asset_id": run["asset_id"], **window, "limit": ALERT_LIMIT}, calls
        )
        search = await read(
            ctx,
            handle,
            Tool.SEARCH_PROCEDURES,
            {"query": text[:QUERY_CHARS], "limit": 3, "mode": RETRIEVAL_MODE},
            calls,
        )
        procedures = proposals.evidence_from_search(search)
        # The manifest records the corpus version and the mode the tool reports it ran, so a result without them, or
        # with values the manifest refuses, is a retrieval failure like any other (T19).
        manifest = RunManifest(
            run_id=run["run_id"],
            model_route=deps.generator.route,
            model_digest=deps.generator.digest,
            prompt_version=PROMPT_VERSION,
            corpus_version=search["data"]["corpus_version"],
            retrieval_mode=search["data"]["retrieval_mode"],
        )
        verdict = evidence.sufficient(status, search)
        seen = evidence.observations(status, alerts)
    except McpCallFailed as exc:
        log.warning("job %s: retrieval failed (%s): %s", job["id"], exc.code, exc)
        # TODO(T22): a bounded re-queue of the job instead of FAILED once the in-node retries are spent.
        return await fail(
            ctx, current, RunState.FAILED, READ_REFUSED if exc.code == UNAUTHENTICATED else RETRIEVAL_FAILED
        )
    except (KeyError, TypeError, ValidationError, ValueError) as exc:
        log.warning("job %s: retrieval failed: %s", job["id"], exc)
        return await fail(ctx, current, RunState.FAILED, RETRIEVAL_FAILED)
    if not verdict:
        return {"run_state": current.value, "context_resolved": True, "evidence": Evidence.INSUFFICIENT.value}
    ctx.held.bundle = Bundle(text, procedures, seen, manifest)
    if current is RunState.RETRIEVING:
        async with unit(ctx) as conn:
            await persistence.transition_run(conn, run_id=run["run_id"], src=current, dst=RunState.DRAFTING)
            # Written before the model is called, so a run whose draft fails still records the route, digest, prompt
            # and corpus it used (R130); one immutable row per run, so a run retrieving again after a clarification
            # keeps the one it has (erratum 125). A run resumed in DRAFTING never gets here.
            if not await persistence.run_manifest_exists(conn, run["run_id"]):
                await persistence.insert_run_manifest(conn, tenant_id=run["tenant_id"], manifest=manifest)
    return {"run_state": RunState.DRAFTING.value, "context_resolved": True, "evidence": Evidence.SUFFICIENT.value}


async def draft_with_langchain(state: RunGraphState, runtime: Runtime[Context]) -> dict[str, Any]:
    """The model route's draft from the held bundle, under one model permit; the validated draft is held, its id and
    kind go into state. An outage, an invalid draft or any other failure ends the run FAILED with a template."""
    ctx = runtime.context
    ctx.trace.append("draft_with_langchain")
    deps, lease, bundle = ctx.deps, ctx.lease, ctx.held.bundle
    if bundle is None:  # a graph run resumed here in a new process: retrieve again first (BS:423)
        return {"evidence": Evidence.UNKNOWN.value}
    async with unit(ctx, fence=False) as conn:
        run = dict(await persistence.run_row(conn, _run_id(state)))
    if RunState(run["state"]) is not RunState.DRAFTING:
        return {"run_state": run["state"]}
    try:
        # One hold spans the first pass and its repair (model concurrency 1, BS:549; the TTL covers both, permit.py).
        async with permit.model_permit(deps.conn, holder=deps.worker_name, lease=lease):
            request = DraftRequest(
                asset_id=run["asset_id"],
                text=bundle.text,
                start_at=run["start_at"],
                end_at=run["end_at"],
                answer_only=Intent(run["intent"]) is Intent.ANSWER_ONLY,
                # BS:555's 90 s are the run's, counted from the claim as the heartbeat counts them, so the draft gets
                # what retrieval and the permit wait left, less a margin for the unit that follows it.
                remaining_seconds=deps.leases.compute_budget_seconds - lease.held_for() - BUDGET_MARGIN_SECONDS,
                observations=bundle.observations,
            )
            draft = await lease.effect(deps.generator.generate(request, bundle.procedures))
    except LeaseLost:
        raise  # the job is handed back; its next owner resumes the run from the stored checkpoint
    except ModelUnavailable as exc:
        log.warning("job %s: %s", ctx.job["id"], exc)
        return await fail(ctx, RunState.DRAFTING, RunState.FAILED, MODEL_UNAVAILABLE)
    except ModelOutputInvalid as exc:
        # Rule names only: the invalid text is never logged or stored (SA:496).
        log.warning("job %s: draft invalid after one repair (%s)", ctx.job["id"], exc)
        return await fail(ctx, RunState.DRAFTING, RunState.FAILED, MODEL_INVALID)
    except Exception:
        log.exception("job %s: drafting failed", ctx.job["id"])
        return await fail(ctx, RunState.DRAFTING, RunState.FAILED, DRAFTING_FAILED)
    held = HeldDraft(uuid4(), draft)
    ctx.held.draft = held
    kind = DraftKind.QUESTION if draft.clarification_requested else DraftKind(draft.kind)
    return {"draft_id": str(held.draft_id), "draft_kind": kind.value}


def _held(ctx: Context, state: RunGraphState) -> HeldDraft | None:
    """The held draft the state names, or None when this graph run does not hold it (resumed in a new process)."""
    held = ctx.held.draft
    return held if held is not None and str(held.draft_id) == state["draft_id"] else None


async def validate_and_freeze(state: RunGraphState, runtime: Runtime[Context]) -> dict[str, Any]:
    """The held proposal frozen through `freeze_proposal` (SA:453) with its `drafts` row and `explanation.ready`, in
    one unit; the run moves to AWAITING_APPROVAL (or BLOCKED_REVIEW on a guard refusal)."""
    ctx = runtime.context
    ctx.trace.append("validate_and_freeze")
    held, bundle = _held(ctx, state), ctx.held.bundle
    if held is None or bundle is None:
        return dict(LOST)
    try:
        async with unit(ctx) as conn:
            run = dict(await persistence.run_row(conn, _run_id(state), lock=True))
            if RunState(run["state"]) is not RunState.DRAFTING:
                return {"run_state": run["state"]}
            freeze_allowed(Intent(run["intent"]))  # the table's intent gate, checked again where it matters (SA:453)
            frozen = proposals.build_proposal(
                tenant_id=run["tenant_id"],
                run_id=run["run_id"],
                proposal_id=uuid4(),
                revision=1,  # TODO(T21): the revision a re-entered run freezes (Plan Q ruling 13)
                asset_id=run["asset_id"],
                start_at=run["start_at"],
                end_at=run["end_at"],
                draft=held.draft,
                evidence=bundle.procedures,
                now=datetime.now(UTC).replace(microsecond=0),
                supersedes_run_id=run["supersedes_run_id"],
            )
            await insert_draft(conn, run, held, frozen.sha256)  # draft_sha256 is what freeze_proposal recomputes
            await persistence.append_event(
                conn,
                run_id=run["run_id"],
                type=EventType.EXPLANATION_READY,
                payload={
                    # A template naming the route and the prompt version (erratum 117), never the model's summary.
                    "message": (
                        f"Drafted by model route {bundle.manifest.model_route.value} "
                        f"(prompt {bundle.manifest.prompt_version})."
                    ),
                    "evidence_refs": list(frozen.payload.evidence_refs),
                },
                source=EventSource.MODEL_SUMMARY,
            )
            await persistence.freeze_proposal(
                conn,
                run_id=run["run_id"],
                draft_id=held.draft_id,
                payload_canonical=frozen.canonical,
                expires_at=frozen.payload.expires_at,
            )
            after = dict(await persistence.run_row(conn, run["run_id"]))
    except LeaseLost:
        raise
    except Exception:
        log.exception("job %s: freezing failed", ctx.job["id"])
        return await fail(ctx, RunState.DRAFTING, RunState.FAILED, DRAFTING_FAILED)
    ctx.held.draft = None
    return {"run_state": after["state"]}


async def await_clarification(state: RunGraphState, runtime: Runtime[Context]) -> dict[str, Any]:
    """Ask the held question and wait for the reply (SA:137, SA:147). Asking is one unit: the `drafts` row and
    DRAFTING → AWAITING_INPUT, whose `clarification.requested` event carries the question; a third question ends the
    run INSUFFICIENT_EVIDENCE instead. The node then interrupts with the question's event id (an id, SA:563), so the
    graph run ends and the handler releases the lease (R022). Resumed with a `clarification.received` event id
    (`Command(resume=...)`, SA:213), it re-runs from its start: the run is AWAITING_INPUT now, so it only checks that
    the reply is the latest answer to the latest question, rereads it, and moves the run back to QUEUED."""
    ctx = runtime.context
    ctx.trace.append("await_clarification")
    run_id = _run_id(state)
    async with unit(ctx, fence=False) as conn:
        run = dict(await persistence.run_row(conn, run_id))
        asked_before = len(await persistence.run_events(conn, run_id, EventType.CLARIFICATION_REQUESTED))
    current = RunState(run["state"])
    if current is RunState.DRAFTING:
        held = _held(ctx, state)
        if held is None:
            return dict(LOST)
        async with unit(ctx) as conn:
            await insert_draft(conn, run, held, draft_sha256(held.draft))
            if asked_before >= CLARIFY_ROUNDS:
                await persistence.transition_run(
                    conn,
                    run_id=run_id,
                    src=current,
                    dst=RunState.INSUFFICIENT_EVIDENCE,
                    detail={"message": CLARIFY_LIMIT},
                )
                ctx.held.draft = None
                return {"run_state": RunState.INSUFFICIENT_EVIDENCE.value}
            await persistence.transition_run(
                conn, run_id=run_id, src=current, dst=RunState.AWAITING_INPUT, detail={"message": held.draft.question}
            )
        ctx.held.draft = None
        current = RunState.AWAITING_INPUT
    if current is RunState.QUEUED:  # a resumed run whose reply was already taken: retrieve again
        async with unit(ctx, fence=False) as conn:  # the round it answered still counts (round 1, M7)
            requested = await persistence.run_events(conn, run_id, EventType.CLARIFICATION_REQUESTED)
        latest = [str(requested[-1][0])] if requested else []
        asked = state["asked"] + [q for q in latest if q not in state["asked"]]
        return {
            "run_state": current.value,
            "asked": asked,
            "evidence": Evidence.UNKNOWN.value,
            "draft_kind": DraftKind.NONE.value,
        }
    if current is not RunState.AWAITING_INPUT:
        return {"run_state": current.value}
    async with unit(ctx, fence=False) as conn:
        requested = await persistence.run_events(conn, run_id, EventType.CLARIFICATION_REQUESTED)
    question = str(requested[-1][0])
    answer = interrupt(question)  # ends the graph run here; on resume, the clarification.received event's id
    async with unit(ctx) as conn:
        run = dict(await persistence.run_row(conn, run_id, lock=True))
        if RunState(run["state"]) is not RunState.AWAITING_INPUT:
            return {"run_state": run["state"]}  # cancelled meanwhile
        received = await persistence.run_events(conn, run_id, EventType.CLARIFICATION_RECEIVED)
        reply = received[-1] if received else None
        text = None
        if reply is not None and str(reply[0]) == str(answer) and reply[1].get("question_id") == question:
            text = await persistence.message_text(conn, UUID(str(reply[1]["message_id"])))
        if text is None or not 0 < len(text) <= REPLY_CHARS:
            await fail_from(conn, run_id, RunState.AWAITING_INPUT, RESUME_REFUSED)
            return {"run_state": RunState.FAILED.value}
        await persistence.transition_run(conn, run_id=run_id, src=RunState.AWAITING_INPUT, dst=RunState.QUEUED)
    asked = [*state["asked"], question]
    if len(asked) != len(requested):  # the database counts the rounds (SA:215); the state's list is a cross-check
        log.warning("run %s: %s questions asked, %s resumed in this thread", run_id, len(requested), len(asked))
    return {
        "run_state": RunState.QUEUED.value,
        "asked": asked,
        "context_resolved": True,
        "evidence": Evidence.UNKNOWN.value,
        "draft_kind": DraftKind.NONE.value,
        "draft_id": None,
    }


async def publish_state(state: RunGraphState, runtime: Runtime[Context]) -> dict[str, Any]:
    """The graph run's last node. On the `answer_only` route: the held answer's summary and citations in
    `explanation.ready` and DRAFTING → ANSWERED, with its `drafts` row, in one unit (SA:153, R114); on `abstain`:
    → INSUFFICIENT_EVIDENCE with the reason's template; on `publish`: nothing left to write."""
    ctx = runtime.context
    ctx.trace.append("publish_state")
    route = route_graph(key(state))
    run_id = _run_id(state)
    if route is GraphRoute.PUBLISH:
        return {}
    async with unit(ctx) as conn:
        run = dict(await persistence.run_row(conn, run_id, lock=True))
        current = RunState(run["state"])
        if current.value != state["run_state"]:
            return {"run_state": current.value}  # cancelled meanwhile
        held = _held(ctx, state)
        if route is GraphRoute.ANSWER_ONLY:
            if held is None:
                return dict(LOST)
            await insert_draft(conn, run, held, draft_sha256(held.draft))
            await persistence.append_event(
                conn,
                run_id=run_id,
                type=EventType.EXPLANATION_READY,
                # The validated answer itself (erratum 124): the requester's answer, cited, never a status claim.
                payload={"message": held.draft.summary, "evidence_refs": list(held.draft.evidence_refs)},
                source=EventSource.MODEL_SUMMARY,
            )
            dst, message = RunState.ANSWERED, ANSWERED
        else:
            if not state["context_resolved"]:
                message = CONTEXT_MISSING
            elif state["evidence"] == Evidence.INSUFFICIENT.value:
                message = EVIDENCE_INSUFFICIENT
            else:
                if held is not None:  # a lost abstention needs no text: only its drafts row is missing
                    await insert_draft(conn, run, held, draft_sha256(held.draft))
                message = ABSTAINED
            dst = RunState.INSUFFICIENT_EVIDENCE
        await persistence.transition_run(conn, run_id=run_id, src=current, dst=dst, detail={"message": message})
    ctx.held.draft = None
    return {"run_state": dst.value}


async def await_independent_decision(state: RunGraphState, runtime: Runtime[Context]) -> dict[str, Any]:
    """Wait for the reviewer (BS:330): reread, and while the run awaits approval interrupt with its proposal's id. The
    execute job that `record_decision` queues resumes the node, which rereads the decision rather than trusting the
    resume value."""
    ctx = runtime.context
    ctx.trace.append("await_independent_decision")
    run_id = _run_id(state)
    async with unit(ctx, fence=False) as conn:
        run = dict(await persistence.run_row(conn, run_id))
    if RunState(run["state"]) is RunState.AWAITING_APPROVAL:
        interrupt(str(run["active_proposal_id"]))
    return await facts(ctx, run_id)


def is_deferred(doc: dict[str, Any]) -> bool:
    """An `error` envelope whose code is GRANT_DEFERRED: the gate found the membership sync stale (T11), so the job
    is retried rather than closed."""
    error = doc.get("error") or {}
    return doc.get("status") == "error" and error.get("code") == "GRANT_DEFERRED"


async def execute_approved_proposal(state: RunGraphState, runtime: Runtime[Context]) -> dict[str, Any]:
    """`create_incident` on mcp-write for the approved run (T47's path, unchanged): mcp-write performs the grant, the
    dispatch and the outcome, and the worker records an UNKNOWN envelope through `mark_unknown`.

    Any other envelope counts as final, an `INVALID_HANDLE` included. When that refusal came from this worker's own
    lease lapsing during the call, the handler's final unit finds the lease not live and raises LeaseLost, so the job
    is handed back and the next owner runs it again (Plan H final review, I1).

    Only an execute job calls mcp-write (AM-15's allowlist). Another job's graph run can get here when the decision
    commits just before the reviewer wait's reread; it leaves the APPROVED run for the execute job `record_decision`
    queued and ends (Plan Q review of T20, M1).

    Raises:
        Requeue: mcp-write could not be reached, or deferred the grant.
    """
    ctx = runtime.context
    ctx.trace.append("execute_approved_proposal")
    deps, lease, job = ctx.deps, ctx.lease, ctx.job
    if job["type"] != JobType.EXECUTE.value:
        log.info(
            "job %s of type %s reached the execute node; the run waits for its execute job", job["id"], job["type"]
        )
        return await facts(ctx, _run_id(state))
    async with unit(ctx) as conn:
        run = dict(await persistence.run_row(conn, _run_id(state), lock=True))
        if RunState(run["state"]) not in (RunState.APPROVED, RunState.EXECUTING):
            return {"run_state": run["state"]}
        handle = await persistence.mint_handle(
            conn, run_id=run["run_id"], job_id=job["id"], server=Server.WRITE, azp=deps.workload_azp, fence=lease.fence
        )
    try:
        doc = await lease.effect(
            deps.mcp.call(
                deps.urls.mcp_write,
                handle=handle,
                tool=Tool.CREATE_INCIDENT.value,
                arguments={"proposal_id": str(run["active_proposal_id"])},
            )
        )
    except McpCallFailed as exc:
        # Before a grant the run is still APPROVED; after one it is EXECUTING and the retry resends under the same
        # action id. TODO(T22): bounded retries, reconciliation and AM-13's timeout path.
        log.warning("execute job %s: %s; re-queued", job["id"], exc)
        raise Requeue(str(exc)) from exc
    if is_deferred(doc):
        # TODO(T22): bounded retries (a sweeper that never returns re-queues this job every 30 s for ever).
        log.warning("execute job %s: grant deferred (stale membership sync); re-queued", job["id"])
        raise Requeue("grant deferred")
    data = doc.get("data") or {}
    log.info("execute job %s: %s %s", job["id"], doc.get("status"), data.get("status"))
    if doc.get("status") == "outcome" and data.get("status") == "UNKNOWN":  # an `error` envelope is never UNKNOWN
        await mark_unknown(ctx)
    return await facts(ctx, _run_id(state))


async def mark_unknown(ctx: Context) -> None:
    """EXECUTING → OUTCOME_UNKNOWN through `mark_unknown`, which takes the lease row FOR UPDATE itself and bumps the
    fence (AM-13, Plan H ruling 9): no `fenced` share lock precedes it in its unit, because a transaction that writes
    the lease takes FOR UPDATE from the start (SA:191). The new fence reaches the shared Lease before anything else
    runs, and a renewal meeting it meanwhile retries instead of declaring the lease lost (ruling 10).

    Raises:
        LeaseLost: the fence was stale, told apart from a run that is not EXECUTING by a fresh `fenced` check rather
            than by the refusal's text.
        VersionConflict: the fence holds, so the run itself is not EXECUTING.
    """
    lease, conn = ctx.lease, ctx.deps.conn
    lease.check()
    lease.begin_refence()
    try:
        async with conn.transaction():
            unknown = await persistence.mark_unknown(conn, lease.run_id, lease.fence)
    except persistence.VersionConflict:
        lease.end_refence(None)
        async with conn.transaction():
            await persistence.fenced(conn, lease)  # a stale fence raises LeaseLost here
        raise
    except BaseException:
        lease.end_refence(None)
        raise
    lease.end_refence(unknown.fence)


async def reconcile_outcome(state: RunGraphState, runtime: Runtime[Context]) -> dict[str, Any]:
    """The recover route's node, and the end of an execute job's graph run (Plan Q ruling 14). Recovery and
    reconciliation of an unknown outcome are T22's: the node rereads the run and ends the graph run."""
    ctx = runtime.context
    ctx.trace.append("reconcile_outcome")
    found = await facts(ctx, _run_id(state))
    if found["run_state"] in (RunState.OUTCOME_UNKNOWN.value, RunState.ESCALATED.value):
        # TODO(T22): recover jobs reconcile the original action id here (get_incident_receipt, abort_incident).
        log.info("run %s is %s; recovery arrives with T22", state["run_id"], found["run_state"])
    return found

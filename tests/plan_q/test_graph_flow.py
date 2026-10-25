"""The worker graph on LangGraph's in-memory saver and Plan H's fakes (T20; SA:207-218; R038, R042, R091, R108, R114,
DoD 1-3), without a database.

Catches: a read that completes after the model is called, or a draft without the status and alerts; a checkpoint id
stored outside the fence, or a stored id that is not the checkpoint holding the interrupt; an invocation without
`durability="sync"` or the checkpoint stream; an answer that freezes a proposal or does not end ANSWERED with its
cited summary; a question that does not release the lease, or a reply that does not resume the run where it waited;
a third question that waits again; a reply that is not the latest that is still taken; a stray newer head that a
resume follows; a crash (twice) that is not resumed from the stored checkpoint, or that writes a second manifest; a
missing stored checkpoint that leaves a run active; model or evidence text inside a checkpoint; a router that routes
on dimensions an earlier node left stale (an approved run that forked from before its freeze could then never
execute); an execute job that resumes with a decision that is not the run's approval of its active proposal; a lost
hold after a completed draft that is not drafted again; and a transient
read that is not retried, a read retried past BS:552's budget, a refused token that is retried or reported as an
ordinary failure, or an unknown asset that is not the "context missing" abstention.
"""

import asyncio
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from ops_core import persistence
from ops_core.contracts import ModelDraft
from ops_core.lease import Lease, LeaseLost
from ops_core.outcomes import EventType
from ops_worker import handlers, main
from ops_worker.drafting import DraftRequest, EvidenceItem, FakeDraftGenerator
from ops_worker.graph import build, nodes
from ops_worker.graph.state import Context, initial
from ops_worker.mcp import TRANSPORT, UNAUTHENTICATED, McpCallFailed

from tests.plan_h.test_worker_units import JOB, RUN, RUN_ID, SEARCH, SUCCEEDED, Log, make, patch
from tests.plan_q.fixtures import ALERTS, STATUS

DRAFT = {"title": "t", "evidence_refs": ["ALPHA-INCIDENT:v2:review"], "assumptions": [], "limitations": []}
QUESTION = ModelDraft(**{**DRAFT, "kind": "abstain", "evidence_refs": [], "summary": "s", "question": "Which hours?"})
ANSWER = ModelDraft(**{**DRAFT, "kind": "answer", "summary": "B22 shows no warning that needs an incident."})
THREAD = build.thread_id(RUN_ID, 1)


class Scripted(FakeDraftGenerator):
    """The fake route answering from a script (None: the fake's own draft); keeps every request it got."""

    def __init__(self, *drafts: ModelDraft | BaseException | None) -> None:
        super().__init__()
        self.drafts = list(drafts)
        self.requests: list[DraftRequest] = []

    async def generate(self, request: DraftRequest, evidence: list[EvidenceItem]) -> ModelDraft:
        self.requests.append(request)
        nxt = self.drafts.pop(0) if self.drafts else None
        if isinstance(nxt, BaseException):
            raise nxt
        return nxt if nxt is not None else await super().generate(request, evidence)


@dataclass
class World:
    """One run's fakes: the log, the kept run row (with its events), the saver every job of the run shares, and the
    contexts the graph runs were given (their node logs)."""

    log: Log
    run: dict[str, Any]
    saver: InMemorySaver
    contexts: list[Context]


def world(monkeypatch: pytest.MonkeyPatch, run: dict[str, Any] | None = None) -> World:
    log = Log()
    current = patch(monkeypatch, log, run=run)
    contexts: list[Context] = []
    real = handlers.Context

    def recording(*args: Any, **kwargs: Any) -> Context:
        ctx = real(*args, **kwargs)
        contexts.append(ctx)
        return ctx

    monkeypatch.setattr(handlers, "Context", recording)
    monkeypatch.setattr(nodes, "RETRY_SECONDS", 0.0)
    return World(log, current, InMemorySaver(), contexts)


def job(
    w: World, generator: Any, kind: str = "investigate", mcp: Any = None, **extra: Any
) -> tuple[handlers.Deps, Lease]:
    """Run one job of the run on a fresh Deps (a fresh process's holds) over the run's saver."""
    deps, lease = make(w.log)
    deps.saver, deps.generator = w.saver, generator
    deps.mcp = mcp or deps.mcp
    asyncio.run(handlers.handle(deps, {**JOB, "type": kind, **extra}, lease))
    return deps, lease


def transitions(w: World) -> list[str]:
    return [e for e in w.log.entries if e == "transition_run"]


def approve(w: World, proposal: Any = None) -> None:
    """What record_decision commits for an approval (0004): APPROVED and `approval.recorded {proposal_id}`."""
    w.run["state"] = "APPROVED"
    chosen = str(RUN["active_proposal_id"] if proposal is None else proposal)
    w.run["events"][EventType.APPROVAL_RECORDED] = [(uuid4(), {"proposal_id": chosen})]


def lose_once_after(monkeypatch: pytest.MonkeyPatch, w: World, entry: str) -> None:
    """The next fence check after `entry` is logged finds the fence moved, once (a lost lease or a stopped process
    between two units); later checks pass."""
    armed = [True]

    async def fenced(_conn: Any, lease: Lease) -> None:
        w.log.entries.append("fenced")
        if armed[0] and entry in w.log.entries:
            armed[0] = False
            lease.mark_lost("the fence moved")
            raise LeaseLost("run lease lost")

    monkeypatch.setattr(persistence, "fenced", fenced)


def handed_back(w: World, generator: Any) -> None:
    """One investigate job that loses its lease and is handed back (`main.run_job` → `abandon`)."""
    deps, lease = make(w.log)
    deps.saver, deps.generator = w.saver, generator
    asyncio.run(main.run_job(deps, persistence.Claimed(dict(JOB), lease)))
    assert w.log.units()[-1] == ["set_tenant", "revoke_handles", "unclaim_job"]


def snapshot(w: World, checkpoint_id: str | None) -> Any:
    graph = build.build_graph(w.saver)
    return asyncio.run(graph.aget_state(build.config(THREAD, checkpoint_id)))


def test_every_read_completes_before_the_model_is_called(monkeypatch: pytest.MonkeyPatch) -> None:
    w = world(monkeypatch)
    generator = Scripted()
    job(w, generator)
    assert w.contexts[0].trace == [
        "load_run",
        "route_request",
        "retrieve_evidence",
        "route_request",
        "draft_with_langchain",
        "route_request",
        "validate_and_freeze",
        "route_request",
        "await_independent_decision",
    ]  # R038's node log: retrieval, then drafting, then the freeze and the wait (DoD 1)
    calls = [e for e in w.log.entries if e.startswith("mcp:")]
    assert calls == ["mcp:get_asset_status", "mcp:get_recent_alerts", "mcp:search_procedures"]
    assert w.log.entries.index("mcp:search_procedures") < w.log.entries.index("take_model_permit")
    (request,) = generator.requests
    assert [o.section for o in request.observations] == ["asset status", "alert"]  # BS:419: status and alerts too
    assert w.run["state"] == "AWAITING_APPROVAL"


def test_every_checkpoint_is_stored_under_the_fence_and_the_last_holds_the_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    w = world(monkeypatch)
    job(w, Scripted())
    stores = [u for u in w.log.units() if "store_checkpoint_id" in u]
    assert stores and all(u == ["set_tenant", "fenced", "store_checkpoint_id"] for u in stores)
    stored = w.run["checkpoint_id"]
    waiting = snapshot(w, stored)
    assert waiting.next == ("await_independent_decision",) and len(waiting.interrupts) == 1  # SA:211
    assert waiting.interrupts[0].value == str(RUN["active_proposal_id"])  # an id, never the proposal (SA:563)
    assert len(stores) == len(list(w.saver.list(build.config(THREAD, None))))  # every checkpoint, once each
    assert w.log.entries[-1] == "release_lease"  # the wait holds no lease (R022)


def test_every_invocation_is_sync_and_streams_checkpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    w = world(monkeypatch)
    seen: list[dict[str, Any]] = []
    real = build.build_graph

    class Spy:
        def __init__(self, graph: Any) -> None:
            self.graph = graph

        def astream(self, *args: Any, **kwargs: Any) -> Any:
            seen.append(kwargs)
            return self.graph.astream(*args, **kwargs)

        def __getattr__(self, name: str) -> Any:
            return getattr(self.graph, name)

    monkeypatch.setattr(build, "build_graph", lambda *a, **k: Spy(real(*a, **k)))
    job(w, Scripted())
    approve(w)
    job(w, Scripted(), "execute")
    assert len(seen) == 2 and all(s["durability"] == "sync" and s["stream_mode"] == "checkpoints" for s in seen)
    assert "mcp:create_incident" in w.log.entries  # the decision's resume reached the execute node (ruling 14)


@pytest.mark.parametrize("intent", ["answer_only", "investigate"])
def test_an_answer_ends_answered_with_its_cited_summary_and_no_proposal(
    monkeypatch: pytest.MonkeyPatch, intent: str
) -> None:
    """R114 on any intent (DEV-002 is an investigate run that ends ANSWERED); the fake route answers answer_only."""
    w = world(monkeypatch, {**RUN, "intent": intent})
    events: list[dict[str, Any]] = []
    moves: list[tuple[str, Any]] = []
    append, move = persistence.append_event, persistence.transition_run

    async def keep_event(*args: Any, **kwargs: Any) -> Any:
        events.append(kwargs)
        return await append(*args, **kwargs)

    async def keep_move(*args: Any, **kwargs: Any) -> Any:
        moves.append((kwargs["dst"].value, kwargs.get("detail")))
        return await move(*args, **kwargs)

    monkeypatch.setattr(persistence, "append_event", keep_event)
    monkeypatch.setattr(persistence, "transition_run", keep_move)
    job(w, Scripted(None if intent == "answer_only" else ANSWER))
    assert moves[-1] == ("ANSWERED", {"message": nodes.ANSWERED})
    (explained,) = [e for e in events if e["type"] is EventType.EXPLANATION_READY]
    assert explained["payload"]["evidence_refs"] == ["ALPHA-INCIDENT:v2:review"]  # the answer cites its evidence
    assert explained["payload"]["message"].startswith("For A17" if intent == "answer_only" else "B22 shows")
    assert "freeze_proposal" not in w.log.entries and w.log.entries.count("insert") == 2  # manifest and drafts row
    assert w.contexts[0].trace[-1] == "publish_state" and w.log.entries[-1] == "release_lease"


def reply(w: World, text: str = "Clarification: asset A17, hours 24") -> str:
    """What the API's record_reply writes (store.py): the reply message and clarification.received; returns the
    job key `run_id:question_id` (SA:501)."""
    question = w.run["events"][EventType.CLARIFICATION_REQUESTED][-1][0]
    message = uuid4()
    received = w.run["events"].setdefault(EventType.CLARIFICATION_RECEIVED, [])
    received.append((uuid4(), {"question_id": str(question), "message_id": str(message)}))
    w.run["messages"][message] = text  # the reply message's own text, read back through its id
    return f"{RUN_ID}:{question}"


def test_a_question_waits_without_a_lease_and_the_reply_resumes_it(monkeypatch: pytest.MonkeyPatch) -> None:
    w = world(monkeypatch)
    job(w, Scripted(QUESTION))
    assert w.run["state"] == "AWAITING_INPUT" and w.log.entries[-1] == "release_lease"  # R022: the wait is free
    ((asked, payload),) = w.run["events"][EventType.CLARIFICATION_REQUESTED]
    assert payload == {"message": "Which hours?"}  # the question rides in its event (erratum 124)
    waiting = snapshot(w, w.run["checkpoint_id"])
    assert [i.value for i in waiting.interrupts] == [str(asked)]  # SA:211: the stored id holds the interrupt
    key = reply(w)
    generator = Scripted(None)
    job(w, generator, "resume_input", dedup_key=key)
    assert w.run["state"] == "AWAITING_APPROVAL"  # resumed where it waited, then retrieved and drafted again
    assert w.contexts[-1].trace[:3] == ["await_clarification", "route_request", "retrieve_evidence"]
    (request,) = generator.requests
    assert request.text == (  # the run's message, then the reply read through the reply message's own id
        "Investigate the alerts on A17 over the last 24 hours."
        "\n\nClarification from the requester: Clarification: asset A17, hours 24"
    )
    assert snapshot(w, w.run["checkpoint_id"]).values["asked"] == [str(asked)]  # ids only, the round counted
    assert w.log.entries.count("run_manifest_exists") == 2 and w.log.entries.count("insert") == 3  # one manifest


def test_a_third_question_ends_the_run_insufficient(monkeypatch: pytest.MonkeyPatch) -> None:
    w = world(monkeypatch)
    w.run["events"][EventType.CLARIFICATION_REQUESTED] = [(uuid4(), {}), (uuid4(), {})]  # two rounds already
    job(w, Scripted(QUESTION))
    assert w.run["state"] == "INSUFFICIENT_EVIDENCE"
    assert len(w.run["events"][EventType.CLARIFICATION_REQUESTED]) == 2  # not asked again (SA:137)


def test_a_reply_that_is_not_the_latest_fails_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    w = world(monkeypatch)
    job(w, Scripted(QUESTION))
    key = reply(w)
    w.run["events"][EventType.CLARIFICATION_RECEIVED].append((uuid4(), {"question_id": "elsewhere"}))
    moves: list[str] = []
    move = persistence.transition_run

    async def keep(*args: Any, **kwargs: Any) -> Any:
        moves.append(kwargs["dst"].value)
        return await move(*args, **kwargs)

    monkeypatch.setattr(persistence, "transition_run", keep)
    start = len(w.log.entries)
    job(w, Scripted(), "resume_input", dedup_key=key)
    assert moves == ["QUEUED", "RETRIEVING", "FAILED"]  # the worker's only path to FAILED from AWAITING_INPUT
    assert not [e for e in w.log.entries[start:] if e.startswith("mcp:")]  # refused before any read


def test_a_stray_newer_head_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """DoD 2 (R108): a checkpoint written after the stored one, as a stale writer could, is not what a resume reads."""
    w = world(monkeypatch)
    job(w, Scripted())
    stored = w.run["checkpoint_id"]
    graph = build.build_graph(w.saver)
    stray = asyncio.run(graph.aupdate_state(build.config(THREAD, None), {"run_state": "FAILED"}))
    stray_id = stray["configurable"]["checkpoint_id"]
    assert snapshot(w, None).values["run_state"] == "FAILED"  # the thread's head is the stray now
    approve(w)
    job(w, Scripted(), "execute")
    assert "mcp:create_incident" in w.log.entries  # the stray's FAILED would have published instead
    assert w.run["checkpoint_id"] not in (stored, stray_id)
    lineage = snapshot(w, w.run["checkpoint_id"])
    while lineage.parent_config is not None and lineage.config["configurable"]["checkpoint_id"] != stored:
        lineage = snapshot(w, lineage.parent_config["configurable"]["checkpoint_id"])
    assert lineage.config["configurable"]["checkpoint_id"] == stored  # the new branch grows from the stored id


def test_a_run_interrupted_twice_mid_draft_resumes_from_the_stored_checkpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ruling 12, review note 2 ("two crashes in a row"): each lost lease hands the job back; each next owner forks
    from the stored checkpoint, retrieves again (its holds are gone, BS:423) and drafts; one manifest in all."""
    w = world(monkeypatch)
    for _ in range(2):
        handed_back(w, Scripted(LeaseLost("lost mid-draft")))
        assert w.run["state"] == "DRAFTING"
    before = len(transitions(w))
    job(w, Scripted())
    assert w.run["state"] == "AWAITING_APPROVAL"
    assert w.contexts[-1].trace[:3] == ["draft_with_langchain", "route_request", "retrieve_evidence"]
    assert len(transitions(w)) == before  # RETRIEVING -> DRAFTING is not repeated (only the freeze moved it)
    assert w.log.entries.count("insert") == 2  # one manifest (the first job's) and one drafts row (the freeze)
    sources = {c.metadata.get("source") for c in w.saver.list(build.config(THREAD, None))}
    assert "fork" in sources  # crash recovery forks (SA:214)


def test_a_missing_stored_checkpoint_fails_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    w = world(monkeypatch, {**RUN, "state": "DRAFTING", "checkpoint_id": "no-such-checkpoint"})
    moves: list[tuple[str, Any]] = []
    move = persistence.transition_run

    async def keep(*args: Any, **kwargs: Any) -> Any:
        moves.append((kwargs["dst"].value, kwargs.get("detail")))
        return await move(*args, **kwargs)

    monkeypatch.setattr(persistence, "transition_run", keep)
    job(w, Scripted())
    assert moves == [("FAILED", {"message": nodes.CHECKPOINT_MISSING})] and w.log.entries[-1] == "release_lease"


@pytest.mark.parametrize("draft", [None, QUESTION], ids=["proposal", "question"])
def test_no_checkpoint_holds_model_or_evidence_text(monkeypatch: pytest.MonkeyPatch, draft: ModelDraft | None) -> None:
    """R091 on the in-memory saver: every stored checkpoint, blob and pending write holds no draft or question text,
    no request text and no alert message (the live test greps the Postgres tables too)."""
    w = world(monkeypatch)
    job(w, Scripted(draft))
    stored = repr((w.saver.storage, w.saver.writes, w.saver.blobs))
    assert w.saver.storage and w.saver.blobs  # there is something to search
    for text in ("Review synthetic warnings", "Which hours?", "Bearing temperature", "Investigate the alerts"):
        assert text not in stored, text


class Failing:
    """mcp-read failing the status read `times` times with `failure`, then answering as Plan H's caller does."""

    def __init__(self, failure: McpCallFailed, times: int) -> None:
        self.failure, self.times, self.calls = failure, times, []

    async def call(self, url: str, *, handle: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(tool)
        if tool == "get_asset_status" and self.times:
            self.times -= 1
            raise self.failure
        return {"get_asset_status": STATUS, "get_recent_alerts": ALERTS, "search_procedures": SEARCH}[tool]


@pytest.mark.parametrize(
    ("failure", "times", "state", "message", "status_calls"),
    [
        (McpCallFailed("x", code=TRANSPORT, retryable=True), 2, "AWAITING_APPROVAL", None, 3),
        (McpCallFailed("x", code="UNAVAILABLE", retryable=True), 9, "FAILED", nodes.RETRIEVAL_FAILED, 3),
        (McpCallFailed("x", code=UNAUTHENTICATED), 9, "FAILED", nodes.READ_REFUSED, 1),
        (McpCallFailed("x", code="NOT_FOUND"), 9, "INSUFFICIENT_EVIDENCE", nodes.CONTEXT_MISSING, 1),
    ],
    ids=["two-retries-then-ok", "retries-spent", "token-refused", "asset-unknown"],
)
def test_reads_retry_transient_failures_only(
    monkeypatch: pytest.MonkeyPatch, failure: McpCallFailed, times: int, state: str, message: str, status_calls: int
) -> None:
    w = world(monkeypatch)
    moves: list[Any] = []
    move = persistence.transition_run

    async def keep(*args: Any, **kwargs: Any) -> Any:
        moves.append((kwargs["dst"].value, (kwargs.get("detail") or {}).get("message")))
        return await move(*args, **kwargs)

    monkeypatch.setattr(persistence, "transition_run", keep)
    caller = Failing(failure, times)
    job(w, FakeDraftGenerator(), mcp=caller)
    assert w.run["state"] == state and caller.calls.count("get_asset_status") == status_calls
    if message is not None:
        assert moves[-1] == (state, message)


def test_the_router_rereads_the_runs_dimensions(monkeypatch: pytest.MonkeyPatch) -> None:
    """Round 1, I1: route_request routes on the database's state, intent, decision and attempt, never on what an
    earlier node or a forked checkpoint left in the graph state."""
    w = world(monkeypatch, {**RUN, "state": "EXECUTING"})
    deps, lease = make(w.log)
    ctx = Context(deps, dict(JOB), lease)
    stale = {**initial(RUN_ID), "run_state": "QUEUED", "decision_present": False, "attempt_state": None}
    update = asyncio.run(nodes.route_request(stale, SimpleNamespace(context=ctx)))
    assert {k: update[k] for k in ("run_state", "intent", "decision_present", "attempt_state")} == {
        "run_state": "EXECUTING",
        "intent": "investigate",
        "decision_present": True,
        "attempt_state": "SENT",
    }
    assert "graph_facts" in w.log.entries


def test_an_approved_run_resumed_from_before_its_freeze_executes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Round 1, I1's scenario: the freeze commits, the lease is lost at the next checkpoint store, so the stored id is
    the checkpoint before validate_and_freeze (no interrupt). After the approval, the execute job forks from it; the
    lost hold sends the run back to the router, which rereads APPROVED with its decision, and the proposal runs."""
    w = world(monkeypatch)
    lose_once_after(monkeypatch, w, "freeze_proposal")
    handed_back(w, Scripted())
    assert w.run["state"] == "AWAITING_APPROVAL"
    assert snapshot(w, w.run["checkpoint_id"]).next == ("validate_and_freeze",)
    approve(w)
    job(w, Scripted(), "execute")
    assert w.log.entries.count("mcp:create_incident") == 1 and w.log.entries[-1] == "release_lease"


def test_an_execute_job_with_a_decision_for_another_proposal_runs_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Round 1, M1: the resume value is checked against the database first; a latest approval that names another
    proposal than the run's active one ends the job with no graph run, no transition and no write call."""
    w = world(monkeypatch)
    job(w, Scripted())
    approve(w, proposal=uuid4())
    moves = len(transitions(w))
    start = len(w.log.entries)
    job(w, Scripted(), "execute")
    assert "mcp:create_incident" not in w.log.entries and len(transitions(w)) == moves
    assert "store_checkpoint_id" not in w.log.entries[start:] and w.log.entries[-1] == "release_lease"


def test_a_hold_lost_after_a_completed_draft_is_drafted_again(monkeypatch: pytest.MonkeyPatch) -> None:
    """Round 1, M4: the draft completed, the lease was lost at the next checkpoint store, so the stored id is still the
    checkpoint before the draft node; the next owner resumes there with no hold, retrieves again and asks the route a
    second time (a second generation for the run: BS:554/555, debt -> T29)."""
    w = world(monkeypatch)
    lose_once_after(monkeypatch, w, "release_model_permit")
    first = Scripted()
    handed_back(w, first)
    assert w.run["state"] == "DRAFTING" and len(first.requests) == 1
    second = Scripted()
    job(w, second)
    assert len(second.requests) == 1 and w.run["state"] == "AWAITING_APPROVAL"
    assert w.contexts[-1].trace[:3] == ["draft_with_langchain", "route_request", "retrieve_evidence"]


REFUSED = {"status": "error", "data": None, "error": {"code": "GRANT_REFUSED", "message": "refused"}}


class Answering:
    """mcp-write answering from a list of envelopes, one per call (the reads are never asked of it)."""

    def __init__(self, log: Log, *docs: dict[str, Any]) -> None:
        self.log, self.docs = log, list(docs)

    async def call(self, url: str, *, handle: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.log.entries.append(f"mcp:{tool}")
        return self.docs.pop(0)


def test_a_redispatched_execute_job_after_a_final_refusal_calls_mcp_write_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review round 1, I1: a final refusal ends the graph at a terminal checkpoint, which is what the stored id is.
    Forking it would run no node, so the re-armed job (a refusal that cleared, wakeups.py) starts a new graph run,
    whose router reads APPROVED and whose execute node rereads everything."""
    w = world(monkeypatch)
    job(w, Scripted())
    approve(w)
    job(w, Scripted(), "execute", mcp=Answering(w.log, REFUSED))
    assert w.run["state"] == "APPROVED" and w.log.entries.count("mcp:create_incident") == 1
    assert snapshot(w, w.run["checkpoint_id"]).next == ()  # the stored checkpoint is the graph run's end
    job(w, Scripted(), "execute", mcp=Answering(w.log, SUCCEEDED))
    assert w.log.entries.count("mcp:create_incident") == 2 and w.log.entries[-1] == "release_lease"
    assert w.contexts[-1].trace[-2:] == ["execute_approved_proposal", "reconcile_outcome"]


def test_an_investigate_job_never_calls_the_write_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    """Review round 1, M1: the decision lands between the freeze and the reviewer wait's reread, so the router sends
    this investigate job to the execute route. Only an execute job calls mcp-write: the graph run ends, the run stays
    APPROVED for the real execute job, and the lease is released."""
    w = world(monkeypatch)
    freeze = persistence.freeze_proposal

    async def freeze_then_approve(*args: Any, **kwargs: Any) -> None:
        await freeze(*args, **kwargs)
        approve(w)  # record_decision commits right after the freeze

    monkeypatch.setattr(persistence, "freeze_proposal", freeze_then_approve)
    job(w, Scripted())  # Plan H's caller answers the reads, and a write call as well (so one would be logged)
    assert w.run["state"] == "APPROVED" and "mcp:create_incident" not in w.log.entries
    assert w.contexts[0].trace[-2:] == ["execute_approved_proposal", "reconcile_outcome"]
    assert w.log.entries[-1] == "release_lease"
    job(w, Scripted(), "execute", mcp=Answering(w.log, SUCCEEDED))  # the real execute job runs it
    assert w.log.entries.count("mcp:create_incident") == 1


def releases(monkeypatch: pytest.MonkeyPatch, w: World) -> list[int | None]:
    """The final unit as the handler calls it: logged like Plan H's recorder, with the `requeue_seconds` it was given
    (None: the job is finished)."""
    seen: list[int | None] = []

    async def release_lease(
        _conn: Any, lease: Lease, *, job: dict[str, Any], requeue_seconds: int | None = None
    ) -> None:
        w.log.entries.append("release_lease")
        seen.append(requeue_seconds)

    monkeypatch.setattr(persistence, "release_lease", release_lease)
    return seen


def test_a_failure_in_a_state_the_graph_does_not_fail_releases_the_lease_and_requeues_the_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review round 1, M2 and round 2, R1: an unexpected failure with the run APPROVED is re-raised for the poll loop,
    but only after the lease is released and the job re-queued (never finished), so the job itself retries."""
    w = world(monkeypatch, {**RUN, "state": "APPROVED"})
    seen = releases(monkeypatch, w)

    class Crashing:
        async def call(self, url: str, *, handle: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError("mcp-write exploded")

    with pytest.raises(RuntimeError):
        job(w, Scripted(), "execute", mcp=Crashing())
    assert w.run["state"] == "APPROVED" and w.log.entries[-1] == "release_lease"
    assert seen == [handlers.FAILURE_RETRY_SECONDS]


def test_a_resume_that_fails_unexpectedly_keeps_its_job_open(monkeypatch: pytest.MonkeyPatch) -> None:
    """Review round 2, R1: the reply was taken (the API refuses a second one) and nothing but this job wakes a run in
    AWAITING_INPUT, so a resume_input job that fails unexpectedly is re-queued, not finished."""
    w = world(monkeypatch)
    job(w, Scripted(QUESTION))
    key = reply(w)
    seen = releases(monkeypatch, w)

    async def saver_read_failed(*_: Any, **__: Any) -> bool:
        raise RuntimeError("the saver could not be read")

    monkeypatch.setattr(build, "known", saver_read_failed)
    with pytest.raises(RuntimeError):
        job(w, Scripted(), "resume_input", dedup_key=key)
    assert w.run["state"] == "AWAITING_INPUT" and seen == [handlers.FAILURE_RETRY_SECONDS]


def test_a_lease_lost_without_being_marked_is_not_released_with_an_error(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Review round 2, R3: mint_handle raises LeaseLost without marking the lease lost; the release after the failure
    meets the lost lease too, which is one INFO line, never a second error with a traceback."""
    w = world(monkeypatch, {**RUN, "state": "APPROVED"})

    async def no_live_lease(*_: Any, **__: Any) -> str:
        raise LeaseLost("no live lease at this fence")

    async def release_finds_it_lost(_conn: Any, lease: Lease, **_: Any) -> None:
        w.log.entries.append("release_lease")
        lease.mark_lost("another owner holds the lease, or it lapsed")
        raise LeaseLost("run lease lost")

    monkeypatch.setattr(persistence, "mint_handle", no_live_lease)
    monkeypatch.setattr(persistence, "release_lease", release_finds_it_lost)
    with caplog.at_level("INFO", logger="ops_worker"), pytest.raises(LeaseLost):
        job(w, Scripted(), "execute")
    assert not [r for r in caplog.records if r.levelno >= 40 or r.exc_info]


def test_a_lost_lease_is_not_released_again(monkeypatch: pytest.MonkeyPatch) -> None:
    """Review round 1, M2: the release after a failure is a no-op once the lease is lost, never a second error."""
    w = world(monkeypatch)
    lose_once_after(monkeypatch, w, "transition_run")
    with pytest.raises(LeaseLost):
        job(w, Scripted())
    assert "release_lease" not in w.log.entries


def test_an_execute_job_whose_approval_was_rejected_runs_no_graph(monkeypatch: pytest.MonkeyPatch) -> None:
    """Review round 1, M4: a run.rejected event refuses the resume even when the approval names the active proposal."""
    w = world(monkeypatch)
    job(w, Scripted())
    approve(w)
    w.run["events"][EventType.RUN_REJECTED] = [(uuid4(), {})]
    moves, start = len(transitions(w)), len(w.log.entries)
    job(w, Scripted(), "execute")
    assert "mcp:create_incident" not in w.log.entries and len(transitions(w)) == moves
    assert "store_checkpoint_id" not in w.log.entries[start:] and w.log.entries[-1] == "release_lease"


def test_a_resume_with_no_reply_to_its_question_fails_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """Review round 1, M4: a resume_input job whose key names a question nobody answered fails the run with the
    template, by the worker's only path to FAILED from AWAITING_INPUT, before any read."""
    w = world(monkeypatch)
    job(w, Scripted(QUESTION))
    question = w.run["events"][EventType.CLARIFICATION_REQUESTED][-1][0]
    moves: list[tuple[str, Any]] = []
    move = persistence.transition_run

    async def keep(*args: Any, **kwargs: Any) -> Any:
        moves.append((kwargs["dst"].value, (kwargs.get("detail") or {}).get("message")))
        return await move(*args, **kwargs)

    monkeypatch.setattr(persistence, "transition_run", keep)
    start = len(w.log.entries)
    job(w, Scripted(), "resume_input", dedup_key=f"{RUN_ID}:{question}")
    assert moves == [("QUEUED", None), ("RETRIEVING", None), ("FAILED", nodes.RESUME_REFUSED)]
    assert not [e for e in w.log.entries[start:] if e.startswith("mcp:")] and w.log.entries[-1] == "release_lease"

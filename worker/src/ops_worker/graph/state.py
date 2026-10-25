"""The worker graph's state and the context its nodes run with (AM-12 SA:207-218, SA:563).

Graph state is identifiers, verdicts and enum values only (R091): the run's id and its last-read state, the router's
other dimensions, a draft's id and kind, and the ids of the clarification events this thread has asked and resumed.
No evidence excerpt, model text, question or answer is ever a state value, so no checkpoint holds one. What a node
needs beyond that lives in the per-graph-run `Context` (the job, the lease, the dependencies and `Held`, the
worker's in-memory hold of the evidence bundle and the validated draft between the node that makes them and the node
that consumes them, SA:496).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TypedDict
from uuid import UUID

from ops_core.contracts import ModelDraft
from ops_core.lease import Lease
from ops_core.routing import DraftKind, Evidence, GraphKey
from ops_core.states import AttemptState, Intent, RunState

from ops_worker.deps import Deps
from ops_worker.evidence import Bundle


class RunGraphState(TypedDict):
    """One run's graph state (every key is replaced whole by the node that returns it)."""

    run_id: str
    run_state: str
    intent: str
    context_resolved: bool
    evidence: str
    draft_id: str | None
    draft_kind: str
    asked: list[str]  # the clarification.requested event ids this thread has been resumed from, oldest first
    decision_present: bool
    attempt_state: str | None


def initial(run_id: UUID) -> RunGraphState:
    """A graph run's input: every key reset, so nothing a stray earlier graph run left on the thread carries over;
    `load_run` replaces the placeholders with the run's own facts."""
    return RunGraphState(
        run_id=str(run_id),
        run_state=RunState.QUEUED.value,
        intent=Intent.INVESTIGATE.value,
        context_resolved=True,
        evidence=Evidence.UNKNOWN.value,
        draft_id=None,
        draft_kind=DraftKind.NONE.value,
        asked=[],
        decision_present=False,
        attempt_state=None,
    )


def key(state: RunGraphState) -> GraphKey:
    """The graph router's key (SA:377) read off the state."""
    attempt = state["attempt_state"]
    return GraphKey(
        RunState(state["run_state"]),
        Intent(state["intent"]),
        state["context_resolved"],
        Evidence(state["evidence"]),
        DraftKind(state["draft_kind"]),
        state["decision_present"],
        None if attempt is None else AttemptState(attempt),
    )


@dataclass
class HeldDraft:
    """A validated draft between `draft_with_langchain` and the node its kind routes to; its id becomes the
    `drafts` row's."""

    draft_id: UUID
    draft: ModelDraft


@dataclass
class Held:
    """The worker's in-memory hold for one graph run (never checkpointed, SA:496)."""

    bundle: Bundle | None = None
    draft: HeldDraft | None = None


@dataclass
class Context:
    """What every node of one graph run receives (LangGraph's runtime context, never persisted): the dependencies,
    the job and the lease it runs under, the hold, and `trace`, the node names in the order they ran (R038's per-run
    node log, which the tests read)."""

    deps: Deps
    job: dict[str, Any]
    lease: Lease
    held: Held = field(default_factory=Held)
    trace: list[str] = field(default_factory=list)

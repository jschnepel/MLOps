"""The graph router's table on its own (T20; SA:377; R129's graph half), without the worker.

Catches: a row that an earlier row shadows (its witness key reaches another row first); a key the worker's nodes
can leave behind that no row routes (the graph run would fail on LookupError); `freeze` without its intent gate; an
answer that does not end on the answer path whatever the intent (DEV-002); and a model's draft kind that could select
anything but abstain, clarify, answer or freeze.
"""

from itertools import product

import pytest
from ops_core.routing import GRAPH_ROUTES, DraftKind, Evidence, GraphKey, GraphRoute, GraphRule, route_graph
from ops_core.states import AttemptState, Intent, RunState


def witnesses(rule: GraphRule) -> list[GraphKey]:
    """One key per run state the row covers, every other dimension at the value the row names or a neutral one."""
    attempt = None if rule.attempt_states is None else min(rule.attempt_states, key=str)
    return [
        GraphKey(
            state,
            rule.intent or Intent.INVESTIGATE,
            True if rule.context_resolved is None else rule.context_resolved,
            rule.evidence or (Evidence.SUFFICIENT if rule.draft_kind else Evidence.UNKNOWN),  # a draft needs it
            rule.draft_kind or DraftKind.NONE,
            bool(rule.decision_present),
            attempt,
        )
        for state in sorted(rule.states)
    ]


WALK = [(rule.name, witness) for rule in GRAPH_ROUTES for witness in witnesses(rule)]


@pytest.mark.parametrize(("name", "witness"), WALK, ids=[f"{n}-{w.state.value}" for n, w in WALK])
def test_each_row_is_the_first_match_for_its_witness(name: str, witness: GraphKey) -> None:
    rule = next(r for r in GRAPH_ROUTES if r.name == name)
    assert next(r for r in GRAPH_ROUTES if r.matches(witness)) is rule  # no earlier row shadows it
    assert route_graph(witness) is rule.route


def test_every_route_is_some_rows_target() -> None:
    assert {rule.route for rule in GRAPH_ROUTES} == set(GraphRoute)


# States that exist only after a reviewer's decision (record_decision is the only way out of AWAITING_APPROVAL).
DECIDED = frozenset(
    {
        RunState.APPROVED,
        RunState.REJECTED,
        RunState.EXECUTING,
        RunState.OUTCOME_UNKNOWN,
        RunState.ESCALATED,
        RunState.SUCCEEDED,
        RunState.ABANDONED_UNVERIFIED,
    }
)


def produced() -> list[GraphKey]:
    """Every key the worker's nodes can leave behind (Plan Q ruling 2): what load_run and the other rereads see in each
    state, and what retrieval and drafting return. The decision and attempt dimensions are always the database's,
    because `route_request` rereads them on every hop (round 1, I1; `test_graph_flow.test_the_router_rereads_...`)."""
    keys: list[GraphKey] = []
    for state, intent in product(RunState, Intent):
        attempts = (
            (AttemptState.INTENT, AttemptState.SENT, AttemptState.ABORT_REQUESTED)
            if state is RunState.EXECUTING
            else (None,)
        )
        for attempt in attempts:
            keys.append(GraphKey(state, intent, True, Evidence.UNKNOWN, DraftKind.NONE, state in DECIDED, attempt))
    for state, intent in product((RunState.RETRIEVING, RunState.DRAFTING), Intent):
        keys.append(GraphKey(state, intent, False, Evidence.UNKNOWN, DraftKind.NONE, False, None))  # asset unknown
        keys.append(GraphKey(state, intent, True, Evidence.INSUFFICIENT, DraftKind.NONE, False, None))
    for intent, kind in product(Intent, DraftKind):
        if (intent, kind) != (Intent.ANSWER_ONLY, DraftKind.PROPOSAL):  # validation refuses that pair (SA:453)
            keys.append(GraphKey(RunState.DRAFTING, intent, True, Evidence.SUFFICIENT, kind, False, None))
    return keys


def test_every_key_the_worker_produces_has_a_route() -> None:
    for produced_key in produced():
        try:
            route_graph(produced_key)  # the only way to fail is the LookupError that would fail the graph run
        except LookupError:
            pytest.fail(f"no graph route for {produced_key}")


def test_freeze_is_gated_by_intent_and_an_answer_is_answered_on_any_run() -> None:
    base = GraphKey(RunState.DRAFTING, Intent.INVESTIGATE, True, Evidence.SUFFICIENT, DraftKind.PROPOSAL, False, None)
    assert route_graph(base) is GraphRoute.FREEZE
    with pytest.raises(LookupError):  # a proposal on an answer_only run is never frozen
        route_graph(GraphKey(**{**base.__dict__, "intent": Intent.ANSWER_ONLY}))
    for intent in Intent:  # DEV-002: an investigate prompt may end ANSWERED (Plan Q ruling 10)
        answer = GraphKey(**{**base.__dict__, "intent": intent, "draft_kind": DraftKind.ANSWER})
        assert route_graph(answer) is GraphRoute.ANSWER_ONLY


def test_a_draft_kind_selects_only_abstain_clarify_answer_or_freeze() -> None:
    # T21: MANUAL is the worker's own verdict when no validated draft came (erratum 134), never a model's kind; it
    # ends the graph run with the run waiting in DRAFTING for a person's proposal.
    routes = {
        route_graph(GraphKey(RunState.DRAFTING, Intent.INVESTIGATE, True, Evidence.SUFFICIENT, kind, False, None))
        for kind in DraftKind
        if kind not in (DraftKind.NONE, DraftKind.MANUAL)
    }
    assert routes == {GraphRoute.ABSTAIN, GraphRoute.CLARIFY, GraphRoute.ANSWER_ONLY, GraphRoute.FREEZE}
    manual = GraphKey(RunState.DRAFTING, Intent.INVESTIGATE, True, Evidence.SUFFICIENT, DraftKind.MANUAL, False, None)
    assert route_graph(manual) is GraphRoute.PUBLISH

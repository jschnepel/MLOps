"""The admission router as a table (AM-16, R129; Plan G rulings 12, 16 and 26): every row is reachable and is the first
to match its sample, the six routes are all reachable, the text-versus-fields parser clarifies instead of guessing
(R018), the slot check precedes every question, and a model hint can only produce a clarification.

Catches: a row shadowed by an earlier one (dead routing), a route no input reaches, a text naming another asset than
the form starting work anyway, a form asset among several the text names starting work, a window number past the
double range raising instead of asking, a "last 200 hours" window accepted, a window in seconds, minutes, weeks,
fortnights, months or years, with a decimal part (or none before the point), a hyphen, a thousands comma or five
digits, that the parser cannot see (so the form wins silently), a bare "M" read as minutes, two windows resolved to
the first, an acronym (UTC) or a lower-case id read as an asset, a busy conversation answered with a question instead
of 409, a status question refused while a run is active (R017 says it must not start work, not that it must be
refused), a hint that starts or rejects work, and a stored-kind vocabulary that drifts from revision 0006's CHECK.
"""

import importlib.util
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest
from ops_core.contracts import SYSTEM_MESSAGE_KINDS, MessageKind, StoredMessageKind
from ops_core.routing import (
    ADMISSION_RULES,
    REPLY_RULES,
    AdmissionFacts,
    AdmissionRoute,
    ClarifyCause,
    RejectCause,
    resolution_for,
    route_admission,
    route_reply,
    said,
)

SAMPLE = "Investigate the alerts on Asset A17 over the last 24 hours."  # BS:287-295


def facts(
    text: str = SAMPLE,
    *,
    kind: MessageKind = MessageKind.INVESTIGATE,
    asset_id: str | None = None,
    hours: int | None = None,
    active_run: bool = False,
    hint: AdmissionRoute | None = None,
) -> AdmissionFacts:
    return AdmissionFacts(kind=kind, text=text, asset_id=asset_id, hours=hours, active_run=active_run, hint=hint)


# One input per row that the row, and no earlier row, decides.
ROW_SAMPLES = {
    "status": facts("Where is my run?", kind=MessageKind.STATUS, active_run=True),
    "clarification_kind": facts("A17, 24 hours", kind=MessageKind.CLARIFICATION),
    "slot_occupied": facts(active_run=True),
    "text_and_fields": facts("Investigate something."),
    "hint": facts(asset_id="A17", hours=24, hint=AdmissionRoute.CLARIFY),
    "investigate": facts(asset_id="A17", hours=24),
    "ask": facts("What did A17 log in the last 24 hours?", kind=MessageKind.ASK),
    "bound_reply": facts("Clarification: asset A17, hours 24", kind=MessageKind.CLARIFICATION, asset_id="A17"),
}


def first_rule(sample: AdmissionFacts, rules: Any) -> str:
    """The name of the first row whose predicate holds, computed the way route_admission computes it."""
    resolution = resolution_for(sample)
    return str(next(rule.name for rule in rules if rule.predicate(sample, resolution)))


def test_every_row_is_reachable_first_and_the_six_routes_are_all_reachable() -> None:
    reached = set()
    for rules, router in ((ADMISSION_RULES, route_admission), (REPLY_RULES, route_reply)):
        for rule in rules:
            sample = ROW_SAMPLES[rule.name]
            assert first_rule(sample, rules) == rule.name, rule.name
            decision = router(sample)
            assert decision.route is rule.route, rule.name
            if rule.cause is not None:  # a fixed-cause row (reject, hint) reports exactly that cause
                assert decision.cause == rule.cause, rule.name
            reached.add(decision.route)
    assert reached == set(AdmissionRoute)
    assert len(ROW_SAMPLES) == len(ADMISSION_RULES) + len(REPLY_RULES)


@pytest.mark.parametrize(
    ("text", "asset_id", "hours", "kind", "expected"),
    [
        (SAMPLE, "A17", 24, MessageKind.INVESTIGATE, ("investigate", None, "A17", 24)),
        (SAMPLE, None, None, MessageKind.INVESTIGATE, ("investigate", None, "A17", 24)),
        ("Investigate A17 over the last day.", None, None, MessageKind.INVESTIGATE, ("investigate", None, "A17", 24)),
        (
            "Investigate A17 over the past 3 days.",
            None,
            None,
            MessageKind.INVESTIGATE,
            ("investigate", None, "A17", 72),
        ),
        ("Look at PUMP-2 for the last hour.", None, None, MessageKind.INVESTIGATE, ("investigate", None, "PUMP-2", 1)),
        ("Check A17, past 6h.", None, None, MessageKind.INVESTIGATE, ("investigate", None, "A17", 6)),
        ("Check A17 over the last week.", None, None, MessageKind.INVESTIGATE, ("investigate", None, "A17", 168)),
        ("Investigate A17.", "A17", 12, MessageKind.INVESTIGATE, ("investigate", None, "A17", 12)),
        # Two ids ask even when one is the form's (ruling 12 as amended after the final review, I2).
        (
            "Compare B22 with A17, last 24 hours.",
            "A17",
            24,
            MessageKind.INVESTIGATE,
            ("clarify", "asset_ambiguous", None, None),
        ),
        (
            "B22 is failing, A17 is fine; last 24 hours",
            "A17",
            24,
            MessageKind.INVESTIGATE,
            ("clarify", "asset_ambiguous", None, None),
        ),
        ("Investigate A17, last 24 hours.", "A17", 24, MessageKind.INVESTIGATE, ("investigate", None, "A17", 24)),
        ("What did A17 log in the last 24 hours?", None, None, MessageKind.ASK, ("readonly_answer", None, "A17", 24)),
        (
            "Investigate A17 over the last 200 hours.",
            None,
            None,
            MessageKind.INVESTIGATE,
            ("clarify", "interval_out_of_range", None, None),
        ),
        (
            "Investigate A17 over the last 0 hours.",
            None,
            None,
            MessageKind.INVESTIGATE,
            ("clarify", "interval_out_of_range", None, None),
        ),
        (
            "Compare A17 and B22 over the last 24 hours.",
            None,
            None,
            MessageKind.INVESTIGATE,
            ("clarify", "asset_ambiguous", None, None),
        ),
        (
            "Check the UTC alerts over the last 24 hours.",
            None,
            None,
            MessageKind.INVESTIGATE,
            ("clarify", "missing_asset", None, None),
        ),
        (
            "Check a17 over the last 24 hours.",
            None,
            None,
            MessageKind.INVESTIGATE,
            ("clarify", "missing_asset", None, None),
        ),
        (
            "Investigate B22 over the last 24 hours.",
            "A17",
            24,
            MessageKind.INVESTIGATE,
            ("clarify", "asset_conflict", None, None),
        ),
        (
            "Investigate A17 over the last 2 days.",
            "A17",
            24,
            MessageKind.INVESTIGATE,
            ("clarify", "interval_conflict", None, None),
        ),
        (
            "Investigate A17 over the last 2 weeks.",
            "A17",
            24,
            MessageKind.INVESTIGATE,
            ("clarify", "interval_conflict", None, None),
        ),
        (
            "Investigate A17 over the last 30 minutes.",
            "A17",
            24,
            MessageKind.INVESTIGATE,
            ("clarify", "interval_conflict", None, None),
        ),
        (
            "Investigate A17 over the last 1000 hours.",
            None,
            None,
            MessageKind.INVESTIGATE,
            ("clarify", "interval_out_of_range", None, None),
        ),
        (
            "Investigate A17 for the last 24 hours, not the past 6h.",
            "A17",
            24,
            MessageKind.INVESTIGATE,
            ("clarify", "interval_ambiguous", None, None),
        ),
        (
            "Compare the last 24 hours of A17 with the past 3 days.",
            None,
            None,
            MessageKind.INVESTIGATE,
            ("clarify", "interval_ambiguous", None, None),
        ),
        ("Investigate A17.", None, None, MessageKind.INVESTIGATE, ("clarify", "missing_interval", None, None)),
        ("What happened recently?", None, None, MessageKind.ASK, ("clarify", "missing_asset", None, None)),
        # One row per unit family ruling 12 added, and one each for a decimal, a hyphen and a bare "M".
        (
            "Investigate A17 over the last 90 seconds.",
            "A17",
            24,
            MessageKind.INVESTIGATE,
            ("clarify", "interval_conflict", None, None),
        ),
        (
            "Check A17 over the last fortnight.",
            None,
            None,
            MessageKind.INVESTIGATE,
            ("clarify", "interval_out_of_range", None, None),
        ),
        (
            "Investigate A17 over the last 6 months.",
            "A17",
            24,
            MessageKind.INVESTIGATE,
            ("clarify", "interval_conflict", None, None),
        ),
        (
            "Investigate A17 over the past 2 yrs.",
            None,
            None,
            MessageKind.INVESTIGATE,
            ("clarify", "interval_out_of_range", None, None),
        ),
        (
            "Investigate A17 over the last 1.5 days.",
            None,
            None,
            MessageKind.INVESTIGATE,
            ("investigate", None, "A17", 36),
        ),
        (
            "Investigate A17 over the last 48-hours.",
            "A17",
            24,
            MessageKind.INVESTIGATE,
            ("clarify", "interval_conflict", None, None),
        ),
        (
            "Investigate A17 over the last 12345 hours.",
            "A17",
            24,
            MessageKind.INVESTIGATE,
            ("clarify", "interval_conflict", None, None),
        ),
        (
            "Investigate A17 over the last 12345 hours.",
            None,
            None,
            MessageKind.INVESTIGATE,
            ("clarify", "interval_out_of_range", None, None),
        ),
        (
            "Investigate A17 over the last 1,000 hours.",
            "A17",
            24,
            MessageKind.INVESTIGATE,
            ("clarify", "interval_conflict", None, None),
        ),
        (
            "Investigate A17 over the last .5 days.",
            "A17",
            24,
            MessageKind.INVESTIGATE,
            ("clarify", "interval_conflict", None, None),
        ),
        ("Investigate A17 over the last 3 M.", "A17", 24, MessageKind.INVESTIGATE, ("investigate", None, "A17", 24)),
        # A number past 12 integer digits is too large to read, with or without a form window (I1).
        (
            "Investigate A17 last 1" + "0" * 400 + ".5 seconds",
            None,
            None,
            MessageKind.INVESTIGATE,
            ("clarify", "interval_out_of_range", None, None),
        ),
        (
            "Investigate A17 last 1" + "0" * 400 + ".5 seconds",
            "A17",
            24,
            MessageKind.INVESTIGATE,
            ("clarify", "interval_out_of_range", None, None),
        ),
        (
            "Investigate A17 over the last 1234567890123 hours.",
            "A17",
            24,
            MessageKind.INVESTIGATE,
            ("clarify", "interval_out_of_range", None, None),
        ),
        (
            "Investigate A17 over the last 1,234,567,890,123 hours.",
            None,
            None,
            MessageKind.INVESTIGATE,
            ("clarify", "interval_out_of_range", None, None),
        ),
    ],
)
def test_text_and_fields(
    text: str, asset_id: str | None, hours: int | None, kind: MessageKind, expected: tuple[str, Any, Any, Any]
) -> None:
    decision = route_admission(facts(text, kind=kind, asset_id=asset_id, hours=hours))
    assert (decision.route.value, decision.cause, decision.asset_id, decision.hours) == expected
    assert (decision.question is not None) == (decision.route is AdmissionRoute.CLARIFY)


def test_questions_name_what_disagreed() -> None:
    asked = {
        ClarifyCause.ASSET_CONFLICT: facts("Investigate B22 now.", asset_id="A17", hours=24),
        ClarifyCause.ASSET_AMBIGUOUS: facts("Compare A17 and B22 over the last 24 hours."),
        ClarifyCause.INTERVAL_AMBIGUOUS: facts("Compare the last 24 hours of A17 with the past 3 days."),
        ClarifyCause.INTERVAL_OUT_OF_RANGE: facts("Investigate A17 over the past 10 days."),
        ClarifyCause.INTERVAL_CONFLICT: facts("Investigate A17 over the last 30 minutes.", asset_id="A17", hours=24),
    }
    expected = {
        ClarifyCause.ASSET_CONFLICT: "The form names asset A17 but the text names B22; which one is meant?",
        ClarifyCause.ASSET_AMBIGUOUS: "The request names more than one asset (A17, B22); name the one to investigate.",
        ClarifyCause.INTERVAL_AMBIGUOUS: (
            "The request names more than one window (24 hours, 72 hours); which one is meant?"
        ),
        ClarifyCause.INTERVAL_OUT_OF_RANGE: "The window must be between 1 and 168 hours; 240 hours was given.",
        ClarifyCause.INTERVAL_CONFLICT: "The form says 24 hours but the text says 30 minutes; which is meant?",
    }
    for cause, sample in asked.items():
        decision = route_admission(sample)
        assert (decision.cause, decision.question) == (cause, expected[cause])


def test_windows_are_said_in_the_singular_and_plain_decimals() -> None:
    assert said(Fraction(3600)) == "1 hour"
    assert said(Fraction(7200)) == "2 hours"
    assert said(Fraction(60)) == "1 minute"
    assert said(Fraction(1)) == "1 second"
    assert said(Fraction(90)) == "90 seconds"
    assert said(Fraction(1, 2)) == "0.5 seconds"
    assert said(Fraction(10, 3)) == "3.33 seconds"
    assert "e+" not in said(Fraction(10**30, 7))
    assert said(Fraction(1, 200)) == "0.01 seconds"  # half up, by integer arithmetic


def test_a_huge_window_is_said_briefly_and_never_raises() -> None:
    # I1: a Fraction past the double range made float() raise OverflowError, a 503 for the requester's own typo.
    for seconds in (Fraction(2 * 10**400 + 1, 2), Fraction(10**4000 * 3600), Fraction(10**400, 7)):
        rendered = said(seconds)
        assert rendered == "more than 1,000,000,000,000 hours"
        assert len(rendered) < 40


def test_a_too_large_window_asks_without_echoing_the_number() -> None:
    text = "Investigate A17 last 1" + "0" * 400 + ".5 seconds"
    for sample in (facts(text), facts(text, asset_id="A17", hours=24)):
        decision = route_admission(sample)
        assert decision.question == (
            "The window in the text is too large to be a number of hours; give between 1 and 168 hours."
        )
    # A decimal part past Python's 4,300-digit int parse limit is still read exactly, not raised on.
    decision = route_admission(facts("Investigate A17 last 1." + "3" * 9000 + " seconds", asset_id="A17", hours=24))
    assert (decision.cause, decision.question) == (
        ClarifyCause.INTERVAL_CONFLICT,
        "The form says 24 hours but the text says 1.33 seconds; which is meant?",
    )


def test_a_busy_conversation_is_rejected_before_any_question() -> None:
    decision = route_admission(facts("Investigate something.", active_run=True))  # would clarify if idle
    assert (decision.route, decision.cause, decision.question) == (
        AdmissionRoute.REJECT,
        RejectCause.SLOT_OCCUPIED,
        None,
    )


def test_a_status_question_skips_the_parser_and_is_answered_while_busy() -> None:
    decision = route_admission(facts("B22 or A17? last 900 hours", kind=MessageKind.STATUS, active_run=True))
    assert (decision.route, decision.cause) == (AdmissionRoute.STATUS_QUESTION, None)


def test_a_clarification_sent_as_a_message_is_rejected_toward_its_own_route() -> None:
    decision = route_admission(facts(kind=MessageKind.CLARIFICATION, asset_id="A17", hours=24))
    assert (decision.route, decision.cause) == (AdmissionRoute.REJECT, RejectCause.USE_CLARIFICATIONS_ROUTE)


def test_a_hint_can_only_turn_a_run_into_a_clarification() -> None:
    for hint in AdmissionRoute:
        for kind, run_route in (
            (MessageKind.INVESTIGATE, AdmissionRoute.INVESTIGATE),
            (MessageKind.ASK, AdmissionRoute.READONLY_ANSWER),
        ):
            decision = route_admission(facts(kind=kind, asset_id="A17", hours=24, hint=hint))
            if hint is AdmissionRoute.CLARIFY:
                assert (decision.route, decision.cause) == (AdmissionRoute.CLARIFY, ClarifyCause.HINT)
                assert decision.question == "Please confirm the asset and the window for this request."
            else:
                assert decision.route is run_route, hint  # any other hint value is ignored
        busy = route_admission(facts(asset_id="A17", hours=24, active_run=True, hint=hint))
        status = route_admission(facts(kind=MessageKind.STATUS, hint=hint))
        assert busy.route is AdmissionRoute.REJECT and status.route is AdmissionRoute.STATUS_QUESTION, hint


def test_the_reply_table_routes_only_a_bound_reply() -> None:
    assert route_reply(facts(kind=MessageKind.CLARIFICATION, hours=24)).route is AdmissionRoute.CLARIFICATION_REPLY
    with pytest.raises(LookupError):
        route_reply(facts(kind=MessageKind.INVESTIGATE))


def test_the_stored_vocabulary_is_revision_0006s_and_the_request_kinds_are_unchanged() -> None:
    path = Path(__file__).resolve().parents[2] / "migrations" / "app" / "versions" / "0006_admission_idempotency.py"
    spec = importlib.util.spec_from_file_location("rev0006_kinds", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert set(module.STORED_KINDS_0006) == {k.value for k in StoredMessageKind}
    assert set(module.SYSTEM_KINDS_0006) == {k.value for k in SYSTEM_MESSAGE_KINDS}
    assert {k.value for k in MessageKind} == {"investigate", "ask", "status", "clarification"}  # the schema's enum

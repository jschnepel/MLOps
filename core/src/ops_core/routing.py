"""The three routers' enumerable routes (AM-16, ADR-0003), the admission router's table, and the per-run manifest.

Routing is deterministic-first: model output may hint, never select (SA:362, SA:375). The admission table (T12) is
`ADMISSION_RULES`, evaluated first match wins over facts the API gathered inside its admission unit; it is pure, so
a test walks every row (R129). The graph table arrives with T20 and the model table with T19; this module fixes the
vocabularies so every table, schema and event spells them the same way.

Text versus fields (BS:297, Plan G ruling 12): structured fields win only when the text agrees with them, so a
small deterministic parser reads asset ids and "last N seconds/minutes/hours/days/weeks/fortnights/months/years"
windows from the text; a disagreement, a missing field the text cannot fill, or an ambiguous text becomes a stored
clarification, never a guess (R018).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from fractions import Fraction
from typing import Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ops_core.contracts import MessageKind


class AdmissionRoute(StrEnum):
    """Where the admission router sends a message (AM-16; table owned by T12)."""

    INVESTIGATE = "investigate"
    CLARIFICATION_REPLY = "clarification_reply"
    STATUS_QUESTION = "status_question"
    READONLY_ANSWER = "readonly_answer"
    CLARIFY = "clarify"
    REJECT = "reject"


class GraphRoute(StrEnum):
    """The worker graph's next node (AM-16; table owned by T20)."""

    CLARIFY = "clarify"
    RETRIEVE = "retrieve"
    DRAFT = "draft"
    ANSWER_ONLY = "answer_only"
    ABSTAIN = "abstain"
    FREEZE = "freeze"
    AWAIT_DECISION = "await_decision"
    EXECUTE = "execute"
    RECOVER = "recover"
    PUBLISH = "publish"


class ModelRoute(StrEnum):
    """Which drafting model runs (AM-16, AM-31; table owned by T19)."""

    FAKE = "fake"
    QWEN3_8B = "qwen3:8b"


class ClarifyCause(StrEnum):
    """Why admission asked instead of starting work (Plan G ruling 12); each has one question template."""

    MISSING_ASSET = "missing_asset"
    ASSET_AMBIGUOUS = "asset_ambiguous"
    ASSET_CONFLICT = "asset_conflict"
    MISSING_INTERVAL = "missing_interval"
    INTERVAL_AMBIGUOUS = "interval_ambiguous"
    INTERVAL_OUT_OF_RANGE = "interval_out_of_range"
    INTERVAL_CONFLICT = "interval_conflict"
    HINT = "hint"


class RejectCause(StrEnum):
    """Why admission refused (AM-16 `reject`): the API turns each into its own status and code."""

    USE_CLARIFICATIONS_ROUTE = "use_clarifications_route"  # 422 INVALID_INPUT
    SLOT_OCCUPIED = "slot_occupied"  # 409 SLOT_OCCUPIED


HOURS_MIN: Final = 1  # BS:547: 1-168 hours
HOURS_MAX: Final = 168
# An upper-case token that contains a digit (A17, PUMP-2): prose words and acronyms such as UTC never match, and a
# lower-case "a17" is not an asset id (contracts.AssetId requires the upper case too). Both quantifiers around the
# digit are capped at the AssetId bound so the scan stays linear on a long run of capitals; the exact 32-character
# limit (the two caps together can reach 64) is still enforced by ASSET_ID in text_assets.
TEXT_ASSET: Final = re.compile(r"\b([A-Z][A-Z0-9_-]{0,31}[0-9][A-Z0-9_-]{0,31})\b")
ASSET_ID: Final = re.compile(r"^[A-Z][A-Z0-9_-]{0,31}$")  # the same bound as contracts.AssetId
# Every unit a person writes is read, seconds to years (ruling 12): a window the parser could not see would let the
# form win silently. The number is any length, may carry thousands commas ("1,000") and a decimal part (".5" too),
# and may be joined to its unit by spaces or a hyphen; it is ASCII digits only (a \d would also read other scripts'
# digits). The only one-letter units are h and d, so a bare "m" (minutes or months?) or "w" is no window at all.
TEXT_WINDOW: Final = re.compile(
    r"\b(?:last|past)\s+([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?|\.[0-9]+)[\s-]*"
    r"(seconds?|secs?|minutes?|mins?|hours?|hrs?|h|days?|d|weeks?|wks?|fortnights?|months?|mos?|years?|yrs?)\b",
    re.IGNORECASE,
)
# "last minute" and "last second" are idioms ("at the last minute"), so the number-less form reads only periods.
TEXT_WINDOW_WORD: Final = re.compile(r"\b(?:last|past)\s+(hour|day|week|fortnight|month|year)\b", re.IGNORECASE)
# One row per unit family, keyed by the full word in the singular: a window's length in seconds. A month is 30 days
# and a year 365, so both convert to whole hours and meet the 1-168 rule like any other window.
UNIT_SECONDS: Final[dict[str, int]] = {
    "second": 1,
    "sec": 1,
    "minute": 60,
    "min": 60,
    "hour": 3600,
    "hr": 3600,
    "h": 3600,
    "day": 86400,
    "d": 86400,
    "week": 604800,
    "wk": 604800,
    "fortnight": 1209600,
    "month": 2592000,
    "mo": 2592000,
    "year": 31536000,
    "yr": 31536000,
}
# A window whose integer part has more digits than this is read as too large rather than as a number: no 1-168
# hour window needs it, and keeping the parsed value small keeps every rendered question short (execution ruling
# (c) as amended after the final review, I1).
WINDOW_DIGITS_MAX: Final = 12
# The question for such a window repeats nothing of it: the number may be hundreds of digits long.
TOO_LARGE_QUESTION: Final = "The window in the text is too large to be a number of hours; give between 1 and 168 hours."
# said() renders a window at or above this many seconds as a bound, never as its digits.
SAID_MAX_SECONDS: Final = 10**12 * 3600
QUESTIONS: Final[dict[ClarifyCause, str]] = {
    ClarifyCause.MISSING_ASSET: "Which asset should be investigated? Name one asset id (for example A17).",
    ClarifyCause.ASSET_AMBIGUOUS: "The request names more than one asset ({ids}); name the one to investigate.",
    ClarifyCause.ASSET_CONFLICT: "The form names asset {field} but the text names {given}; which one is meant?",
    ClarifyCause.MISSING_INTERVAL: (
        'Over which window? Give a number of hours between 1 and 168 (for example "last 24 hours").'
    ),
    ClarifyCause.INTERVAL_AMBIGUOUS: "The request names more than one window ({windows}); which one is meant?",
    ClarifyCause.INTERVAL_OUT_OF_RANGE: "The window must be between 1 and 168 hours; {given} was given.",
    ClarifyCause.INTERVAL_CONFLICT: "The form says {field} hours but the text says {given}; which is meant?",
    ClarifyCause.HINT: "Please confirm the asset and the window for this request.",
}


def text_assets(text: str) -> tuple[str, ...]:
    """The asset ids a text names, first mention first, each once; tokens longer than an AssetId are not ids."""
    return tuple(dict.fromkeys(m for m in TEXT_ASSET.findall(text) if ASSET_ID.fullmatch(m)))


def unit_seconds(unit: str) -> int:
    """A unit's length in seconds, whatever its case or plural ("Hrs", "months", "d")."""
    return UNIT_SECONDS[unit.lower().removesuffix("s")]


def _digits(digits: str) -> int:
    """An ASCII digit string as an int, read in slices: a decimal part longer than Python's 4,300-digit parse limit
    is still read exactly instead of raising. Only a caller that skips the 4,000-character text contract can reach
    that, but the router must never raise on text."""
    value = 0
    for start in range(0, len(digits), 1000):
        piece = digits[start : start + 1000]
        value = value * 10 ** len(piece) + int(piece)
    return value


def _window(number: str, unit: str) -> Fraction | None:
    """One "last N unit" match in seconds, exact; None when the integer part is too long to be a window at all."""
    whole, _, decimals = number.replace(",", "").partition(".")
    whole = whole.lstrip("0")
    if len(whole) > WINDOW_DIGITS_MAX:
        return None
    value = Fraction(int(whole or "0"))
    if decimals:
        value += Fraction(_digits(decimals), 10 ** len(decimals))
    return value * unit_seconds(unit)


def text_windows(text: str) -> tuple[Fraction | None, ...]:
    """The distinct look-back windows the text names, in seconds, first mention first ("last 24 hours", "past 3
    days", "last 1.5 days", "last 48-hours", "last week"); two spellings of one length ("last 24 hours", "past day")
    are one. A Fraction keeps a decimal exact, so "last 0.5 days" is 12 hours and never 11.999. None stands for a
    window whose number is too large to read (WINDOW_DIGITS_MAX)."""
    found: list[tuple[int, Fraction | None]] = []
    for match in TEXT_WINDOW.finditer(text):
        found.append((match.start(), _window(match.group(1), match.group(2))))
    for match in TEXT_WINDOW_WORD.finditer(text):
        found.append((match.start(), Fraction(unit_seconds(match.group(1)))))
    return tuple(dict.fromkeys(seconds for _, seconds in sorted(found, key=lambda pair: pair[0])))


def said(seconds: Fraction) -> str:
    """A window as a question repeats it: in hours when it is whole hours ("48 hours"), else in minutes when it is
    whole minutes ("30 minutes"), else in seconds ("90 seconds", "0.5 seconds"); a count of one is singular, and a
    fractional count shows at most two decimals. Integer arithmetic only: a float raises past about 1e308 and
    prints scientific notation long before that. A window past SAID_MAX_SECONDS is said as a bound, not its digits."""
    if seconds >= SAID_MAX_SECONDS:
        return f"more than {SAID_MAX_SECONDS // 3600:,} hours"
    for size, unit in ((3600, "hour"), (60, "minute")):
        if seconds % size == 0:
            count = seconds // size
            return f"{count} {unit}{'' if count == 1 else 's'}"
    if seconds == 1:
        return "1 second"
    hundredths = (seconds * 200 + 1) // 2  # rounded half up to two decimals, still exact
    whole, part = divmod(hundredths, 100)
    return f"{whole}.{part:02d}".rstrip("0").rstrip(".") + " seconds"


@dataclass(frozen=True)
class AdmissionFacts:
    """What the router sees: the request's kind, text and fields, whether the conversation holds a run, and an
    optional model hint (no producer exists yet; TODO(T19))."""

    kind: MessageKind
    text: str
    asset_id: str | None
    hours: int | None
    active_run: bool
    hint: AdmissionRoute | None = None


@dataclass(frozen=True)
class Resolution:
    """The text-versus-fields verdict: the agreed asset and window, or the first cause that needs a question."""

    asset_id: str | None
    hours: int | None
    cause: ClarifyCause | None = None
    question: str | None = None


def _ask(cause: ClarifyCause, **values: object) -> Resolution:
    return Resolution(None, None, cause, QUESTIONS[cause].format(**values))


def resolve(facts: AdmissionFacts) -> Resolution:
    """Ruling 12's table, asset rules before interval rules; the first disagreement names the one cause asked."""
    ids = text_assets(facts.text)
    asset = facts.asset_id
    if len(ids) > 1:
        # Two ids ask even beside a form asset that equals one of them, as two windows do below: which asset the text
        # meant is the doubt, and a form left on the last asset is the stale input BS:297 will not trust.
        return _ask(ClarifyCause.ASSET_AMBIGUOUS, ids=", ".join(ids))
    if asset is not None:
        if ids and ids[0] != asset:
            return _ask(ClarifyCause.ASSET_CONFLICT, field=asset, given=ids[0])
    elif ids:
        asset = ids[0]
    else:
        return _ask(ClarifyCause.MISSING_ASSET)
    read = text_windows(facts.text)
    if None in read:  # with or without a form window: a number that long is no window anyone meant
        return Resolution(None, None, ClarifyCause.INTERVAL_OUT_OF_RANGE, TOO_LARGE_QUESTION)
    windows = tuple(window for window in read if window is not None)
    if len(windows) > 1:
        # Two windows ask even beside a form window that equals one of them: which one the text meant is the doubt.
        return _ask(ClarifyCause.INTERVAL_AMBIGUOUS, windows=", ".join(said(w) for w in windows))
    window = windows[0] if windows else None
    hours = facts.hours
    if hours is not None:
        if window is not None and window != hours * 3600:  # outside 1-168 can never equal a valid form window
            return _ask(ClarifyCause.INTERVAL_CONFLICT, field=hours, given=said(window))
    elif window is None:
        return _ask(ClarifyCause.MISSING_INTERVAL)
    elif window % 3600 != 0 or not HOURS_MIN <= window // 3600 <= HOURS_MAX:
        return _ask(ClarifyCause.INTERVAL_OUT_OF_RANGE, given=said(window))
    else:
        hours = window // 3600
    return Resolution(asset, hours)


@dataclass(frozen=True)
class AdmissionDecision:
    """The route, its cause for a clarify or a reject, the resolved asset and window for a run, the question asked."""

    route: AdmissionRoute
    cause: ClarifyCause | RejectCause | None = None
    asset_id: str | None = None
    hours: int | None = None
    question: str | None = None


@dataclass(frozen=True)
class AdmissionRule:
    """One row: the first rule whose predicate holds decides the route (`cause` fixed for reject and hint rows)."""

    name: str
    predicate: Callable[[AdmissionFacts, Resolution], bool]
    route: AdmissionRoute
    cause: ClarifyCause | RejectCause | None = None


_RUNS: Final = frozenset({MessageKind.INVESTIGATE, MessageKind.ASK})

# AM-16's table in evaluation order (Plan G ruling 16). The slot check precedes the clarify rows, so a busy
# conversation gets 409 before any question (1.3.6, T12 review note 2); the hint row can only turn a run into a
# clarification, never the reverse (SA:375); after the first three rows only investigate and ask remain, and the last
# two rows cover both.
ADMISSION_RULES: Final[tuple[AdmissionRule, ...]] = (
    AdmissionRule("status", lambda f, _: f.kind is MessageKind.STATUS, AdmissionRoute.STATUS_QUESTION),
    AdmissionRule(
        "clarification_kind",
        lambda f, _: f.kind is MessageKind.CLARIFICATION,
        AdmissionRoute.REJECT,
        RejectCause.USE_CLARIFICATIONS_ROUTE,
    ),
    AdmissionRule("slot_occupied", lambda f, _: f.active_run, AdmissionRoute.REJECT, RejectCause.SLOT_OCCUPIED),
    AdmissionRule("text_and_fields", lambda _, r: r.cause is not None, AdmissionRoute.CLARIFY),
    AdmissionRule("hint", lambda f, _: f.hint is AdmissionRoute.CLARIFY, AdmissionRoute.CLARIFY, ClarifyCause.HINT),
    AdmissionRule("investigate", lambda f, _: f.kind is MessageKind.INVESTIGATE, AdmissionRoute.INVESTIGATE),
    AdmissionRule("ask", lambda f, _: f.kind is MessageKind.ASK, AdmissionRoute.READONLY_ANSWER),
)
# BS:273's route is the clarification_reply entry (ruling 15): a reply bound to a question by id and version never
# passes through the message table, so it has a table of one row of its own and R129's walk covers both tables.
REPLY_RULES: Final[tuple[AdmissionRule, ...]] = (
    AdmissionRule("bound_reply", lambda f, _: f.kind is MessageKind.CLARIFICATION, AdmissionRoute.CLARIFICATION_REPLY),
)


def _first(rules: tuple[AdmissionRule, ...], facts: AdmissionFacts, resolution: Resolution) -> AdmissionDecision:
    for rule in rules:
        if not rule.predicate(facts, resolution):
            continue
        if rule.route is AdmissionRoute.CLARIFY:
            if rule.cause is None:  # the text-and-fields row carries the parser's own cause and question
                return AdmissionDecision(rule.route, resolution.cause, question=resolution.question)
            assert isinstance(rule.cause, ClarifyCause)  # a fixed clarify row names a clarify cause, never a reject one
            return AdmissionDecision(rule.route, rule.cause, question=QUESTIONS[rule.cause])
        if rule.route in (AdmissionRoute.INVESTIGATE, AdmissionRoute.READONLY_ANSWER):
            return AdmissionDecision(rule.route, asset_id=resolution.asset_id, hours=resolution.hours)
        return AdmissionDecision(rule.route, rule.cause)
    raise LookupError(f"no admission rule matched kind {facts.kind.value}")  # the tables are total; a test walks them


def resolution_for(facts: AdmissionFacts) -> Resolution:
    """The parser runs only for kinds that would start a run; status and clarification skip it (R017)."""
    if facts.kind in _RUNS:
        return resolve(facts)
    return Resolution(facts.asset_id, facts.hours)


def route_admission(facts: AdmissionFacts) -> AdmissionDecision:
    """The messages route's decision (AM-16). The parser runs only for kinds that would start a run."""
    return _first(ADMISSION_RULES, facts, resolution_for(facts))


def route_reply(facts: AdmissionFacts) -> AdmissionDecision:
    """The clarifications route's decision: a bound reply is the clarification_reply route."""
    return _first(REPLY_RULES, facts, resolution_for(facts))


class RunManifest(BaseModel):
    """What produced a run's draft: route, model digest, prompt and corpus versions (AM-80; written by T19)."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    run_id: UUID
    model_route: ModelRoute
    model_digest: str | None = Field(pattern=r"^[0-9a-f]{64}$")  # bare hex, as data/model-pins.json
    prompt_version: str = Field(min_length=1, max_length=60)
    corpus_version: str = Field(min_length=1, max_length=100)
    # Plan ruling 3: the externally visible mode keeps the delivered `vector_exact`, which says what the search
    # guarantees (exact, not approximate, vector search); AM-20.3's `mode=vector` is the SQL function's argument value.
    # TODO(T15): mcp-read, the caller of `search_procedures_scoped`, translates `vector_exact` to `mode=vector`.
    retrieval_mode: Literal["lexical", "vector_exact"]

    @model_validator(mode="after")
    def _real_models_carry_a_digest(self) -> RunManifest:
        # The fake route has nothing to pin; every real model route records the digest the worker verified (AM-31).
        if self.model_route is not ModelRoute.FAKE and self.model_digest is None:
            raise ValueError("model_digest is required for a real model route")
        return self

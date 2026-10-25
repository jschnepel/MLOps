"""The evidence bundle the graph's retrieval node gathers (BS:419) and the code rule that judges it (SA:377).

The bundle holds what the model will read: the confirmed request (the run's message and any clarification replies),
the retrieved procedure sections and the asset status and alert records as `Observation`s, and the run's manifest. It
lives in the worker's memory for one graph run and never in graph state, a checkpoint or an event (SA:496, SA:563,
R091); a graph run that resumes without it retrieves again, which also re-checks access before anything reaches a
model (BS:423).

"Evidence sufficient?" is SA:377's rule and nothing more (Plan Q ruling 3, erratum 122): at least one permitted status
observation (`normal` or `warning`; `unavailable` observes nothing) and at least one effective procedure section,
all within `FRESHNESS` of the instant mcp-read answered at. The search's own minimum rank (0.25, T17) is v1's
relevance criterion; erratum 102's residue stays measured, not closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final

from ops_core.routing import RunManifest

from ops_worker.drafting import EvidenceItem, Observation

# SA:462's asset freshness, the bound the grant applies at execution; the same window keeps a draft from resting on
# a status the grant would refuse. Every instant compared is the database's (`app.current_time()` via mcp-read).
FRESHNESS: Final = timedelta(minutes=5)
# BS:551 allows 8 references in the bundle: up to 3 procedure sections, the status and at most 4 alerts, and a count
# of the alerts left out (BS:419's "truncation notice").
ALERTS_SHOWN: Final = 4
OBSERVED: Final = frozenset({"normal", "warning"})


@dataclass(frozen=True)
class Bundle:
    """What one graph run retrieved for its draft; held in memory only (see the module docstring)."""

    text: str
    procedures: list[EvidenceItem]
    observations: tuple[Observation, ...]
    manifest: RunManifest


def _instant(value: str) -> datetime:
    return datetime.fromisoformat(value)  # Python 3.11+ reads the trailing Z


def observations(status: dict[str, Any], alerts: dict[str, Any]) -> tuple[Observation, ...]:
    """The status and alert records as the model reads them, newest alerts first, with a count of those left out."""
    data = status["data"]
    shown = [
        Observation("asset status", str(data["revision"]), f"{data['state']} at {data['observed_at']}"),
    ]
    # By instant, not by text: `...:00.5Z`, `...:00Z` and `+00:00` spellings of instants do not sort as they occurred.
    rows = sorted(alerts["data"]["alerts"], key=lambda alert: _instant(alert["occurred_at"]), reverse=True)
    shown.extend(
        Observation("alert", str(a["revision"]), f"{a['occurred_at']} {a['code']}: {a['message']}")
        for a in rows[:ALERTS_SHOWN]
    )
    left, more = max(0, len(rows) - ALERTS_SHOWN), alerts["data"]["next_cursor"] is not None
    if left or more:
        if left:
            notice = f"{left} more alert records were not shown" + ("; further pages were not read" if more else "")
        else:  # every record in hand is shown, but the page says more exist
            notice = "further alert records exist and were not read"
        shown.append(Observation("alerts not shown", "0", notice))
    return tuple(shown)


def sufficient(status: dict[str, Any], search: dict[str, Any]) -> bool:
    """SA:377's code rule over the two `ok` tool results (never a model judgement)."""
    data = status["data"]
    if data["state"] not in OBSERVED:
        return False
    answered = _instant(status["observed_at"])
    # Live, this status check cannot fire: mcp-read refuses a status whose observed_at differs from the scope's as_of
    # and stamps the envelope with the same instant. The bound that binds is the search's retrieved_at against it.
    if abs(answered - _instant(data["observed_at"])) > FRESHNESS:
        return False
    rows = search["data"]["results"]
    return bool(rows) and all(abs(_instant(row["retrieved_at"]) - answered) <= FRESHNESS for row in rows)

"""The only path from the application to the destination (ADR-0001: mcp-write → incident-sim).

Three calls, each with mcp-write's own workload token: the POST carries the exact canonical bytes the reviewer
approved, wrapped with the action id and hash (AM-13 §4); the restricted lookup reads the key that stands (SA:269); the
abort asks the destination to make the key a permanent tombstone, carrying the grant's hash (SA:266). What comes back
is classified into the AM-13 tool outcome vocabulary without optimism: a transport failure, a 404 (SA:269: NOT_FOUND is
never a no-commit), a 429 or a 503 is UNKNOWN, never "no effect" (BUILD_SPEC §1, §11); a committed receipt counts only
if its action id and hash are ours (SA:358); a tombstone becomes FAILED_NO_COMMIT with the reason
`outcome_from_destination` derives.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

import httpx2
from ops_core.canonical import canonical_json
from ops_core.outcomes import (
    ActionOutcome,
    DestinationState,
    Receipt,
    Tombstone,
    ToolOutcome,
    outcome_from_destination,
)
from ops_core.states import Reason
from pydantic import ValidationError

TIMEOUT = httpx2.Timeout(10.0)  # one destination call per tool call; the 1, 2, 4, 8 s backoff is the worker's (T22)
# The abort reasons that mean the attempt was never sent (request_abort chose them from INTENT); `deadline` is SENT's.
NEVER_SENT: Final = frozenset({Reason.CANCELLED_BEFORE_SEND.value, Reason.EXPIRED.value})


@dataclass(frozen=True)
class Reply:
    """The destination's HTTP status and parsed JSON document."""

    status_code: int
    document: dict[str, Any]


async def post_incident(
    http: httpx2.AsyncClient,
    *,
    url: str,
    token: str,
    action_id: UUID,
    payload_sha256: str,
    payload_canonical: bytes,
) -> Reply | None:
    """POST the approved bytes; None means the transport gave no usable answer (the caller records UNKNOWN)."""
    # The canonical bytes travel as one JSON string, so the destination hashes exactly what the reviewer approved.
    body = canonical_json(
        {
            "action_id": str(action_id),
            "payload_sha256": payload_sha256,
            "payload_canonical": payload_canonical.decode("utf-8"),
        }
    )
    return await _send(http, "POST", f"{url}/internal/incidents", token, body)


async def get_action(http: httpx2.AsyncClient, *, url: str, token: str, action_id: UUID) -> Reply | None:
    """The restricted lookup (SA:269): the key's receipt or tombstone, or 404 while there is none (UNKNOWN, never
    "no commit"). It reads; it never writes a key."""
    return await _send(http, "GET", f"{url}/internal/actions/{action_id}", token, None)


async def post_abort(
    http: httpx2.AsyncClient, *, url: str, token: str, action_id: UUID, payload_sha256: str, reason: str
) -> Reply | None:
    """The abort (SA:266): a fresh ABORTED tombstone carrying the grant's hash, or the key that already stands (a
    receipt, a REJECTED or an earlier ABORTED tombstone). It never creates an incident."""
    body = canonical_json({"payload_sha256": payload_sha256, "reason": reason})
    return await _send(http, "POST", f"{url}/internal/actions/{action_id}/abort", token, body)


async def _send(http: httpx2.AsyncClient, method: str, url: str, token: str, body: bytes | None) -> Reply | None:
    """One request with the workload token; None means the transport gave no usable answer (the caller's UNKNOWN)."""
    headers = {"Authorization": f"Bearer {token}"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    try:
        response = await http.request(method, url, content=body, headers=headers, timeout=TIMEOUT)
        document = response.json()
    except (httpx2.HTTPError, ValueError):
        return None
    if not isinstance(document, dict):
        return None
    return Reply(response.status_code, document)


def unknown(action_id: UUID, payload_sha256: str) -> ActionOutcome:
    """The outcome for an answer we cannot trust: UNKNOWN, never "no effect"."""
    return ActionOutcome(
        status=ToolOutcome.UNKNOWN,
        action_id=action_id,
        payload_sha256=payload_sha256,
        receipt=None,
        tombstone=None,
        reason=None,
    )


def _conflict(action_id: UUID, payload_sha256: str) -> ActionOutcome:
    return ActionOutcome(
        status=ToolOutcome.CONFLICT,
        action_id=action_id,
        payload_sha256=payload_sha256,
        receipt=None,
        tombstone=None,
        reason=None,
    )


def classify(reply: Reply | None, *, action_id: UUID, payload_sha256: str) -> ActionOutcome:
    """Map the destination's answer to a tool outcome; anything unrecognised is UNKNOWN, never success."""
    if reply is None:
        return unknown(action_id, payload_sha256)
    doc = reply.document
    try:
        if reply.status_code == 409 and doc.get("state") == "CONFLICT":
            return _conflict(action_id, payload_sha256)
        if reply.status_code != 200:
            return unknown(action_id, payload_sha256)
        if doc.get("action_id") != str(action_id) or doc.get("payload_sha256") != payload_sha256:
            return _conflict(action_id, payload_sha256)  # a receipt for something else is not our receipt
        if doc.get("state") == "COMMITTED":
            receipt = Receipt.model_validate_json(json.dumps(doc["receipt"]))  # JSON mode: strict models parse ISO text
            return ActionOutcome(
                status=ToolOutcome.SUCCEEDED,
                action_id=action_id,
                payload_sha256=payload_sha256,
                receipt=receipt,
                tombstone=None,
                reason=None,
            )
        state = DestinationState(doc["state"])
        tombstone = Tombstone.model_validate_json(json.dumps(doc["tombstone"]))
        # An ABORTED key's reason is the one request_abort chose and the abort carried (Plan K ruling 3): `expired` or
        # `cancelled_before_send` only for an attempt never sent; anything else proves only that nothing committed.
        sent = tombstone.reason not in NEVER_SENT
        cancelled = tombstone.reason == Reason.CANCELLED_BEFORE_SEND.value
        outcome, reason = outcome_from_destination(state, sent=sent, cancel_requested=cancelled)
        return ActionOutcome(
            status=outcome,
            action_id=action_id,
            payload_sha256=payload_sha256,
            receipt=None,
            tombstone=tombstone,
            reason=reason,
        )
    except (KeyError, ValueError, ValidationError):
        return unknown(action_id, payload_sha256)

"""The only path from the application to the destination (ADR-0001: mcp-write → incident-sim).

The POST carries the exact canonical bytes the reviewer approved, wrapped with the action id and hash (AM-13 §4). What
comes back is classified into the AM-13 tool outcome vocabulary without optimism: a transport failure after SENT is
UNKNOWN, never "no effect" (BUILD_SPEC §1, §11); a committed receipt counts only if its action id and hash are ours
(SA:358); a tombstone becomes FAILED_NO_COMMIT with the reason `outcome_from_destination` derives.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
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
from pydantic import ValidationError


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
    try:
        response = await http.post(
            f"{url}/internal/incidents",
            content=body,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=httpx2.Timeout(10.0),
        )
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
        outcome, reason = outcome_from_destination(state, sent=True, cancel_requested=False)
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

"""The destination's truth: one `action_key` row per action, written once (AM-13 §4, SA:259-269).

`commit` is `INSERT … ON CONFLICT (action_id) DO NOTHING` followed by a read of whatever row exists, at READ COMMITTED,
which is the whole idempotency mechanism: a retry with the same key and hash gets the same receipt; a different hash
under an existing key is a CONFLICT the caller must escalate, and never a second incident. The destination recomputes
nothing here — app.py already proved the presented hash over the received bytes — but it stores only its own view.
TODO(T10): abort (`ABORTED`), `REJECTED` via the fault factory, and the detective check against grant hashes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from ops_core.persistence import Conn
from psycopg.rows import DictRow
from psycopg.types.json import Jsonb


@dataclass(frozen=True)
class KeyRow:
    action_id: UUID
    payload_sha256: str
    state: str
    incident_id: str | None
    reason: str | None
    receipt_id: UUID | None
    decided_at: datetime


def _row(record: DictRow) -> KeyRow:
    return KeyRow(
        action_id=record["action_id"],
        payload_sha256=record["payload_sha256"],
        state=record["state"],
        incident_id=record["incident_id"],
        reason=record["reason"],
        receipt_id=record["receipt_id"],
        decided_at=record["decided_at"],
    )


async def commit(conn: Conn, *, action_id: UUID, payload_sha256: str, payload: dict[str, Any]) -> KeyRow:
    """Insert the key and its incident, or return the existing key untouched. The caller holds the unit of work
    (`Session.unit()`), so the key and the incident row commit together or not at all."""
    cur = await conn.execute(
        "INSERT INTO incident.action_key (action_id, payload_sha256, state, incident_id, receipt_id)"
        " VALUES (%s, %s, 'COMMITTED', 'INC-' || lpad(nextval('incident.incident_seq')::text, 6, '0'), %s)"
        " ON CONFLICT (action_id) DO NOTHING RETURNING *",
        (action_id, payload_sha256, uuid4()),
    )
    inserted = await cur.fetchone()
    if inserted is not None:
        # The incident row exists only when its key commits in this same transaction (SA:264).
        await conn.execute(
            "INSERT INTO incident.incidents (incident_id, action_id, payload) VALUES (%s, %s, %s)",
            (inserted["incident_id"], action_id, Jsonb(payload)),
        )
        return _row(inserted)
    existing = await lookup(conn, action_id)
    assert existing is not None  # the conflict proved the row exists and rows are never deleted (SA:265)
    return existing


async def lookup(conn: Conn, action_id: UUID) -> KeyRow | None:
    cur = await conn.execute("SELECT * FROM incident.action_key WHERE action_id = %s", (action_id,))
    record = await cur.fetchone()
    return None if record is None else _row(record)


def _stamp(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def document(row: KeyRow, *, presented_sha256: str) -> tuple[int, dict[str, Any]]:
    """The HTTP document for a key row as seen by a caller presenting `presented_sha256` (ruling 9 of Plan D)."""
    if row.state == "COMMITTED" and row.payload_sha256 != presented_sha256:
        return 409, {"state": "CONFLICT", "action_id": str(row.action_id), "payload_sha256": row.payload_sha256}
    doc: dict[str, Any] = {"state": row.state, "action_id": str(row.action_id), "payload_sha256": row.payload_sha256}
    if row.state == "COMMITTED":
        doc["receipt"] = {
            "receipt_id": str(row.receipt_id),
            "incident_id": row.incident_id,
            "committed_at": _stamp(row.decided_at),
        }
    else:
        doc["tombstone"] = {
            "action_id": str(row.action_id),
            "state": row.state,
            "payload_sha256": row.payload_sha256,
            "reason": row.reason or row.state.lower(),
            "decided_at": _stamp(row.decided_at),
        }
    return 200, doc

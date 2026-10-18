"""keys.commit against the real `incident` database as role `incident` (OPS_LIVE=1): first-writer-wins, replay returns
the same receipt, and the destination's role cannot read the application schema (separate credentials,
BUILD_SPEC §14)."""

from uuid import uuid4

import psycopg
import pytest
from ops_core import persistence, settings
from ops_core.canonical import canonical_sha256
from ops_incident_sim import keys

pytestmark = pytest.mark.asyncio


async def test_commit_replay_conflict_and_isolation(migrated: None) -> None:
    conn = await persistence.connect(settings.incident_postgres())
    try:
        async with conn.transaction(force_rollback=True):  # the live key table keeps nothing from this test
            action = uuid4()
            payload = {"title": "live", "n": 1}
            first = await keys.commit(conn, action_id=action, payload_sha256=canonical_sha256(payload), payload=payload)
            again = await keys.commit(conn, action_id=action, payload_sha256=canonical_sha256(payload), payload=payload)
            assert first == again and first.incident_id.startswith("INC-") and first.state == "COMMITTED"
            other = await keys.commit(conn, action_id=action, payload_sha256="0" * 64, payload={"x": 1})
            assert other == first  # the key keeps its first hash; document() turns this into CONFLICT
            assert keys.document(other, presented_sha256="0" * 64)[0] == 409
            cur = await conn.execute("SELECT count(*) AS n FROM incident.incidents WHERE action_id = %s", (action,))
            assert (await cur.fetchone())["n"] == 1
        # The application schema is not even visible from the destination's database (separate credentials).
        with pytest.raises((psycopg.errors.InsufficientPrivilege, psycopg.errors.UndefinedTable)):
            await conn.execute("SELECT 1 FROM app.runs")
    finally:
        await conn.close()

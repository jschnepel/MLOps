"""The tool allowlist that stayed in Python (BUILD_SPEC §9, Plan E ruling 21) and one SQLSTATE mapping.

The server, azp, expiry and revocation checks live in `app._resolve_handle` (Task 4's live test); this module holds
only what needs no database.

Catches: a read job allowed to call a write tool, an execute job allowed to call the recover-only receipt tool, and a
handle refusal that echoes the server's text.
"""

from types import SimpleNamespace

import psycopg
import pytest
from ops_core.jobs import JobType, Tool
from ops_core.persistence import HandleRejected, allowed_tool, translate
from ops_core.states import RunState


@pytest.mark.parametrize(
    ("job_type", "state", "tool"),
    [
        (JobType.INVESTIGATE, RunState.RETRIEVING, Tool.CREATE_INCIDENT),  # a read job may not call a write tool
        (JobType.EXECUTE, RunState.APPROVED, Tool.GET_INCIDENT_RECEIPT),  # execute is not recover
    ],
)
def test_rejections(job_type: JobType, state: RunState, tool: Tool) -> None:
    with pytest.raises(HandleRejected):
        allowed_tool(job_type, state, None, tool)  # refused on the tool, before any attempt rule


def test_handle_refusal_never_echoes_the_server_text() -> None:
    diag = SimpleNamespace(message_detail="secret-handle-value", message_primary="secret-handle-value")
    exc = type("FakeError", (psycopg.DatabaseError,), {"diag": property(lambda self: diag)})("x")
    exc.sqlstate = "OC008"
    mapped = translate(exc)
    assert isinstance(mapped, HandleRejected) and "secret-handle-value" not in str(mapped)

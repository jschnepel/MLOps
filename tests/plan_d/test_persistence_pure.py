"""Invocation-handle checks (BUILD_SPEC §9 handle binding, R131 in miniature): the part of resolve_invocation that
needs no database — expiry, revocation, server binding derived from the job type (not the stored column), the caller's
azp, and the per-job-type tool allowlist.

Catches: an expired or revoked handle still usable, a read handle accepted by mcp-write (server derived from the
worker-written column instead of the job type), another workload's token replaying a stolen handle, and a read job
calling a write tool.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from ops_core.jobs import JobType, Server, Tool
from ops_core.persistence import HandleRejected, check_invocation

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
RUN, JOB, TENANT, CONV = UUID(int=1), UUID(int=2), UUID(int=3), UUID(int=4)


def row(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "handle": "h",
        "run_id": RUN,
        "job_id": JOB,
        "server": "read",
        "azp": "ops-worker",
        "expires_at": NOW + timedelta(seconds=30),
        "revoked_at": None,
        "job_type": "investigate",
        "tenant_id": TENANT,
        "conversation_id": CONV,
    }
    base.update(over)
    return base


def test_valid_read_handle_resolves_to_its_run_and_job():
    inv = check_invocation(row(), server=Server.READ, azp="ops-worker", tool=Tool.SEARCH_PROCEDURES, now=NOW)
    assert (inv.run_id, inv.job_id, inv.job_type, inv.tenant_id) == (RUN, JOB, JobType.INVESTIGATE, TENANT)


@pytest.mark.parametrize(
    ("over", "server", "azp", "tool"),
    [
        ({"expires_at": NOW}, Server.READ, "ops-worker", Tool.SEARCH_PROCEDURES),  # expiry is exclusive
        ({"revoked_at": NOW - timedelta(seconds=1)}, Server.READ, "ops-worker", Tool.SEARCH_PROCEDURES),
        ({}, Server.WRITE, "ops-worker", Tool.CREATE_INCIDENT),  # investigate handle presented to mcp-write
        ({"job_type": "execute", "server": "read"}, Server.READ, "ops-worker", Tool.SEARCH_PROCEDURES),  # column lies
        ({}, Server.READ, "ops-mcp-write", Tool.SEARCH_PROCEDURES),  # another workload replays the handle
        ({}, Server.READ, "ops-worker", Tool.CREATE_INCIDENT),  # a read job may not call a write tool
        (
            {"job_type": "execute", "server": "write"},
            Server.WRITE,
            "ops-worker",
            Tool.GET_INCIDENT_RECEIPT,
        ),  # execute ≠ recover
    ],
)
def test_rejections(over: dict[str, object], server: Server, azp: str, tool: Tool):
    with pytest.raises(HandleRejected):
        check_invocation(row(**over), server=server, azp=azp, tool=tool, now=NOW)


def test_rejection_messages_never_echo_the_handle():
    with pytest.raises(HandleRejected) as caught:
        check_invocation(
            row(handle="secret-handle-value", expires_at=NOW),
            server=Server.READ,
            azp="ops-worker",
            tool=Tool.SEARCH_PROCEDURES,
            now=NOW,
        )
    assert "secret-handle-value" not in str(caught.value)

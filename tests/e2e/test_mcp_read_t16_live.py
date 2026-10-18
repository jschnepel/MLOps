"""mcp-read's read tools over a real socket with Keycloak's tokens, asset-sim behind it (OPS_LIVE=1; R028, T16 DoD
1; Plan M rulings 3, 7-10 and 15).

mcp-read is `production_app()` under uvicorn on a free loopback port (test_mcp_read_t15_live's `serving`), asset-sim
the `asset_sim` fixture's, both in the test's loop; mcp-read reaches asset-sim with its own `ops-mcp-read` token.
Catches: a status or alert page that is not asset-sim's answer for the run's asset at the database instant (a moved
test clock must move it into the A17 seal-leak window); a page whose `truncated` disagrees with `next_cursor`; alpha
reading beta's B22, whether it names B22 on an A17 run (refused before asset-sim) or its run itself names B22
(asset-sim's own tenant filter: NOT_FOUND); another interval served; a search that leaves the run's asset type or
returns a revoked procedure; a requester who lost the membership still served by any of the three tools; and an
asset-sim failure (unavailable, malformed, slow) that is not the documented envelope.
Writes reports/mcp-read/t16-read-tools.txt (codes and counts only).
"""

import time
from collections.abc import Awaitable, Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx2
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from ops_core import persistence, settings, tool_contracts
from ops_core.jobs import Tool
from ops_core.mcp_protocol import PROTOCOL_VERSION
from ops_core.settings import Role
from ops_core.tokens import WorkloadTokenSource

from tests.e2e.conftest import lease_for, purge_run
from tests.e2e.test_fenced_definers_live import investigate_job, read_handle
from tests.e2e.test_mcp_read_t15_live import call, serving, worker_token
from tests.e2e.test_migrations_and_persistence import new_run

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("ingested", "asset_sim")]

RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
ALPHA = UUID("3ea79c95-914c-52cb-9d10-c4e19dda8ff7")
ALEX = UUID("2fc05986-c7ec-544c-b628-fdb112bbf18a")
SEAL_WINDOW = (datetime(2026, 10, 5, tzinfo=UTC), datetime(2026, 10, 7, tzinfo=UTC))  # both A17 seal alerts
INTERVAL = {"start_at": "2026-10-05T00:00:00Z", "end_at": "2026-10-07T00:00:00Z"}
MOVE = "UPDATE app.test_clock SET clock_offset = %s::timestamptz - clock_timestamp()"  # test_harness only (AM-20.6)
EVIDENCE = Path("reports/mcp-read/t16-read-tools.txt")
EXPECTED_LINES = 5  # one per test below


@pytest.fixture(scope="module")
def lines() -> Iterator[list[str]]:
    out = [f"T16 read tools — {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}"]
    yield out
    if len(out) != 1 + EXPECTED_LINES:  # a failed or partial run leaves the committed file as it was
        return
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")


async def handle_for(app_conn: persistence.Conn, role_conn: RoleConn, run: UUID, owner: str) -> str:
    """A read handle for the run's investigate job under a lease taken now."""
    worker = await role_conn(Role.WORKER)
    lease = await lease_for(worker, run, owner=owner, seconds=600)
    return await read_handle(worker, run, await investigate_job(app_conn, run), lease)


async def tool(
    url: str, token: str, handle: str, name: Tool, arguments: dict[str, Any], *, read_timeout: float | None = None
) -> dict[str, Any]:
    """One call's envelope, checked against the committed contract whatever it says. Every call goes through
    test_mcp_read_t15_live's `call`, whose client keeps httpx2's default 5-second timeout, except one that is slow on
    purpose: mcp-read answers it only after its own 10 seconds toward asset-sim, so that call gets its own client
    with `read_timeout` above both (the default would end it first, as a transport error, not the envelope)."""
    if read_timeout is None:
        result = await call(url, token, handle, tool=name.value, arguments=arguments)
    else:
        headers = {"Authorization": f"Bearer {token}", "X-Ops-Invocation": handle}
        async with (
            httpx2.AsyncClient(headers=headers, timeout=httpx2.Timeout(10.0, read=read_timeout)) as http,
            Client(streamable_http_client(url, http_client=http), mode=PROTOCOL_VERSION) as client,
        ):
            result = await client.call_tool(name.value, arguments)
    assert not result.is_error and isinstance(result.structured_content, dict)
    return tool_contracts.check_result(name, result.structured_content)


async def test_the_asset_tools_answer_for_the_run_at_the_database_instant(
    app_conn: persistence.Conn, role_conn: RoleConn, secret: Callable[[str], str], lines: list[str]
) -> None:
    harness = await role_conn(Role.TEST_HARNESS)
    _, _, run = await new_run(app_conn, ALPHA, api=await role_conn(Role.API), interval=SEAL_WINDOW)
    token = await worker_token(secret)
    try:
        async with serving() as url:
            handle = await handle_for(app_conn, role_conn, run, "t16-now")
            now = await tool(url, token, handle, Tool.GET_ASSET_STATUS, {"asset_id": "A17"})
            assert (now["data"]["state"], now["data"]["revision"]) == ("normal", 2)  # after both alerts' windows
            first = await tool(url, token, handle, Tool.GET_RECENT_ALERTS, {"asset_id": "A17", **INTERVAL, "limit": 1})
            cursor = first["data"]["next_cursor"]
            assert len(first["data"]["alerts"]) == 1 and first["truncated"] and cursor
            rest = {"asset_id": "A17", **INTERVAL, "limit": 1, "cursor": cursor}
            second = await tool(url, token, handle, Tool.GET_RECENT_ALERTS, rest)
            assert len(second["data"]["alerts"]) == 1 and not second["truncated"]
            assert second["data"]["next_cursor"] is None
            assert [a["revision"] for a in first["data"]["alerts"] + second["data"]["alerts"]] == [1, 2]
            forged = {"asset_id": "A17", **INTERVAL, "limit": 1, "cursor": "c" * 76}  # asset-sim's 400, as an envelope
            refused = await tool(url, token, handle, Tool.GET_RECENT_ALERTS, forged)
            assert refused["data"] is None and refused["error"]["code"] == "INVALID_CURSOR"
            assert refused["error"]["retryable"] is False
            try:
                # The database clock moved back inside the A17 window. The handle stays good: its lease and its 60 s
                # lie further ahead of a clock moved back. At 2026-10-06T12:00Z the status asset-sim derives at the
                # forwarded instant is warning; at 00:00Z only the alert raised by then is listed (ruling 9).
                await harness.execute(MOVE, ("2026-10-06T12:00:00Z",))
                inside = await tool(url, token, handle, Tool.GET_ASSET_STATUS, {"asset_id": "A17"})
                assert (inside["data"]["state"], inside["data"]["revision"]) == ("warning", 2)
                assert inside["observed_at"].startswith("2026-10-06T12:00")  # as_of, not the wall clock
                await harness.execute(MOVE, ("2026-10-06T00:00:00Z",))
                early = await tool(
                    url, token, handle, Tool.GET_RECENT_ALERTS, {"asset_id": "A17", **INTERVAL, "limit": 10}
                )
                assert [a["revision"] for a in early["data"]["alerts"]] == [1]  # seal-002 is still in the future
            finally:
                await harness.execute("UPDATE app.test_clock SET clock_offset = interval '0'")
        lines.append(
            "asset tools: A17 normal r2 now, warning r2 at 2026-10-06T12:00Z; alerts paged 1+1 by cursor; a forged cursor INVALID_CURSOR"
        )
    finally:
        await purge_run(app_conn, run)


async def test_r028_alpha_never_reads_b22(
    app_conn: persistence.Conn, role_conn: RoleConn, secret: Callable[[str], str], lines: list[str]
) -> None:
    api = await role_conn(Role.API)
    _, _, a17_run = await new_run(app_conn, ALPHA, api=api, interval=SEAL_WINDOW)
    _, _, b22_run = await new_run(app_conn, ALPHA, api=api, asset_id="B22", interval=SEAL_WINDOW)
    token = await worker_token(secret)
    try:
        async with serving() as url:
            a17 = await handle_for(app_conn, role_conn, a17_run, "t16-a17")
            named = await tool(url, token, a17, Tool.GET_ASSET_STATUS, {"asset_id": "B22"})
            widened = {"asset_id": "A17", "start_at": "2026-10-01T00:00:00Z", "end_at": "2026-10-07T00:00:00Z"}
            wider = await tool(url, token, a17, Tool.GET_RECENT_ALERTS, {**widened, "limit": 5})
            # Admission ties no asset to its tenant (fact sheet 3.4): this alpha run itself names beta's B22, so
            # mcp-read forwards it, and asset-sim's own tenant filter answers as for an unknown asset.
            b22 = await handle_for(app_conn, role_conn, b22_run, "t16-b22")
            status = await tool(url, token, b22, Tool.GET_ASSET_STATUS, {"asset_id": "B22"})
            alerts = await tool(url, token, b22, Tool.GET_RECENT_ALERTS, {"asset_id": "B22", **INTERVAL, "limit": 5})
        codes = [doc["error"]["code"] for doc in (named, wider, status, alerts)]
        assert codes == ["ASSET_OUT_OF_SCOPE", "INTERVAL_OUT_OF_SCOPE", "NOT_FOUND", "NOT_FOUND"]
        assert all(doc["data"] is None for doc in (named, wider, status, alerts))  # no beta data reached the caller
        lines.append(f"R028: alpha -> B22 {codes}")
    finally:
        await purge_run(app_conn, a17_run)
        await purge_run(app_conn, b22_run)


async def test_r028_a_requester_who_lost_the_membership_gets_no_asset_data(
    app_conn: persistence.Conn, role_conn: RoleConn, secret: Callable[[str], str], lines: list[str]
) -> None:
    _, _, run = await new_run(app_conn, ALPHA, api=await role_conn(Role.API), interval=SEAL_WINDOW)
    token = await worker_token(secret)
    calls = (
        (Tool.GET_ASSET_STATUS, {"asset_id": "A17"}),
        (Tool.GET_RECENT_ALERTS, {"asset_id": "A17", **INTERVAL, "limit": 5}),
        (Tool.SEARCH_PROCEDURES, {"query": "seal inspection", "limit": 3, "mode": "lexical"}),
    )
    try:
        async with serving() as url:
            handle = await handle_for(app_conn, role_conn, run, "t16-member")
            assert all([(await tool(url, token, handle, n, a))["status"] == "ok" for n, a in calls])
            try:
                await app_conn.execute(
                    "UPDATE app.memberships SET active = false WHERE tenant_id = %s AND subject = %s", (ALPHA, ALEX)
                )
                refused = [await tool(url, token, handle, n, a) for n, a in calls]
            finally:
                await app_conn.execute(
                    "UPDATE app.memberships SET active = true WHERE tenant_id = %s AND subject = %s", (ALPHA, ALEX)
                )
            assert all([(await tool(url, token, handle, n, a))["status"] == "ok" for n, a in calls])
        assert [doc["error"] for doc in refused] == [
            {"code": "INVALID_HANDLE", "message": "invocation handle rejected", "retryable": False}
        ] * 3  # the one plain refusal: nothing tells the caller it was the membership (SA:355)
        lines.append("R028 membership: all three tools INVALID_HANDLE while alex was inactive; ok before and after")
    finally:
        await purge_run(app_conn, run)


async def test_r028_the_search_keeps_to_the_runs_asset_type_and_never_returns_a_revoked_procedure(
    app_conn: persistence.Conn, role_conn: RoleConn, secret: Callable[[str], str], lines: list[str]
) -> None:
    _, _, run = await new_run(app_conn, ALPHA, api=await role_conn(Role.API))
    token = await worker_token(secret)
    query = {"query": "alarm bypass seal inspection", "limit": 8, "mode": "lexical"}
    try:
        async with serving() as url:
            handle = await handle_for(app_conn, role_conn, run, "t16-search")
            own = await tool(url, token, handle, Tool.SEARCH_PROCEDURES, query)
            other = await tool(url, token, handle, Tool.SEARCH_PROCEDURES, {**query, "asset_type": "compressor"})
        documents = {r["document_id"] for r in own["data"]["results"]}
        # A17 is a pump: pump documents or any-asset ones only; ALPHA-ALARM-BYPASS (a pump document) is revoked.
        assert documents and documents <= {"ALPHA-PUMP-SEAL", "ALPHA-ALERT-REVIEW"}
        assert all(r["retrieved_at"] == own["observed_at"] for r in own["data"]["results"])  # the definer's instant
        assert other["error"]["code"] == "ASSET_TYPE_OUT_OF_SCOPE" and other["data"] is None
        lines.append(f"R028 search: run type pump -> {sorted(documents)}; revoked bypass absent; compressor refused")
    finally:
        await purge_run(app_conn, run)


async def test_asset_sim_failures_reach_the_caller_as_their_envelopes(
    app_conn: persistence.Conn, role_conn: RoleConn, secret: Callable[[str], str], asset_sim: str, lines: list[str]
) -> None:
    _, _, run = await new_run(app_conn, ALPHA, api=await role_conn(Role.API), interval=SEAL_WINDOW)
    token = await worker_token(secret)
    mcp_read_token = await WorkloadTokenSource(
        token_url=settings.keycloak().token_url,
        client_id="ops-mcp-read",
        client_secret=secret("kc_client_secret_ops_mcp_read"),
    ).token()

    async def arm(kind: str, **body: int) -> None:
        async with httpx2.AsyncClient(base_url=asset_sim) as http:
            answer = await http.post(
                f"/internal/faults/{kind}",
                headers={"Authorization": f"Bearer {mcp_read_token}"},
                json={"count": 1, **body},
            )
        assert answer.status_code == 200, kind

    try:
        async with serving() as url:
            handle = await handle_for(app_conn, role_conn, run, "t16-faults")
            seen = {}
            for kind, body, read_timeout in (
                ("asset_unavailable", {}, None),
                ("drop_before_commit", {}, None),
                ("malformed_response", {}, None),
                # asset-sim holds 11 s; mcp-read gives up after 10 s (ruling 15); this client waits up to 30 s.
                ("timeout_before_accept", {"seconds": 11}, 30.0),
            ):
                await arm(kind, **body)
                status = {"asset_id": "A17"}
                doc = await tool(url, token, handle, Tool.GET_ASSET_STATUS, status, read_timeout=read_timeout)
                seen[kind] = (doc["data"] or {}).get("state") or (doc["error"]["code"], doc["error"]["retryable"])
        assert seen == {
            "asset_unavailable": "unavailable",  # the contract's third state, an ok answer
            "drop_before_commit": ("UNAVAILABLE", True),
            "malformed_response": ("UPSTREAM_INVALID", False),
            "timeout_before_accept": ("UNAVAILABLE", True),
        }
        lines.append(f"asset-sim faults through mcp-read: {seen}")
    finally:
        await purge_run(app_conn, run)

"""mcp-write's T47 cases over a real socket with Keycloak's tokens and a real incident-sim (OPS_LIVE=1; R030, R131
write half, T47 DoD 1-3, T47 review note 3; Plan K rulings 8, 13-15, 19-21 and 24).

mcp-write is `production_app()` under uvicorn on a free loopback port in the test's own event loop, pointed at an
incident-sim `production_app()` on another free port (the test profile, so its fault route exists); the independent
process is tests/e2e/test_mcp_write_process_live.py. Every recover handle is staged by the superuser, as mark_unknown
or the sweeper would queue its job (the worker's recover handler is T22's). mcp-write's destination calls are counted
in-process (`ops_mcp_write.destination`), and the destination's own tables are read as role `incident`.

Catches: an `mcp_exec` that may execute anything beyond its seven functions; a read handle (investigate, resume_input,
or one whose stored server column lies) answered at mcp-write; incident-sim accepting mcp-read's token; a receipt lookup
or an abort answered for an execute or investigate handle, or for an APPROVED run (no grant); a lookup that writes a
key, a grant, an attempt, a job or a proposal, or answers more than the minimal outcome; an abort that writes more than
its own state rows and its tombstone; the re-queued execute job's re-send
creating a second action or incident, or its call after an abort request refused instead of answered UNKNOWN with
nothing sent (final review I1); a delayed receipt's 404 at the lookup, or a rate limit or a lost reply at the send,
answered as anything but an unrecorded UNKNOWN; a foreign receipt hash recorded as anything but CONFLICT, or re-queried
once recorded; an abort before it is due; a cancelled or expired attempt sent instead of aborted, or ending without the
destination's tombstone; and a redispatch outside EXECUTING that sends anything.

What it does not pin rests on other modules: the lookup's 429, 503 and lost reply, the abort's unanswered and
resolved branches and the other proposal's refusal are scripted in tests/plan_k/test_recovery_tools.py; the definers'
own rules (the abort's reasons, the deadline, a receipt after an abort, the token's `azp`, another run's action id)
are called directly in tests/e2e/test_migration_0010_live.py.
"""

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx2
import pytest
import uvicorn
from mcp_types import CallToolResult
from ops_core import persistence, privileges, settings
from ops_core.jobs import Server
from ops_core.settings import Role
from ops_core.tokens import WorkloadTokenSource
from ops_incident_sim.app import production_app as incident_sim_app
from ops_mcp_write import destination
from ops_mcp_write.server import production_app

from tests.e2e.conftest import lease_for, purge_run
from tests.e2e.test_definers_run_path_live import refused
from tests.e2e.test_fenced_definers_live import attempt_states, investigate_job, read_handle
from tests.e2e.test_mcp_read_t15_live import assert_refused, call, free_port, guarded, set_server, worker_token
from tests.e2e.test_mcp_write_live import ALPHA, approved_run
from tests.e2e.test_migration_0010_live import AZP, LATE, NOW, cancel, execute_handle, fence_of, recover_handle
from tests.e2e.test_migrations_and_persistence import new_run

pytestmark = pytest.mark.asyncio

RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
EVIDENCE = Path("reports/mcp-write/t47-mcp-write.txt")
EXPECTED_LINES = 11  # one per test below
WRITE_TOOLS = ("create_incident", "get_incident_receipt", "abort_incident")
MCP_EXEC_FUNCTIONS = {
    "current_time",  # erratum 15
    "resolve_invocation",
    "grant_execution",
    "mark_sent",
    "record_outcome",
    "request_abort",
    "lookup_action",
}
COUNTS = (
    "SELECT (SELECT count(*) FROM app.execution_grant) AS grants, (SELECT count(*) FROM app.action_attempt)"
    " AS attempts, (SELECT count(*) FROM app.jobs) AS jobs, (SELECT count(*) FROM app.proposals) AS proposals"
)


@pytest.fixture(scope="module")
def lines() -> Iterator[list[str]]:
    out = [f"T47 mcp-write — {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}"]
    yield out
    if len(out) != 1 + EXPECTED_LINES:  # a failed or partial run leaves the committed file as it was
        return
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")


@asynccontextmanager
async def started(app: Any, name: str) -> AsyncIterator[str]:
    """`app` under uvicorn on a free loopback port in this event loop; its base URL. Stopped in `finally` by uvicorn's
    own shutdown, never a cancel; a failed start or a failure after it is raised, not only logged."""
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", log_config=None))
    task = asyncio.create_task(guarded(server))
    try:
        while not server.started:
            if task.done():
                task.result()  # a failed start raises here instead of waiting for ever
            await asyncio.sleep(0.05)
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await asyncio.wait({task})
    failure = None if task.cancelled() else task.exception()
    if failure is not None:
        raise RuntimeError(f"{name} failed after it started") from failure


@asynccontextmanager
async def write_stack(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[tuple[str, str]]:
    """incident-sim, then mcp-write pointed at it (mcp-write reads `OPS_INCIDENT_SIM_URL` at its start); both URLs."""
    async with started(incident_sim_app(), "incident-sim") as sim:
        monkeypatch.setenv("OPS_INCIDENT_SIM_URL", sim)
        async with started(production_app(), "mcp-write") as base:
            yield sim, f"{base}/mcp"


async def write_token(secret: Callable[[str], str]) -> str:
    """mcp-write's own workload token (aud incident-sim, azp ops-mcp-write): what arms incident-sim's faults."""
    kcs = settings.keycloak()
    return await WorkloadTokenSource(
        token_url=kcs.token_url, client_id="ops-mcp-write", client_secret=secret("kc_client_secret_ops_mcp_write")
    ).token()


async def arm(sim: str, token: str, kind: str) -> None:
    """Arm one occurrence of a test-profile destination fault."""
    async with httpx2.AsyncClient() as http:
        armed = await http.post(
            f"{sim}/internal/faults/{kind}", json={"count": 1}, headers={"Authorization": f"Bearer {token}"}
        )
    assert armed.status_code == 200 and kind in armed.json()["armed"]


class Calls:
    """mcp-write's destination calls, counted in-process (the server runs in this test's event loop)."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.made: list[str] = []
        for name in ("post_incident", "get_action", "post_abort"):
            monkeypatch.setattr(destination, name, self.counted(name, getattr(destination, name)))

    def counted(self, name: str, real: Any) -> Any:
        async def call(*args: Any, **kwargs: Any) -> Any:
            self.made.append(name)
            return await real(*args, **kwargs)

        return call


def data(result: CallToolResult, status: str) -> dict[str, Any]:
    """An answered call's envelope data, with the envelope status checked: no transport error, no error object."""
    doc = result.structured_content
    assert not result.is_error and isinstance(doc, dict) and doc["status"] == status and doc["error"] is None
    assert isinstance(doc["data"], dict)
    return doc["data"]


def error(result: CallToolResult) -> dict[str, Any]:
    """A refused call's error object; a refusal never carries data or an action id (SA:355)."""
    doc = result.structured_content
    assert not result.is_error and isinstance(doc, dict) and doc["status"] == "error" and doc["data"] is None
    assert "action_id" not in str(doc)
    assert isinstance(doc["error"], dict)
    return doc["error"]


async def keys_total(incident_conn: persistence.Conn) -> int:
    """Every key the destination holds, whoever's: a call that must write none is checked against this."""
    cur = await incident_conn.execute("SELECT count(*) AS n FROM incident.action_key")
    return int((await cur.fetchone() or {})["n"])


async def at_destination(incident_conn: persistence.Conn, action: UUID) -> tuple[tuple[str, str | None] | None, int]:
    """The destination's key for the action (state, reason) and how many incidents it holds for it."""
    cur = await incident_conn.execute("SELECT state, reason FROM incident.action_key WHERE action_id = %s", (action,))
    key = await cur.fetchone()
    cur = await incident_conn.execute("SELECT count(*) AS n FROM incident.incidents WHERE action_id = %s", (action,))
    return (None if key is None else (key["state"], key["reason"])), int((await cur.fetchone() or {})["n"])


async def run_state(app_conn: persistence.Conn, run: UUID) -> tuple[str, str | None]:
    cur = await app_conn.execute("SELECT state, reason FROM app.runs WHERE run_id = %s", (run,))
    row = await cur.fetchone() or {}
    return row["state"], row["reason"]


async def test_r131_mcp_exec_executes_exactly_the_write_path_functions(
    app_conn: persistence.Conn, role_conn: RoleConn, lines: list[str]
) -> None:
    """Ruling 13: the pg_proc ACL. "No read function" is no EXECUTE on any `app` function outside the seven, the
    read functions `search_procedures_scoped` (T17) and `asset_scope` (T16) among them, each refused when called."""
    cur = await app_conn.execute(
        "SELECT p.proname AS name, has_function_privilege('mcp_exec', p.oid, 'EXECUTE') AS allowed"
        " FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = 'app'"
    )
    rows = await cur.fetchall()
    assert {row["name"] for row in rows if row["allowed"]} == MCP_EXEC_FUNCTIONS
    others = (set(privileges.DEFINER_FUNCTIONS) | set(privileges.HELPER_FUNCTIONS)) - MCP_EXEC_FUNCTIONS
    assert others <= {row["name"] for row in rows}  # every other function exists, so the line above is not vacuous
    mcp_exec = await role_conn(Role.MCP_EXEC)
    code = await refused(mcp_exec, "SELECT * FROM app.mark_unknown(%s, 1)", (uuid4(),))
    assert code == "42501"  # the worker's
    assert "search_procedures_scoped" in others  # mcp-read's (T17)
    search = "SELECT * FROM app.search_procedures_scoped('h', 'ops-worker', 'x', NULL, NULL, 1, 'lexical')"
    assert await refused(mcp_exec, search, ()) == "42501"
    assert "asset_scope" in others  # mcp-read's (T16)
    assert await refused(mcp_exec, "SELECT * FROM app.asset_scope('h', 'ops-worker')", ()) == "42501"
    lines.append(
        f"R131 write half: mcp_exec EXECUTE = the seven write-path functions; {len(others)} others refused"
        " (mark_unknown 42501)"
    )


async def test_r131_read_handles_are_refused_at_mcp_write(
    app_conn: persistence.Conn,
    role_conn: RoleConn,
    secret: Callable[[str], str],
    monkeypatch: pytest.MonkeyPatch,
    lines: list[str],
) -> None:
    """Ruling 14: an investigate and a resume_input handle at each of the three tools, then the investigate handle with
    a stored server column that lies; each is live at mcp_read (the positive control) and grants nothing; the execute
    handle of an approved run is then answered at mcp-write."""
    api, worker = await role_conn(Role.API), await role_conn(Role.WORKER)
    mcp_read, mcp_exec = await role_conn(Role.MCP_READ), await role_conn(Role.MCP_EXEC)
    _, _, read_run = await new_run(app_conn, ALPHA, api=api)
    _, run, proposal, execute = await approved_run(app_conn, api=api, worker=worker)
    token = await worker_token(secret)
    arguments = {"proposal_id": str(proposal)}
    resolve = "SELECT job_id FROM app.resolve_invocation(%s, 'ops-worker')"
    try:
        lease = await lease_for(worker, read_run)
        investigate = await read_handle(worker, read_run, await investigate_job(app_conn, read_run), lease)
        resume = uuid4()  # a resume_input job staged by the superuser: the worker creates none before T20
        await app_conn.execute(
            "INSERT INTO app.jobs (id, type, tenant_id, run_id, dedup_key) VALUES (%s, 'resume_input', %s, %s, %s)",
            (resume, ALPHA, read_run, f"{read_run}:{uuid4()}"),
        )
        async with worker.transaction():
            resume_input = await persistence.mint_handle(
                worker, run_id=read_run, job_id=resume, server=Server.READ, azp=AZP, fence=lease.fence
            )
        cur = await app_conn.execute(COUNTS)
        before = dict(await cur.fetchone() or {})
        async with write_stack(monkeypatch) as (_, url):
            for handle in (investigate, resume_input):
                cur = await mcp_read.execute(resolve, (handle,))
                assert (await cur.fetchone() or {}).get("job_id") is not None  # live at mcp-read
                for tool in WRITE_TOOLS:
                    assert_refused(await call(url, token, handle, tool, arguments))
            await set_server(app_conn, investigate, "write")  # the lie: the job type still says read
            for tool in WRITE_TOOLS:
                assert_refused(await call(url, token, investigate, tool, arguments))
            code = await refused(mcp_exec, resolve, (investigate,))  # bound first: no handle as an assert operand
            assert code == "OC008"  # mcp_exec's own resolution agrees
            await set_server(app_conn, investigate, "read")
            cur = await mcp_read.execute(resolve, (investigate,))
            assert (await cur.fetchone() or {}).get("job_id") == await investigate_job(app_conn, read_run)
            cur = await app_conn.execute(COUNTS)
            assert dict(await cur.fetchone() or {}) == before  # nine refusals: no grant, attempt, job or proposal
            answered = data(await call(url, token, execute, "create_incident", arguments), "ok")
            assert answered["status"] == "SUCCEEDED"  # the write handle is answered here
        lines.append(
            "R131 write half: investigate and resume_input handles refused at all three tools (each live at mcp_read),"
            " lying server column refused (and at mcp_exec); no grant; the execute handle answered SUCCEEDED"
        )
    finally:
        await purge_run(app_conn, read_run)
        await purge_run(app_conn, run)


async def test_r131_incident_sim_refuses_mcp_reads_token(
    incident_conn: persistence.Conn, secret: Callable[[str], str], lines: list[str]
) -> None:
    """Ruling 15: mcp-read's workload token at each incident-sim route is 403 and writes nothing; mcp-write's token on
    the same lookup passes authentication (the positive control). That mcp-read cannot reach incident-sim over the
    network is T30's Docker network test."""
    kcs = settings.keycloak()
    read_token = await WorkloadTokenSource(
        token_url=kcs.token_url, client_id="ops-mcp-read", client_secret=secret("kc_client_secret_ops_mcp_read")
    ).token()
    action, sha = uuid4(), "e" * 64
    body = {"action_id": str(action), "payload_sha256": sha, "payload_canonical": '{"x":1}'}
    routes = {
        "incident": ("POST", "/internal/incidents", body),
        "lookup": ("GET", f"/internal/actions/{action}", None),
        "abort": ("POST", f"/internal/actions/{action}/abort", {"payload_sha256": sha, "reason": "expired"}),
    }
    cur = await incident_conn.execute("SELECT count(*) AS n FROM incident.action_key")
    keys = int((await cur.fetchone() or {})["n"])
    async with started(incident_sim_app(), "incident-sim") as sim, httpx2.AsyncClient() as http:
        answers = {}
        for name, (method, path, payload) in routes.items():
            headers = {"Authorization": f"Bearer {read_token}"}
            response = await http.request(method, f"{sim}{path}", json=payload, headers=headers)
            answers[name] = (response.status_code, response.json()["code"])
        own = {"Authorization": f"Bearer {await write_token(secret)}"}
        control = await http.get(f"{sim}/internal/actions/{action}", headers=own)
    assert answers == {name: (403, "FORBIDDEN") for name in routes}
    assert (control.status_code, control.json()["code"]) == (404, "NOT_FOUND")  # authenticated; no such key
    cur = await incident_conn.execute("SELECT count(*) AS n FROM incident.action_key")
    assert int((await cur.fetchone() or {})["n"]) == keys  # nothing written
    lines.append("R131/DoD 3 token half: ops-mcp-read token 403 at incidents, lookup and abort; ops-mcp-write 404")


async def test_r030_the_receipt_lookup_is_recover_only_and_creates_nothing(
    app_conn: persistence.Conn,
    role_conn: RoleConn,
    incident_conn: persistence.Conn,
    secret: Callable[[str], str],
    monkeypatch: pytest.MonkeyPatch,
    lines: list[str],
) -> None:
    """Rulings 8 and 19: the reply to the first send is lost after commit (UNKNOWN, attempt SENT); an execute handle,
    an investigate handle and a recover handle of an APPROVED run (no grant) are refused at the recovery tools, the last
    by the run-state rule (a run in a recover state without a grant cannot arise: only grant_execution leaves
    APPROVED for EXECUTING, and only with a grant); a recover
    handle's first lookup meets a delayed receipt (404: UNKNOWN, nothing recorded), its second the receipt (SUCCEEDED,
    the minimal outcome). Nothing but one RESOLVED row is written, and nothing is POSTed."""
    api, worker = await role_conn(Role.API), await role_conn(Role.WORKER)
    _, run, proposal, execute = await approved_run(app_conn, api=api, worker=worker)
    _, bare, bare_proposal, _ = await approved_run(app_conn, api=api, worker=worker)  # APPROVED, never granted
    _, _, read_run = await new_run(app_conn, ALPHA, api=api)
    token, own = await worker_token(secret), await write_token(secret)
    arguments = {"proposal_id": str(proposal)}
    try:
        async with write_stack(monkeypatch) as (sim, url):
            await arm(sim, own, "lose_after_commit")
            first = data(await call(url, token, execute, "create_incident", arguments), "outcome")
            assert first["status"] == "UNKNOWN"
            action = UUID(first["action_id"])
            fresh = await execute_handle(worker, run, fence=await fence_of(app_conn, run))
            investigate = await read_handle(
                worker, read_run, await investigate_job(app_conn, read_run), await lease_for(worker, read_run)
            )
            unrelated = await recover_handle(app_conn, worker, bare, "timeout")
            calls = Calls(monkeypatch)
            for tool in ("get_incident_receipt", "abort_incident"):
                assert_refused(await call(url, token, fresh, tool, arguments))  # execute jobs never look up
                assert_refused(await call(url, token, investigate, tool, arguments))  # nor do read jobs
            for tool in WRITE_TOOLS:  # an APPROVED run is in no recover state: refused, and nothing is created
                assert_refused(await call(url, token, unrelated, tool, {"proposal_id": str(bare_proposal)}))
            assert calls.made == []  # every refusal came before any destination call
            recover = await recover_handle(app_conn, worker, run, "timeout")
            cur = await app_conn.execute(COUNTS)
            before, keys = dict(await cur.fetchone() or {}), await keys_total(incident_conn)
            await arm(sim, own, "delay_receipt")
            delayed = data(await call(url, token, recover, "get_incident_receipt", arguments), "outcome")
            assert delayed["status"] == "UNKNOWN" and await attempt_states(app_conn, run) == ["INTENT", "SENT"]
            found = data(await call(url, token, recover, "get_incident_receipt", arguments), "ok")
            cur = await app_conn.execute(COUNTS)
            after = dict(await cur.fetchone() or {})
        assert await keys_total(incident_conn) == keys  # the lookups wrote no key at the destination
        assert set(found) == {"status", "action_id", "payload_sha256", "receipt", "tombstone", "reason"}  # minimal
        assert found["status"] == "SUCCEEDED" and UUID(found["action_id"]) == action and found["tombstone"] is None
        assert calls.made == ["get_action", "get_action"]  # a lookup never POSTs
        assert after == before  # no grant, attempt, job or proposal created
        assert await attempt_states(app_conn, run) == ["INTENT", "SENT", "RESOLVED"]
        assert await at_destination(incident_conn, action) == (("COMMITTED", None), 1)
        assert await run_state(app_conn, run) == ("SUCCEEDED", None)
        cur = await app_conn.execute("SELECT count(*) AS n FROM app.execution_grant WHERE run_id = %s", (bare,))
        assert (await cur.fetchone() or {})["n"] == 0
        lines.append(
            "R030: execute, investigate and APPROVED-run (no grant) recover handles refused at the recovery tools;"
            " recover lookup: delay_receipt 404 -> UNKNOWN unrecorded, then SUCCEEDED (minimal outcome); GETs only;"
            " counts unchanged"
        )
    finally:
        for each in (run, bare, read_run):
            await purge_run(app_conn, each)


async def test_the_executing_re_send_returns_the_same_action(
    app_conn: persistence.Conn,
    role_conn: RoleConn,
    incident_conn: persistence.Conn,
    secret: Callable[[str], str],
    monkeypatch: pytest.MonkeyPatch,
    lines: list[str],
) -> None:
    """T47 review note 3, ruling 21: the reply to the first create_incident is lost after commit (UNKNOWN; the run
    stays EXECUTING with the attempt SENT); a fresh handle for the same open execute job re-sends under the same action
    id and the destination's key answers with the one incident."""
    api, worker = await role_conn(Role.API), await role_conn(Role.WORKER)
    _, run, proposal, execute = await approved_run(app_conn, api=api, worker=worker)
    token, own = await worker_token(secret), await write_token(secret)
    arguments = {"proposal_id": str(proposal)}
    try:
        async with write_stack(monkeypatch) as (sim, url):
            await arm(sim, own, "lose_after_commit")
            first = data(await call(url, token, execute, "create_incident", arguments), "outcome")
            action = UUID(first["action_id"])
            assert first["status"] == "UNKNOWN" and await run_state(app_conn, run) == ("EXECUTING", None)
            assert await attempt_states(app_conn, run) == ["INTENT", "SENT"]
            assert await at_destination(incident_conn, action) == (("COMMITTED", None), 1)
            calls = Calls(monkeypatch)
            fresh = await execute_handle(worker, run, fence=await fence_of(app_conn, run))
            second = data(await call(url, token, fresh, "create_incident", arguments), "ok")
        assert second["status"] == "SUCCEEDED" and UUID(second["action_id"]) == action
        assert calls.made == ["post_incident"]  # the same key re-sent once
        assert await at_destination(incident_conn, action) == (("COMMITTED", None), 1)  # no second incident
        cur = await app_conn.execute("SELECT count(*) AS n FROM app.execution_grant WHERE run_id = %s", (run,))
        assert (await cur.fetchone() or {})["n"] == 1
        assert await attempt_states(app_conn, run) == ["INTENT", "SENT", "RESOLVED"]
        lines.append("re-send (review note 3): lose_after_commit -> UNKNOWN; fresh execute handle -> same action_id")
    finally:
        await purge_run(app_conn, run)


async def test_a_foreign_receipt_hash_is_a_conflict_the_lookup_replays(
    app_conn: persistence.Conn,
    role_conn: RoleConn,
    secret: Callable[[str], str],
    monkeypatch: pytest.MonkeyPatch,
    lines: list[str],
) -> None:
    """Ruling 19: the destination answers the send with another payload hash; mcp-write records CONFLICT (the run
    ESCALATED), never success; a recover job's lookup then answers the stored CONFLICT without asking again, and its
    abort is refused (the attempt is resolved)."""
    api, worker = await role_conn(Role.API), await role_conn(Role.WORKER)
    _, run, proposal, execute = await approved_run(app_conn, api=api, worker=worker)
    token, own = await worker_token(secret), await write_token(secret)
    arguments = {"proposal_id": str(proposal)}
    try:
        async with write_stack(monkeypatch) as (sim, url):
            await arm(sim, own, "receipt_hash_mismatch")
            sent = data(await call(url, token, execute, "create_incident", arguments), "outcome")
            assert sent["status"] == "CONFLICT" and await run_state(app_conn, run) == ("ESCALATED", "conflict")
            recover = await recover_handle(app_conn, worker, run, "timeout")
            calls = Calls(monkeypatch)
            looked = data(await call(url, token, recover, "get_incident_receipt", arguments), "outcome")
            assert_refused(await call(url, token, recover, "abort_incident", arguments))
        assert looked["status"] == "CONFLICT" and looked["action_id"] == sent["action_id"]
        assert calls.made == []  # the stored outcome; the destination is not asked again
        assert await attempt_states(app_conn, run) == ["INTENT", "SENT", "RESOLVED"]
        lines.append("receipt_hash_mismatch -> CONFLICT (ESCALATED); recover lookup replays it, no call; abort refused")
    finally:
        await purge_run(app_conn, run)


async def test_a_rate_limited_send_is_aborted_once_cancelled(
    app_conn: persistence.Conn,
    role_conn: RoleConn,
    incident_conn: persistence.Conn,
    secret: Callable[[str], str],
    monkeypatch: pytest.MonkeyPatch,
    lines: list[str],
) -> None:
    """Rulings 3 and 19, SA:242 and SA:248: the send meets a rate limit (UNKNOWN; nothing at the destination); the
    lookup finds no key (UNKNOWN); an abort before a cancel or the deadline is refused ABORT_NOT_DUE; after a cancel
    the abort goes at once (`deadline`) and the fresh tombstone ends the run FAILED with `aborted_no_commit`. The
    recovery calls create no grant, attempt, job or proposal, and the destination gains exactly one key: the abort's
    tombstone (round 1, M5)."""
    api, worker = await role_conn(Role.API), await role_conn(Role.WORKER)
    _, run, proposal, execute = await approved_run(app_conn, api=api, worker=worker)
    token, own = await worker_token(secret), await write_token(secret)
    arguments = {"proposal_id": str(proposal)}
    try:
        async with write_stack(monkeypatch) as (sim, url):
            await arm(sim, own, "rate_limit")
            sent = data(await call(url, token, execute, "create_incident", arguments), "outcome")
            action = UUID(sent["action_id"])
            assert sent["status"] == "UNKNOWN" and await at_destination(incident_conn, action) == (None, 0)
            recover = await recover_handle(app_conn, worker, run, "timeout")
            cur = await app_conn.execute(COUNTS)
            before, keys = dict(await cur.fetchone() or {}), await keys_total(incident_conn)
            looked = data(await call(url, token, recover, "get_incident_receipt", arguments), "outcome")
            assert looked["status"] == "UNKNOWN"  # 404: no key, which is never a no-commit (SA:269)
            assert await keys_total(incident_conn) == keys  # the lookup wrote none, so the later +1 is the tombstone
            early = error(await call(url, token, recover, "abort_incident", arguments))
            assert early["code"] == "ABORT_NOT_DUE" and early["retryable"] is True
            assert await attempt_states(app_conn, run) == ["INTENT", "SENT"]
            await cancel(api, run)
            aborted = data(await call(url, token, recover, "abort_incident", arguments), "outcome")
            cur = await app_conn.execute(COUNTS)
            after = dict(await cur.fetchone() or {})
        assert after == before and await keys_total(incident_conn) == keys + 1  # the tombstone, nothing else
        assert aborted["outcome"] == "FAILED_NO_COMMIT" and aborted["receipt"] is None
        assert aborted["tombstone"]["state"] == "ABORTED" and aborted["tombstone"]["reason"] == "deadline"
        assert await run_state(app_conn, run) == ("FAILED", "aborted_no_commit")
        assert await attempt_states(app_conn, run) == ["INTENT", "SENT", "ABORT_REQUESTED", "RESOLVED"]
        assert await at_destination(incident_conn, action) == (("ABORTED", "deadline"), 0)
        lines.append(
            "rate_limit -> UNKNOWN; lookup 404 -> UNKNOWN; abort not due refused; cancel -> abort 'deadline' ->"
            " FAILED aborted_no_commit; grant/attempt/job/proposal counts unchanged around the lookup and the abort;"
            " the destination gained only the tombstone"
        )
    finally:
        await purge_run(app_conn, run)


async def test_a_cancel_before_send_ends_in_the_destinations_tombstone(
    app_conn: persistence.Conn,
    role_conn: RoleConn,
    incident_conn: persistence.Conn,
    secret: Callable[[str], str],
    monkeypatch: pytest.MonkeyPatch,
    lines: list[str],
) -> None:
    """Ruling 24, SA:348: the grant committed (INTENT), then a cancel; create_incident's mark_sent answers `cancelled`,
    and the tool itself requests the abort, POSTs it and records the tombstone: FAILED, `cancelled_before_send`;
    nothing is ever POSTed to /internal/incidents."""
    api, worker, mcp_exec = await role_conn(Role.API), await role_conn(Role.WORKER), await role_conn(Role.MCP_EXEC)
    _, run, proposal, execute = await approved_run(app_conn, api=api, worker=worker)
    token = await worker_token(secret)
    try:
        grant = await persistence.grant_execution(mcp_exec, handle=execute, azp=AZP, proposal_id=proposal)
        await cancel(api, run)
        async with write_stack(monkeypatch) as (_, url):
            calls = Calls(monkeypatch)
            ended = data(await call(url, token, execute, "create_incident", {"proposal_id": str(proposal)}), "outcome")
        assert ended["status"] == "FAILED_NO_COMMIT" and ended["reason"] == "cancelled_before_send"
        assert UUID(ended["action_id"]) == grant.action_id and ended["tombstone"]["reason"] == "cancelled_before_send"
        assert calls.made == ["post_abort"]
        assert await run_state(app_conn, run) == ("FAILED", "cancelled_before_send")
        assert await attempt_states(app_conn, run) == ["INTENT", "ABORT_REQUESTED", "RESOLVED"]
        assert await at_destination(incident_conn, grant.action_id) == (("ABORTED", "cancelled_before_send"), 0)
        lines.append("cancel before send: create_incident -> abort -> FAILED_NO_COMMIT cancelled_before_send; no POST")
    finally:
        await purge_run(app_conn, run)


async def test_a_send_past_the_dispatch_deadline_ends_expired(
    app_conn: persistence.Conn,
    role_conn: RoleConn,
    incident_conn: persistence.Conn,
    secret: Callable[[str], str],
    monkeypatch: pytest.MonkeyPatch,
    lines: list[str],
) -> None:
    """Rulings 17 and 24: the grant at t0, the test clock 400 s on (past the 300 s deadline; reset in `finally`); a
    fresh handle under a fresh lease; create_incident aborts instead of sending: FAILED, `expired`."""
    api, worker = await role_conn(Role.API), await role_conn(Role.WORKER)
    mcp_exec, harness = await role_conn(Role.MCP_EXEC), await role_conn(Role.TEST_HARNESS)
    _, run, proposal, execute = await approved_run(app_conn, api=api, worker=worker)
    token = await worker_token(secret)
    try:
        grant = await persistence.grant_execution(mcp_exec, handle=execute, azp=AZP, proposal_id=proposal)
        try:
            await harness.execute(LATE)
            fresh = await execute_handle(worker, run)  # the first lease lapsed with the clock
            async with write_stack(monkeypatch) as (_, url):
                calls = Calls(monkeypatch)
                ended = data(
                    await call(url, token, fresh, "create_incident", {"proposal_id": str(proposal)}), "outcome"
                )
        finally:
            await harness.execute(NOW)
        # The harness may write the clock but not read it (AM-20.2), so the superuser reads the reset back.
        cur = await app_conn.execute("SELECT clock_offset = interval '0' AS reset FROM app.test_clock")
        reset = bool((await cur.fetchone() or {}).get("reset"))
        assert reset  # the global offset is back at zero for every later test
        assert ended["status"] == "FAILED_NO_COMMIT" and ended["reason"] == "expired"
        assert UUID(ended["action_id"]) == grant.action_id and calls.made == ["post_abort"]
        assert await run_state(app_conn, run) == ("FAILED", "expired")
        assert await attempt_states(app_conn, run) == ["INTENT", "ABORT_REQUESTED", "RESOLVED"]
        assert await at_destination(incident_conn, grant.action_id) == (("ABORTED", "expired"), 0)
        lines.append("past the dispatch deadline: create_incident -> abort -> FAILED_NO_COMMIT expired; no POST")
    finally:
        await purge_run(app_conn, run)


async def test_a_re_queued_execute_job_at_an_abort_request_parks_the_run(
    app_conn: persistence.Conn,
    role_conn: RoleConn,
    incident_conn: persistence.Conn,
    secret: Callable[[str], str],
    monkeypatch: pytest.MonkeyPatch,
    lines: list[str],
) -> None:
    """Final review I1: the grant committed, then a cancel, then the abort request committed (ABORT_REQUESTED,
    `cancelled_before_send`) and mcp-write stopped before the abort POST and the record, as a crash or a database
    error leaves it; the worker re-queues the execute job. Its fresh handle is answered UNKNOWN with no destination
    call and nothing written, and the worker's mark_unknown then parks the run in OUTCOME_UNKNOWN with a recover
    job, where T22 picks it up. Before the fix the handle was refused, the job closed and the run stranded."""
    api, worker, mcp_exec = await role_conn(Role.API), await role_conn(Role.WORKER), await role_conn(Role.MCP_EXEC)
    _, run, proposal, execute = await approved_run(app_conn, api=api, worker=worker)
    token = await worker_token(secret)
    try:
        grant = await persistence.grant_execution(mcp_exec, handle=execute, azp=AZP, proposal_id=proposal)
        await cancel(api, run)
        reason = await persistence.request_abort(mcp_exec, handle=execute, azp=AZP, action_id=grant.action_id)
        assert reason == "cancelled_before_send"  # committed; its POST and its record never happen
        fresh = await execute_handle(worker, run, fence=await fence_of(app_conn, run))  # the re-queued job's
        cur = await app_conn.execute(COUNTS)
        before, keys = dict(await cur.fetchone() or {}), await keys_total(incident_conn)
        async with write_stack(monkeypatch) as (_, url):
            calls = Calls(monkeypatch)
            answered = data(await call(url, token, fresh, "create_incident", {"proposal_id": str(proposal)}), "outcome")
        cur = await app_conn.execute(COUNTS)
        after = dict(await cur.fetchone() or {})
        assert answered["status"] == "UNKNOWN" and UUID(answered["action_id"]) == grant.action_id
        assert calls.made == []  # no incident POST, no abort POST, no lookup
        assert after == before and await keys_total(incident_conn) == keys  # nothing written here or at the destination
        assert await at_destination(incident_conn, grant.action_id) == (None, 0)
        assert await attempt_states(app_conn, run) == ["INTENT", "ABORT_REQUESTED"]
        assert await run_state(app_conn, run) == ("EXECUTING", None)
        # What the worker's execute handler does with that UNKNOWN (handlers._mark_unknown), at the job's own fence.
        unknown = await persistence.mark_unknown(worker, run, await fence_of(app_conn, run))
        assert unknown.state.value == "OUTCOME_UNKNOWN"
        cur = await app_conn.execute(
            "SELECT dedup_key FROM app.jobs WHERE run_id = %s AND type = 'recover' AND done_at IS NULL", (run,)
        )
        assert [row["dedup_key"] for row in await cur.fetchall()] == [f"{grant.action_id}:timeout"]
        assert await run_state(app_conn, run) == ("OUTCOME_UNKNOWN", None)
        lines.append(
            "I1: abort requested (cancelled_before_send), outcome never recorded; the re-queued execute job's"
            " create_incident -> UNKNOWN, no destination call, counts and keys unchanged; mark_unknown ->"
            " OUTCOME_UNKNOWN with a recover job"
        )
    finally:
        await purge_run(app_conn, run)


async def test_a_redispatch_outside_executing_sends_nothing(
    app_conn: persistence.Conn,
    role_conn: RoleConn,
    incident_conn: persistence.Conn,
    secret: Callable[[str], str],
    monkeypatch: pytest.MonkeyPatch,
    lines: list[str],
) -> None:
    """Rulings 6 and 20: the grant committed (INTENT), then the worker's mark_unknown (OUTCOME_UNKNOWN, the fence
    bumped, a recover job queued). The recover job's create_incident passes the allowlist (INTENT) and is refused by
    mark_sent's EXECUTING guard: the plain STALE_RUN, nothing sent (redispatch from OUTCOME_UNKNOWN is T22's). Its abort
    is not due until a cancel, then ends the run FAILED with `cancelled_before_send`."""
    api, worker, mcp_exec = await role_conn(Role.API), await role_conn(Role.WORKER), await role_conn(Role.MCP_EXEC)
    _, run, proposal, execute = await approved_run(app_conn, api=api, worker=worker)
    token = await worker_token(secret)
    arguments = {"proposal_id": str(proposal)}
    try:
        grant = await persistence.grant_execution(mcp_exec, handle=execute, azp=AZP, proposal_id=proposal)
        unknown = await persistence.mark_unknown(worker, run, await fence_of(app_conn, run))
        assert unknown.state.value == "OUTCOME_UNKNOWN"
        cur = await app_conn.execute("SELECT id FROM app.jobs WHERE run_id = %s AND type = 'recover'", (run,))
        job = UUID(str((await cur.fetchone() or {})["id"]))  # mark_unknown's own recover job (<action>:timeout)
        async with worker.transaction():
            recover = await persistence.mint_handle(
                worker, run_id=run, job_id=job, server=Server.WRITE, azp=AZP, fence=unknown.fence
            )
        async with write_stack(monkeypatch) as (_, url):
            calls = Calls(monkeypatch)
            stale = error(await call(url, token, recover, "create_incident", arguments))
            early = error(await call(url, token, recover, "abort_incident", arguments))
            await cancel(api, run)
            aborted = data(await call(url, token, recover, "abort_incident", arguments), "outcome")
        assert stale["code"] == "STALE_RUN" and early["code"] == "ABORT_NOT_DUE"
        assert aborted["outcome"] == "FAILED_NO_COMMIT" and aborted["tombstone"]["reason"] == "cancelled_before_send"
        assert calls.made == ["post_abort"]  # nothing was ever sent to /internal/incidents
        assert await run_state(app_conn, run) == ("FAILED", "cancelled_before_send")
        assert await attempt_states(app_conn, run) == ["INTENT", "ABORT_REQUESTED", "RESOLVED"]
        assert await at_destination(incident_conn, grant.action_id) == (("ABORTED", "cancelled_before_send"), 0)
        lines.append(
            "recover create_incident on INTENT in OUTCOME_UNKNOWN -> STALE_RUN, nothing sent; abort not due, then"
            " cancel -> FAILED_NO_COMMIT cancelled_before_send"
        )
    finally:
        await purge_run(app_conn, run)

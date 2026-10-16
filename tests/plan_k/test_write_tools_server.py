"""mcp-write's three tools in-process, through the guard and the SDK's bearer auth, with the definers and the work
replaced (Plan K rulings 1, 9, 10, 20 and 26).

Catches: a tool missing from the list or listed with a schema other than its `schemas/tools/` contract (an extra
argument accepted, SA:350); a tool that does its work before resolving the handle, or resolves it for another tool's
allowlist; a call without a handle that reaches anything; a refused handle, a premature abort or a stale run answered
with an action id; the worker's `azp` not handed to the work; envelopes for the recovery tools that do not validate
against `schemas/tool-result.schema.json` for every outcome (the abort's UNKNOWN and CONFLICT included), or `ok`
around anything but SUCCEEDED (R083).
"""

import json
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import MappingProxyType
from typing import Any
from uuid import UUID

import httpx2
import pytest
from jsonschema import Draft202012Validator, FormatChecker
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from ops_core import persistence
from ops_core.jobs import Tool
from ops_core.outcomes import ActionOutcome, ToolOutcome
from ops_core.tokens import Principal, TokenRejected
from ops_mcp_write import destination, execution, server

from tests.plan_k.test_recovery_tools import ACTION, PROPOSAL, SHA, committed, tombstone

ISSUER = "http://localhost:18080/realms/ops-dev"
RESOURCE = "http://mcp-write:8082/mcp"
BASE = "http://127.0.0.1:8082"
WRITE_TOOLS = ("create_incident", "get_incident_receipt", "abort_incident")
TOOL_RESULT = Draft202012Validator(
    json.loads(Path("schemas/tool-result.schema.json").read_text(encoding="utf-8")), format_checker=FormatChecker()
)


class WriteVerifier:
    """'good' is the worker's token for this server; anything else is refused, as a real verifier would."""

    @property
    def ready(self) -> bool:
        return True

    async def load_keys(self) -> None:
        return None

    async def verify_async(self, token: str) -> Principal:
        if token != "good":
            raise TokenRejected("unit test")
        claims = MappingProxyType({"iss": ISSUER, "typ": "Bearer"})
        return Principal("subject", "ops-worker", (RESOURCE, "account"), int(time.time()) + 300, claims)


class IdleConn:
    async def close(self) -> None:
        return None


class FakeSession:
    @asynccontextmanager
    async def unit(self, tenant_id: Any = None) -> AsyncIterator[object]:
        yield object()


def write_app() -> Any:
    session: Any = FakeSession()
    token: Any = None
    http: Any = httpx2.AsyncClient()
    deps = execution.Deps(session=session, http=http, destination_url="http://127.0.0.1:9", destination_token=token)
    state = server.State(deps=deps, verifier=WriteVerifier())
    idle: Any = IdleConn()
    deps.session.conn = idle  # the lifespan closes it at shutdown
    return server.build_app(server.build_server(state, issuer=ISSUER, resource_url=RESOURCE), state)


@asynccontextmanager
async def client(app: Any, handle: str | None = "a-handle") -> AsyncIterator[Client]:
    """The SDK's own client pinned to 2026-07-28 over an in-process transport, with the app's lifespan running."""
    headers = {"Authorization": "Bearer good"} | ({} if handle is None else {"X-Ops-Invocation": handle})
    async with app.router.lifespan_context(app):
        transport = httpx2.ASGITransport(app=app)
        async with (
            httpx2.AsyncClient(transport=transport, base_url=BASE, headers=headers) as http,
            Client(streamable_http_client(f"{BASE}/mcp", http_client=http), mode="2026-07-28") as mcp,
        ):
            yield mcp


def outcome(status: ToolOutcome) -> ActionOutcome:
    reply = {
        ToolOutcome.SUCCEEDED: committed(),
        ToolOutcome.FAILED_NO_COMMIT: tombstone("ABORTED", "deadline"),
        ToolOutcome.CONFLICT: committed(sha="d" * 64),
        ToolOutcome.UNKNOWN: None,
    }[status]
    return destination.classify(reply, action_id=ACTION, payload_sha256=SHA)


@pytest.mark.asyncio
async def test_the_three_tools_are_listed_with_their_contract_schemas() -> None:
    async with client(write_app()) as mcp:
        tools = {t.name: t.input_schema for t in (await mcp.list_tools()).tools}
        extras = [await mcp.call_tool(name, {"proposal_id": str(PROPOSAL), "reason": "deadline"}) for name in tools]
    assert sorted(tools) == sorted(WRITE_TOOLS)
    for name, schema in tools.items():
        contract = json.loads(Path(f"schemas/tools/{name}.input.schema.json").read_text(encoding="utf-8"))
        assert schema["additionalProperties"] is False and schema["required"] == contract["required"] == ["proposal_id"]
        assert schema["properties"]["proposal_id"]["format"] == "uuid", name
    assert all(result.is_error for result in extras)  # a reason, a tenant or an approval is never an argument (SA:350)


@pytest.mark.asyncio
async def test_without_a_handle_nothing_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    resolved: list[Tool] = []

    async def resolve(_conn: Any, **kwargs: Any) -> None:
        resolved.append(kwargs["tool"])

    monkeypatch.setattr(persistence, "resolve_invocation", resolve)
    async with client(write_app(), handle=None) as mcp:
        results = [await mcp.call_tool(name, {"proposal_id": str(PROPOSAL)}) for name in WRITE_TOOLS]
    for name, result in zip(WRITE_TOOLS, results, strict=True):
        doc = result.structured_content
        assert not result.is_error and isinstance(doc, dict) and doc["tool_name"] == name
        assert doc["error"] == {"code": "INVALID_HANDLE", "message": "missing invocation handle", "retryable": False}
    assert resolved == []


@pytest.mark.asyncio
async def test_each_tool_resolves_its_own_allowlist_first_and_hands_the_token_azp_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []

    async def resolve(_conn: Any, **kwargs: Any) -> None:
        assert kwargs["azp"] == "ops-worker" and kwargs["handle"] == "a-handle"
        order.append(f"resolve:{kwargs['tool'].value}")

    def work(name: str, status: ToolOutcome) -> Any:
        async def run(_deps: Any, **kwargs: Any) -> ActionOutcome:
            assert kwargs["azp"] == "ops-worker" and kwargs["proposal_id"] == PROPOSAL
            order.append(f"work:{name}")
            return outcome(status)

        return run

    monkeypatch.setattr(persistence, "resolve_invocation", resolve)
    monkeypatch.setattr(execution, "create_incident", work("create_incident", ToolOutcome.SUCCEEDED))
    monkeypatch.setattr(execution, "get_incident_receipt", work("get_incident_receipt", ToolOutcome.UNKNOWN))
    monkeypatch.setattr(execution, "abort_incident", work("abort_incident", ToolOutcome.FAILED_NO_COMMIT))
    async with client(write_app()) as mcp:
        docs = [(await mcp.call_tool(name, {"proposal_id": str(PROPOSAL)})).structured_content for name in WRITE_TOOLS]
    assert order == [f"{step}:{name}" for name in WRITE_TOOLS for step in ("resolve", "work")]
    assert [d["status"] for d in docs if isinstance(d, dict)] == ["ok", "outcome", "outcome"]
    for doc in docs:
        TOOL_RESULT.validate(doc)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raised", "code", "retryable"),
    [
        (persistence.HandleRejected("invocation handle rejected"), "INVALID_HANDLE", False),
        (persistence.Refused("ABORT_NOT_DUE"), "ABORT_NOT_DUE", True),
        (persistence.Refused("OTHER_PROPOSAL"), "GRANT_REFUSED", False),
        (persistence.VersionConflict("run is OUTCOME_UNKNOWN"), "STALE_RUN", False),
        (persistence.Refused("NOT_REDISPATCHABLE"), "NOT_REDISPATCHABLE", False),
    ],
    ids=["handle", "not-due", "other-proposal", "stale-run", "not-redispatchable"],
)
async def test_a_refusal_before_the_destination_is_a_plain_error(
    monkeypatch: pytest.MonkeyPatch, raised: Exception, code: str, retryable: bool
) -> None:
    async def resolve(_conn: Any, **_: Any) -> None:
        return None

    async def refuse(_deps: Any, **_: Any) -> ActionOutcome:
        raise raised

    monkeypatch.setattr(persistence, "resolve_invocation", resolve)
    for name in WRITE_TOOLS:
        monkeypatch.setattr(execution, name, refuse)
    async with client(write_app()) as mcp:
        docs = [(await mcp.call_tool(name, {"proposal_id": str(PROPOSAL)})).structured_content for name in WRITE_TOOLS]
    for doc in docs:
        assert isinstance(doc, dict) and doc["status"] == "error" and doc["data"] is None
        assert doc["error"]["code"] == code and doc["error"]["retryable"] is retryable
        assert "action_id" not in json.dumps(doc)  # a refusal never names the action (SA:355)
        TOOL_RESULT.validate(doc)


@pytest.mark.parametrize("status", list(ToolOutcome))
def test_the_recovery_envelopes_follow_the_tool_result_contract(status: ToolOutcome) -> None:
    receipt = server.outcome_envelope(outcome(status), Tool.GET_INCIDENT_RECEIPT.value)
    aborted = server.abort_envelope(outcome(status))
    for doc in (receipt, aborted):
        TOOL_RESULT.validate(doc)
        assert doc["status"] == ("ok" if status is ToolOutcome.SUCCEEDED else "outcome") and doc["error"] is None
    assert receipt["tool_name"] == "get_incident_receipt" and receipt["data"]["status"] == status.value
    assert aborted["tool_name"] == "abort_incident" and aborted["data"]["outcome"] == status.value
    assert set(aborted["data"]) == {"action_id", "outcome", "receipt", "tombstone"}  # SA:356, nothing else
    assert aborted["data"]["action_id"] == str(ACTION)
    if status is ToolOutcome.FAILED_NO_COMMIT:
        assert aborted["data"]["tombstone"]["reason"] == "deadline"  # the destination's own token (ruling 10)


def test_the_abort_example_carries_the_destinations_token() -> None:
    example = json.loads(Path("schemas/examples/tool-abort_incident-valid.json").read_text(encoding="utf-8"))
    TOOL_RESULT.validate(example)
    assert example["data"]["tombstone"]["reason"] == "cancelled_before_send"


def test_an_ok_abort_envelope_around_anything_but_success_is_refused_by_the_contract() -> None:
    doc = server.abort_envelope(outcome(ToolOutcome.UNKNOWN))
    doc["status"] = "ok"
    assert not TOOL_RESULT.is_valid(doc)  # R083's probe, for the abort's added outcomes
    stray = server.abort_envelope(outcome(ToolOutcome.CONFLICT))
    stray["data"]["receipt"] = committed().document["receipt"]
    assert not TOOL_RESULT.is_valid(stray)  # UNKNOWN and CONFLICT carry neither a receipt nor a tombstone


def test_an_abort_not_due_is_retryable_and_names_no_action() -> None:
    error = server.refusal_error("ABORT_NOT_DUE")
    assert error["code"] == "ABORT_NOT_DUE" and error["retryable"] is True
    assert str(UUID(int=21)) not in json.dumps(error)

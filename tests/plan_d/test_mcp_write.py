"""mcp-write without a network (AM-13 attempt protocol, AM-80 envelope rules, review focus 1).

Catches: a receipt accepted without checking its action id and hash (SA:358 says a mismatch is CONFLICT), a transport
failure reported as "no effect" instead of UNKNOWN (BUILD_SPEC §1), an ABORTED tombstone mapped to the wrong reason, a
replay that would send a second POST after the outcome was recorded, an envelope with status=ok around an UNKNOWN
outcome (R083), and a tool schema that accepts an extra argument.
"""

import json
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from mcp import Client
from ops_core.outcomes import ToolOutcome
from ops_core.states import Reason
from ops_core.tokens import Principal, TokenRejected
from ops_mcp_write import destination, execution, server

ACTION = UUID(int=11)
SHA = "a" * 64
RECEIPT = {"receipt_id": str(UUID(int=12)), "incident_id": "INC-000007", "committed_at": "2026-10-08T12:00:00Z"}
TOOL_RESULT = Draft202012Validator(
    json.loads(Path("schemas/tool-result.schema.json").read_text(encoding="utf-8")), format_checker=FormatChecker()
)
INPUT = json.loads(Path("schemas/tools/create_incident.input.schema.json").read_text(encoding="utf-8"))


def committed(action: UUID = ACTION, sha: str = SHA) -> destination.Reply:
    return destination.Reply(
        200, {"state": "COMMITTED", "action_id": str(action), "payload_sha256": sha, "receipt": RECEIPT}
    )


def test_classify_succeeded_only_when_identity_and_hash_match():
    ok = destination.classify(committed(), action_id=ACTION, payload_sha256=SHA)
    assert ok.status is ToolOutcome.SUCCEEDED and ok.receipt is not None and ok.receipt.incident_id == "INC-000007"
    other_action = destination.classify(committed(action=UUID(int=99)), action_id=ACTION, payload_sha256=SHA)
    other_hash = destination.classify(committed(sha="b" * 64), action_id=ACTION, payload_sha256=SHA)
    assert other_action.status is ToolOutcome.CONFLICT and other_hash.status is ToolOutcome.CONFLICT


def test_classify_conflict_unknown_and_tombstones():
    conflict = destination.Reply(409, {"state": "CONFLICT", "action_id": str(ACTION), "payload_sha256": "b" * 64})
    assert destination.classify(conflict, action_id=ACTION, payload_sha256=SHA).status is ToolOutcome.CONFLICT
    assert destination.classify(None, action_id=ACTION, payload_sha256=SHA).status is ToolOutcome.UNKNOWN
    assert destination.classify(destination.Reply(500, {}), action_id=ACTION, payload_sha256=SHA).status is (
        ToolOutcome.UNKNOWN
    )
    broken = destination.Reply(
        200, {"state": "COMMITTED", "action_id": str(ACTION), "payload_sha256": SHA, "receipt": {"receipt_id": "nope"}}
    )
    assert destination.classify(broken, action_id=ACTION, payload_sha256=SHA).status is ToolOutcome.UNKNOWN
    for state, reason in (("REJECTED", Reason.REJECTED), ("ABORTED", Reason.ABORTED_NO_COMMIT)):
        tomb = destination.Reply(
            200,
            {
                "state": state,
                "action_id": str(ACTION),
                "payload_sha256": SHA,
                "tombstone": {
                    "action_id": str(ACTION),
                    "state": state,
                    "payload_sha256": SHA,
                    "reason": "policy",
                    "decided_at": "2026-10-08T12:00:00Z",
                },
            },
        )
        out = destination.classify(tomb, action_id=ACTION, payload_sha256=SHA)
        assert out.status is ToolOutcome.FAILED_NO_COMMIT and out.reason is reason and out.tombstone is not None


@pytest.mark.parametrize("status", list(ToolOutcome))
def test_outcome_envelopes_follow_the_tool_result_contract(status: ToolOutcome):
    reply = {
        ToolOutcome.SUCCEEDED: committed(),
        ToolOutcome.CONFLICT: destination.Reply(
            409, {"state": "CONFLICT", "action_id": str(ACTION), "payload_sha256": "b" * 64}
        ),
        ToolOutcome.UNKNOWN: None,
        ToolOutcome.FAILED_NO_COMMIT: destination.Reply(
            200,
            {
                "state": "REJECTED",
                "action_id": str(ACTION),
                "payload_sha256": SHA,
                "tombstone": {
                    "action_id": str(ACTION),
                    "state": "REJECTED",
                    "payload_sha256": SHA,
                    "reason": "policy",
                    "decided_at": "2026-10-08T12:00:00Z",
                },
            },
        ),
    }[status]
    outcome = destination.classify(reply, action_id=ACTION, payload_sha256=SHA)
    doc = server.outcome_envelope(outcome)
    TOOL_RESULT.validate(doc)
    assert doc["status"] == ("ok" if status is ToolOutcome.SUCCEEDED else "outcome")
    assert doc["data"]["status"] == status.value and doc["data"]["action_id"] == str(ACTION)
    err = server.envelope("create_incident", error=server.tool_error("INVALID_HANDLE", "x"))
    TOOL_RESULT.validate(err)
    assert "action_id" not in json.dumps(err)  # SA:357: an error before any grant never names an action


def test_next_step_replays_without_a_second_send_once_resolved():
    assert execution.next_step("RESOLVED") == "stored"
    assert execution.next_step("INTENT") == "send"
    assert execution.next_step("SENT") == "resend"
    with pytest.raises(ValueError):
        execution.next_step("ABORT_REQUESTED")  # T22 territory; the skeleton refuses to guess


class StubVerifier:
    @property
    def ready(self) -> bool:
        return True

    async def load_keys(self) -> None:
        return None

    async def verify_async(self, token: str) -> Principal:
        raise TokenRejected("unit test")


@pytest.mark.asyncio
async def test_tool_schema_matches_the_contract_and_rejects_extras():
    state = server.State(deps=None, verifier=StubVerifier())
    mcp = server.build_server(
        state, issuer="http://localhost:18080/realms/ops-dev", resource_url="http://mcp-write:8082/mcp"
    )
    async with Client(mcp) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        assert set(tools) == {"create_incident"}
        schema: dict[str, Any] = tools["create_incident"].input_schema
        assert schema["additionalProperties"] is False and schema["required"] == INPUT["required"]
        assert schema["properties"]["proposal_id"]["format"] == "uuid"
        extra = await client.call_tool("create_incident", {"proposal_id": str(UUID(int=1)), "approved": True})
        assert extra.is_error
        res = await client.call_tool("create_incident", {"proposal_id": str(UUID(int=1))})
        assert not res.is_error and res.structured_content["status"] == "error"

"""`ops_core.tool_contracts` (Plan M ruling 13): the committed schemas at run time.

Catches: an input schema that is not the committed file, or a cached one a caller can change for everyone after it;
a comparison that is fooled by key order or accepts a changed bound or a float where the file has an integer; a
result validator that checks only the envelope (BS:399: nested data too), accepts another tool's envelope, or puts a
value from the document into its message; and an instant that is not RFC 3339 accepted because jsonschema's
`date-time` check is silently off without rfc3339-validator (a runtime dependency of ops-core since T16).
"""

import json
import tomllib
from pathlib import Path

import pytest
from ops_core import tool_contracts
from ops_core.jobs import Tool

READ = (Tool.GET_ASSET_STATUS, Tool.GET_RECENT_ALERTS, Tool.SEARCH_PROCEDURES)
EXAMPLES = Path("schemas/examples")


@pytest.mark.parametrize("tool", READ)
def test_the_input_schema_is_the_committed_file(tool: Tool) -> None:
    committed = json.loads(Path(f"schemas/tools/{tool.value}.input.schema.json").read_text(encoding="utf-8"))
    served = tool_contracts.input_schema(tool)
    assert served == committed and tool_contracts.same_input_schema(tool, committed)
    served["properties"].clear()  # a caller's copy: the next caller still gets the file
    assert tool_contracts.input_schema(tool) == committed
    reordered = json.loads(json.dumps(committed, sort_keys=True))
    assert tool_contracts.same_input_schema(tool, reordered)  # canonical JSON: key order does not matter
    loosened = json.loads(json.dumps(committed))
    loosened["additionalProperties"] = True
    assert not tool_contracts.same_input_schema(tool, loosened)


def test_a_changed_bound_or_a_float_is_another_schema() -> None:
    schema = tool_contracts.input_schema(Tool.GET_ASSET_STATUS)
    schema["properties"]["asset_id"]["maxLength"] = 64
    assert not tool_contracts.same_input_schema(Tool.GET_ASSET_STATUS, schema)
    schema["properties"]["asset_id"]["maxLength"] = 32.0  # equal in Python, not in canonical JSON
    assert not tool_contracts.same_input_schema(Tool.GET_ASSET_STATUS, schema)


def test_check_result_validates_the_nested_data_of_the_named_tool() -> None:
    for name in ("tool-get_asset_status-valid.json", "tool-get_recent_alerts-valid.json"):
        doc = json.loads((EXAMPLES / name).read_text(encoding="utf-8"))
        assert tool_contracts.check_result(Tool(doc["tool_name"]), doc) is doc
    status = json.loads((EXAMPLES / "tool-get_asset_status-valid.json").read_text(encoding="utf-8"))
    broken = {**status, "data": {**status["data"], "state": "on fire"}}
    with pytest.raises(tool_contracts.ContractViolation, match="at data/state") as refused:
        tool_contracts.check_result(Tool.GET_ASSET_STATUS, broken)
    assert "on fire" not in str(refused.value)  # the path and the rule, never the value
    with pytest.raises(tool_contracts.ContractViolation, match="names another tool"):
        tool_contracts.check_result(Tool.GET_RECENT_ALERTS, status)
    with pytest.raises(tool_contracts.ContractViolation, match="not an object"):
        tool_contracts.check_result(Tool.GET_ASSET_STATUS, [status])
    outcome = {**status, "status": "outcome"}  # a read tool answers ok or error only (AM-80)
    with pytest.raises(tool_contracts.ContractViolation):
        tool_contracts.check_result(Tool.GET_ASSET_STATUS, outcome)


def test_date_time_is_checked_at_run_time() -> None:
    """The patterns alone would accept a day that does not exist; the format check refuses it, and the package that
    performs it is a runtime dependency of ops-core, not only of the dev group."""
    core = tomllib.loads(Path("core/pyproject.toml").read_text(encoding="utf-8"))
    assert any(d.startswith("rfc3339-validator") for d in core["project"]["dependencies"])
    status = json.loads((EXAMPLES / "tool-get_asset_status-valid.json").read_text(encoding="utf-8"))
    for impossible in ("2026-02-30T00:00:00Z", "2026-10-06T25:00:00Z"):
        with pytest.raises(tool_contracts.ContractViolation, match="at observed_at"):
            tool_contracts.check_result(Tool.GET_ASSET_STATUS, {**status, "observed_at": impossible})

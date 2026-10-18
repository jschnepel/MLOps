"""The committed MCP tool contracts at run time (T16; Plan M rulings 13 and 15; AM-80, BS:399).

Both sides of the read boundary hold the server to the files in `schemas/`, not to what a server says about itself:
mcp-read advertises exactly `schemas/tools/<tool>.input.schema.json` as each tool's input schema and validates what
asset-sim returned as a whole tool result before it answers; the worker compares every advertised read tool's input
schema with the same file (canonical JSON) and validates every read result against `schemas/tool-result.schema.json`
(R029). The schemas are read from the repository's `schemas/` directory, so a process runs from a checkout (packaging
them for a container is T30's). Errors name the failing rule and the JSON path, never a value from the document.
"""

from __future__ import annotations

import copy
import functools
import json
from pathlib import Path
from typing import Any, Final

from jsonschema import Draft202012Validator

from ops_core.canonical import canonical_json
from ops_core.jobs import Tool

SCHEMAS: Final = Path(__file__).resolve().parents[3] / "schemas"
MAX_RESULT_BYTES: Final = 256 * 1024  # ruling 13: a serialized result above this is refused, whatever it holds


class ContractViolation(ValueError):
    """A document does not satisfy its committed contract; the message names the rule and the path only."""


@functools.cache
def _input_schema(tool: Tool) -> dict[str, Any]:
    schema: dict[str, Any] = json.loads((SCHEMAS / "tools" / f"{tool.value}.input.schema.json").read_text("utf-8"))
    return schema


def input_schema(tool: Tool) -> dict[str, Any]:
    """The tool's committed input schema, a fresh copy each call (a caller may hand it to an SDK that keeps it)."""
    return copy.deepcopy(_input_schema(tool))


def same_input_schema(tool: Tool, advertised: object) -> bool:
    """True when `advertised` is the committed input schema of `tool`, compared as canonical JSON (ruling 13)."""
    try:
        return canonical_json(advertised) == canonical_json(_input_schema(tool))
    except ValueError:  # not canonicalisable (a float, a non-string key): not the committed schema either
        return False


@functools.cache
def _result_validator() -> Any:
    schema = json.loads((SCHEMAS / "tool-result.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)


def check_result(tool: Tool, document: object) -> dict[str, Any]:
    """`document` as a tool-result envelope of `tool` that the committed schema accepts, branch and nested data
    included (BS:399).

    Raises:
        ContractViolation: not an object, another tool's envelope, or a schema failure (the first, by path).
    """
    if not isinstance(document, dict):
        raise ContractViolation(f"{tool.value}: the result is not an object")
    if document.get("tool_name") != tool.value:
        raise ContractViolation(f"{tool.value}: the result names another tool")
    errors = sorted(_result_validator().iter_errors(document), key=lambda e: [str(p) for p in e.absolute_path])
    if errors:
        path = "/".join(str(part) for part in errors[0].absolute_path) or "(root)"
        raise ContractViolation(f"{tool.value}: the result fails the contract at {path} ({errors[0].validator})")
    return document

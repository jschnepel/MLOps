"""mcp-read without a network (AM-15 read tools, AM-80 tool-result contract, R131 in miniature).

Catches: an envelope that does not validate against tool-result.schema.json, a rank or other field the contract lacks
leaking into a result, a timestamp not in the contract's spelling, mcp-read reading a corpus from files again instead
of the governed store (T17 retired the fixture corpus; the lifecycle, tenant and ranking cases it used to pin here are
now the definer's, tests/e2e/test_migration_0011_live.py), a tool schema that drifts from schemas/tools/, and an extra
argument such as tenant_id silently ignored (SA:350).
"""

import importlib.util
import inspect
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from mcp import Client
from ops_core import corpus, persistence
from ops_core.tokens import Principal, TokenRejected
from ops_mcp_read import server

ALPHA = UUID("3ea79c95-914c-52cb-9d10-c4e19dda8ff7")
NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
TOOL_RESULT = Draft202012Validator(
    json.loads(Path("schemas/tool-result.schema.json").read_text(encoding="utf-8")), format_checker=FormatChecker()
)
INPUT = json.loads(Path("schemas/tools/search_procedures.input.schema.json").read_text(encoding="utf-8"))


def found_in_corpus(document_id: str, names: tuple[str, ...]) -> persistence.Procedures:
    """What the definer would return for sections of a committed document (their real hashes and offsets)."""
    doc = next(d for d in corpus.load(Path("data/corpus")).documents if d.document_id == document_id)
    hits = tuple(
        persistence.Procedure(
            evidence_id=doc.evidence_id(s),
            document_id=doc.document_id,
            version=doc.version,
            section=s.name,
            content_sha256=s.sha256,
            excerpt=s.body[:500],
            effective_from=doc.effective_from,
            rank=0.5 - i / 10,
        )
        for i, s in enumerate(x for x in doc.sections if x.name in names)
    )
    return persistence.Procedures("corpus-1", hits)


def test_search_response_matches_the_tool_result_contract() -> None:
    found = found_in_corpus("ALPHA-ALERT-REVIEW", ("repeated-alerts", "evidence"))
    doc = server.search_response(found, now=NOW)
    TOOL_RESULT.validate(doc)
    assert doc["status"] == "ok" and doc["data"]["retrieval_mode"] == "lexical"
    assert doc["data"]["corpus_version"] == "corpus-1"
    assert [r["evidence_id"] for r in doc["data"]["results"]] == [
        "ALPHA-ALERT-REVIEW:v1:repeated-alerts",
        "ALPHA-ALERT-REVIEW:v1:evidence",
    ]
    first = doc["data"]["results"][0]
    assert (first["effective_from"], first["retrieved_at"]) == ("2026-09-01T00:00:00Z", "2026-10-16T12:00:00Z")
    assert all("rank" not in r for r in doc["data"]["results"])  # the score stays in the database's answer
    nothing = server.search_response(persistence.Procedures("none", ()), now=NOW)
    TOOL_RESULT.validate(nothing)
    assert nothing["data"] == {"results": [], "retrieval_mode": "lexical", "corpus_version": "none"}
    err = server.envelope("search_procedures", error=server.tool_error("INVALID_HANDLE", "missing invocation handle"))
    TOOL_RESULT.validate(err)
    assert err["status"] == "error" and err["data"] is None


def test_mcp_read_reads_no_corpus_file() -> None:
    assert importlib.util.find_spec("ops_mcp_read.procedures") is None  # T17 retired the in-memory corpus
    source = inspect.getsource(server)
    assert "handoff-fixtures" not in source and "data/corpus" not in source


class StubVerifier:
    @property
    def ready(self) -> bool:
        return True

    async def load_keys(self) -> None:
        return None

    async def verify_async(self, token: str) -> Principal:
        raise TokenRejected("unit test")


@pytest.mark.asyncio
async def test_tool_schema_conforms_to_the_contract_and_rejects_extra_arguments() -> None:
    state = server.State(session=None, verifier=StubVerifier())
    mcp = server.build_server(
        state, issuer="http://localhost:18080/realms/ops-dev", resource_url="http://mcp-read:8081/mcp"
    )
    async with Client(mcp) as client:  # in-process: no HTTP, so no bearer middleware; schema and validation only
        tools = {t.name: t for t in (await client.list_tools()).tools}
        assert set(tools) == {"search_procedures"}
        schema: dict[str, Any] = tools["search_procedures"].input_schema
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(INPUT["required"])
        assert set(schema["properties"]) == set(INPUT["properties"])  # since T17 the optional asset_type too
        assert schema["properties"]["mode"]["enum"] == INPUT["properties"]["mode"]["enum"]
        assert (schema["properties"]["limit"]["minimum"], schema["properties"]["limit"]["maximum"]) == (1, 8)
        assert (schema["properties"]["query"]["minLength"], schema["properties"]["query"]["maxLength"]) == (1, 500)
        asset_type = schema["properties"]["asset_type"]
        assert (asset_type["type"], asset_type["minLength"], asset_type["maxLength"]) == ("string", 1, 40)
        assert "default" not in asset_type  # nothing for a schema-driven client to copy (round 1, M3)
        extra = await client.call_tool(
            "search_procedures", {"query": "x", "limit": 1, "mode": "lexical", "tenant_id": str(ALPHA)}
        )
        assert extra.is_error  # SA:350: an argument that supplies a tenant is rejected, not ignored
        bad = await client.call_tool("search_procedures", {"query": "x", "limit": 9, "mode": "lexical"})
        assert bad.is_error
        for lax in ("1", True):  # lax coercion would accept both as 1
            assert (
                await client.call_tool("search_procedures", {"query": "x", "limit": lax, "mode": "lexical"})
            ).is_error
        for empty in ("", None, "x" * 41):  # the contract's asset_type is a string of 1 to 40 characters
            arguments = {"query": "x", "limit": 1, "mode": "lexical", "asset_type": empty}
            assert (await client.call_tool("search_procedures", arguments)).is_error, empty
        # Without the bearer middleware there is no access token, so the tool body refuses before any lookup.
        res = await client.call_tool("search_procedures", {"query": "x", "limit": 1, "mode": "lexical"})
        assert not res.is_error and res.structured_content["status"] == "error"
        assert res.structured_content["error"]["code"] == "INVALID_HANDLE"

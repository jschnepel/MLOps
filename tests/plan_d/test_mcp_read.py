"""mcp-read without a network (AM-15 read tools, AM-80 tool-result contract, R131 in miniature).

Catches: the per-section hash the tool cites drifting from meta.json (an evidence_ref the proposal cannot prove), a
superseded or draft document served as evidence, beta evidence visible to alpha, a non-deterministic ranking (the same
query giving a different first citation on retry), a tool schema that drifts from schemas/tools/, an extra argument
such as tenant_id silently ignored (SA:350), and an envelope that does not validate against tool-result.schema.json.
"""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from mcp import Client
from ops_core.tokens import Principal, TokenRejected
from ops_mcp_read import procedures, server

FIXTURES = Path("data/handoff-fixtures")
ALPHA = UUID("3ea79c95-914c-52cb-9d10-c4e19dda8ff7")
BETA = UUID("5ab45c2c-1e12-5a0c-a2b9-66cd2ff05201")
NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
TOOL_RESULT = Draft202012Validator(
    json.loads(Path("schemas/tool-result.schema.json").read_text(encoding="utf-8")), format_checker=FormatChecker()
)
INPUT = json.loads(Path("schemas/tools/search_procedures.input.schema.json").read_text(encoding="utf-8"))


def test_section_bodies_hash_exactly_as_meta_json_says():
    meta = json.loads((FIXTURES / "meta.json").read_text(encoding="utf-8"))
    catalog = json.loads((FIXTURES / "catalog.json").read_text(encoding="utf-8"))
    expected = {(s["document_id"], s["version"], s["section"]): s["sha256"] for s in meta["sections"]}
    seen = 0
    for doc in catalog["documents"]:
        bodies = procedures.section_bodies((FIXTURES / doc["path"]).read_text(encoding="utf-8"))
        for name in doc["sections"]:
            assert (
                hashlib.sha256(bodies[name].encode("utf-8")).hexdigest()
                == expected[(doc["document_id"], doc["version"], name)]
            )
            seen += 1
    assert seen == len(expected)


def test_corpus_is_tenant_scoped_and_approved_only():
    alpha = procedures.Corpus.load(FIXTURES, "alpha")
    ids = sorted(s.evidence_id for s in alpha.sections)
    assert ids == [
        "ALPHA-EVIDENCE:v1:quality",
        "ALPHA-INCIDENT:v2:evidence",
        "ALPHA-INCIDENT:v2:review",
        "ALPHA-TRIAGE:v1:limits",
        "ALPHA-TRIAGE:v1:scope",
    ]  # no v1 (superseded), no ALPHA-DRAFT (draft)
    beta = procedures.Corpus.load(FIXTURES, "beta")
    assert {s.document_id for s in beta.sections} == {"BETA-INCIDENT", "BETA-TRIAGE", "BETA-EVIDENCE"}
    assert alpha.corpus_version == "handoff-1"
    review = next(s for s in alpha.sections if s.evidence_id == "ALPHA-INCIDENT:v2:review")
    assert review.content_sha256 == "62a90906c7bb706ae8a968eb0f7102f76b05d2c3be911c182d528a1fd25ef008"
    assert review.effective_from == "2026-10-01T00:00:00Z"
    corpora = procedures.load_corpora(FIXTURES)
    assert set(corpora) == {ALPHA, BETA} and corpora[ALPHA] is not corpora[BETA]


def test_search_is_lexical_deterministic_and_bounded():
    alpha = procedures.Corpus.load(FIXTURES, "alpha")
    hits = alpha.search("a different authorized reviewer must inspect the exact content", limit=3)
    assert hits[0].section.evidence_id == "ALPHA-INCIDENT:v2:review" and len(hits) <= 3
    assert [h.section.evidence_id for h in hits] == [
        h.section.evidence_id
        for h in alpha.search("a different authorized reviewer must inspect the exact content", limit=3)
    ]
    assert alpha.search("zzzz qqqq", limit=8) == []
    assert len(alpha.search("the", limit=1)) == 1


def test_search_response_matches_the_tool_result_contract():
    corpora = procedures.load_corpora(FIXTURES)
    doc = server.search_response(corpora, tenant_id=ALPHA, query="warnings incident draft", limit=2, now=NOW)
    TOOL_RESULT.validate(doc)
    assert doc["status"] == "ok" and doc["data"]["retrieval_mode"] == "lexical"
    assert (
        doc["data"]["corpus_version"] == "handoff-1"
        and doc["data"]["results"][0]["retrieved_at"] == "2026-10-08T12:00:00Z"
    )
    assert {r["document_id"] for r in doc["data"]["results"]} <= {"ALPHA-INCIDENT", "ALPHA-TRIAGE", "ALPHA-EVIDENCE"}
    unknown = server.search_response(corpora, tenant_id=UUID(int=99), query="x", limit=1, now=NOW)
    TOOL_RESULT.validate(unknown)
    assert unknown["data"] == {"results": [], "retrieval_mode": "lexical", "corpus_version": "handoff-1"}
    err = server.envelope("search_procedures", error=server.tool_error("INVALID_HANDLE", "missing invocation handle"))
    TOOL_RESULT.validate(err)
    assert err["status"] == "error" and err["data"] is None


class StubVerifier:
    @property
    def ready(self) -> bool:
        return True

    async def load_keys(self) -> None:
        return None

    async def verify_async(self, token: str) -> Principal:
        raise TokenRejected("unit test")


@pytest.mark.asyncio
async def test_tool_schema_conforms_to_the_contract_and_rejects_extra_arguments():
    state = server.State(session=None, corpora=procedures.load_corpora(FIXTURES), verifier=StubVerifier())
    mcp = server.build_server(
        state, issuer="http://localhost:18080/realms/ops-dev", resource_url="http://mcp-read:8081/mcp"
    )
    async with Client(mcp) as client:  # in-process: no HTTP, so no bearer middleware; schema and validation only
        tools = {t.name: t for t in (await client.list_tools()).tools}
        assert set(tools) == {"search_procedures"}
        schema: dict[str, Any] = tools["search_procedures"].input_schema
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(INPUT["required"])
        assert set(schema["properties"]) <= set(INPUT["properties"])
        assert schema["properties"]["mode"]["enum"] == INPUT["properties"]["mode"]["enum"]
        assert (schema["properties"]["limit"]["minimum"], schema["properties"]["limit"]["maximum"]) == (1, 8)
        assert (schema["properties"]["query"]["minLength"], schema["properties"]["query"]["maxLength"]) == (1, 500)
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
        # Without the bearer middleware there is no access token, so the tool body refuses before any lookup.
        res = await client.call_tool("search_procedures", {"query": "x", "limit": 1, "mode": "lexical"})
        assert not res.is_error and res.structured_content["status"] == "error"
        assert res.structured_content["error"]["code"] == "INVALID_HANDLE"

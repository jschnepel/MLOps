"""The worker's model-free parts (AM-16 model router, BUILD_SPEC §6 canonical proposal, §12 draft validation).

Catches: a model mode other than `fake` silently falling back (R130), a fake draft that is not a valid ModelDraft, a
proposal whose hash is not the hash of the canonical bytes stored (the decision would bind to the wrong content),
evidence refs out of order (the contract requires sorted refs with matching snapshots), a search result accepted
without the fields the proposal needs, and a manifest claiming a digest for the fake route.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from ops_core.canonical import canonical_json, canonical_sha256, parse_json_strict
from ops_core.contracts import ModelDraft, Proposal
from ops_core.routing import ModelRoute
from ops_worker import drafting, proposals

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
REQ = drafting.DraftRequest(
    asset_id="A17",
    text="Investigate the alerts on A17 over the last 24 hours.",
    start_at=NOW - timedelta(hours=24),
    end_at=NOW,
)
EV = [
    drafting.EvidenceItem("ALPHA-TRIAGE:v1:scope", "ALPHA-TRIAGE", "1", "scope", "b" * 64, "scope text"),
    drafting.EvidenceItem("ALPHA-INCIDENT:v2:review", "ALPHA-INCIDENT", "2", "review", "a" * 64, "review text"),
]


def test_model_router_has_one_route_and_no_fallback():
    assert isinstance(drafting.make_generator("fake"), drafting.FakeDraftGenerator)
    for mode in ("ollama", "qwen3:8b", "", "FAKE"):
        with pytest.raises(drafting.ModelRouteError):
            drafting.make_generator(mode)


@pytest.mark.asyncio
async def test_fake_draft_is_deterministic_and_valid():
    gen = drafting.FakeDraftGenerator()
    first = await gen.generate(REQ, EV)
    second = await gen.generate(REQ, EV)
    assert first == second and isinstance(first, ModelDraft) and first.kind == "proposal"
    assert first.evidence_refs == ["ALPHA-TRIAGE:v1:scope"]  # cites the first (highest-ranked) item
    assert any("fake" in lim.lower() for lim in first.limitations)  # BUILD_SPEC §1: never presented as a real model
    with pytest.raises(ValueError):
        await gen.generate(REQ, [])  # a proposal needs evidence; the handler maps this to INSUFFICIENT_EVIDENCE


@pytest.mark.asyncio
async def test_build_proposal_binds_hash_to_canonical_bytes():
    draft = await drafting.FakeDraftGenerator().generate(REQ, EV)
    frozen = proposals.build_proposal(
        tenant_id=UUID(int=1),
        run_id=UUID(int=2),
        proposal_id=UUID(int=3),
        revision=1,
        asset_id="A17",
        start_at=REQ.start_at,
        end_at=REQ.end_at,
        draft=draft,
        evidence=EV,
        corpus_version="handoff-1",
        now=NOW,
        supersedes_run_id=None,
    )
    assert frozen.canonical == canonical_json(frozen.payload.canonical_dict())
    assert frozen.sha256 == canonical_sha256(frozen.payload.canonical_dict())
    assert parse_json_strict(frozen.canonical.decode("utf-8")) == frozen.payload.canonical_dict()
    Proposal(
        canonicalization_version=1, payload=frozen.payload, payload_sha256=frozen.sha256, authored_by=[UUID(int=9)]
    )
    assert frozen.payload.evidence_refs == ["ALPHA-TRIAGE:v1:scope"]
    assert [s.evidence_id for s in frozen.payload.source_snapshots] == ["ALPHA-TRIAGE:v1:scope"]
    assert (
        frozen.payload.source_snapshots[0].content_sha256 == "b" * 64
        and frozen.payload.source_snapshots[0].version == "1"
    )
    assert frozen.payload.expires_at == NOW + timedelta(minutes=15)
    assert (
        frozen.payload.prompt_version == "incident-draft-v1" and frozen.payload.workflow_version == "investigation-v1"
    )
    assert frozen.manifest.model_route is ModelRoute.FAKE and frozen.manifest.model_digest is None
    assert frozen.manifest.corpus_version == "handoff-1" and frozen.manifest.retrieval_mode == "lexical"


@pytest.mark.asyncio
async def test_transport_failures_become_one_exception_type():
    from ops_worker.mcp import HttpMcpCaller, McpCallFailed, failure_leaf

    class NoToken:
        async def token(self) -> str:
            return "t"

    # Nobody listens on this port: the connection failure escapes the client's context inside an exception group.
    caller = HttpMcpCaller(NoToken(), connect_timeout=0.5)
    with pytest.raises(McpCallFailed):
        await caller.call("http://127.0.0.1:9/mcp", handle="h", tool="search_procedures", arguments={})
    inner = ValueError("leaf")
    assert failure_leaf(ExceptionGroup("outer", [ExceptionGroup("inner", [inner])])) is inner
    assert failure_leaf(inner) is inner


def test_evidence_from_search_requires_the_contract_fields():
    doc = {
        "status": "ok",
        "data": {
            "results": [
                {
                    "evidence_id": "ALPHA-INCIDENT:v2:review",
                    "document_id": "ALPHA-INCIDENT",
                    "version": "2",
                    "section": "review",
                    "content_sha256": "a" * 64,
                    "excerpt": "x",
                    "effective_from": "2026-10-01T00:00:00Z",
                    "retrieved_at": "2026-10-08T12:00:00Z",
                }
            ],
            "retrieval_mode": "lexical",
            "corpus_version": "handoff-1",
        },
    }
    assert proposals.evidence_from_search(doc)[0].evidence_id == "ALPHA-INCIDENT:v2:review"
    assert (
        proposals.evidence_from_search(
            {"status": "ok", "data": {"results": [], "retrieval_mode": "lexical", "corpus_version": "x"}}
        )
        == []
    )
    with pytest.raises(ValueError):
        proposals.evidence_from_search({"status": "error", "data": None})
    with pytest.raises(ValueError):
        proposals.evidence_from_search({"status": "ok", "data": {"results": [{"evidence_id": "x"}]}})

"""From a validated draft to the frozen proposal: the exact bytes the reviewer decides on (BUILD_SPEC §6, SA:453).

The payload is built once, canonicalised once, hashed once; the same bytes are stored, shown and sent. Evidence refs
are sorted and the snapshots follow them, as `ProposalPayload` demands, so two drafts citing the same sections in a
different order freeze to the same bytes. The run manifest records the model route (SA:379) and is validated here even
though T19 is the task that stores it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from ops_core.canonical import canonical_json, canonical_sha256
from ops_core.contracts import ModelDraft, ProposalPayload, SourceSnapshot
from ops_core.routing import ModelRoute, RunManifest

from ops_worker.drafting import PROMPT_VERSION, WORKFLOW_VERSION, EvidenceItem

EXPIRY = timedelta(minutes=15)  # BUILD_SPEC §12 default; enforced by T21


@dataclass(frozen=True)
class Frozen:
    """The proposal as frozen: payload, the exact bytes, their hash and the run manifest."""

    payload: ProposalPayload
    canonical: bytes
    sha256: str
    manifest: RunManifest


def evidence_from_search(doc: dict[str, Any]) -> list[EvidenceItem]:
    """The tool-result envelope of `search_procedures` → evidence items; anything short of the contract is an error."""
    if doc.get("status") != "ok" or not isinstance(doc.get("data"), dict):
        raise ValueError("search_procedures did not return data")
    items: list[EvidenceItem] = []
    for row in doc["data"]["results"]:
        try:
            items.append(
                EvidenceItem(
                    row["evidence_id"],
                    row["document_id"],
                    row["version"],
                    row["section"],
                    row["content_sha256"],
                    row["excerpt"],
                )
            )
        except (KeyError, TypeError) as exc:
            raise ValueError("search result row is missing a contract field") from exc
    return items


def build_proposal(
    *,
    tenant_id: UUID,
    run_id: UUID,
    proposal_id: UUID,
    revision: int,
    asset_id: str,
    start_at: datetime,
    end_at: datetime,
    draft: ModelDraft,
    evidence: list[EvidenceItem],
    corpus_version: str,
    now: datetime,
) -> Frozen:
    """Build the payload, its canonical bytes, their hash and the run manifest from a validated draft."""
    by_id = {e.evidence_id: e for e in evidence}
    refs = sorted(draft.evidence_refs)
    payload = ProposalPayload(
        tenant_id=tenant_id,
        run_id=run_id,
        proposal_id=proposal_id,
        revision=revision,
        action="create_incident",
        destination="synthetic-incidents",
        asset_id=asset_id,
        start_at=start_at,
        end_at=end_at,
        title=draft.title,
        summary=draft.summary,
        evidence_refs=refs,
        source_snapshots=[
            SourceSnapshot(evidence_id=r, content_sha256=by_id[r].content_sha256, version=by_id[r].version)
            for r in refs
        ],
        assumptions=list(draft.assumptions),
        limitations=list(draft.limitations),
        workflow_version=WORKFLOW_VERSION,
        prompt_version=PROMPT_VERSION,
        expires_at=now + EXPIRY,
    )
    doc = payload.canonical_dict()
    manifest = RunManifest(
        run_id=run_id,
        model_route=ModelRoute.FAKE,
        model_digest=None,
        prompt_version=PROMPT_VERSION,
        corpus_version=corpus_version,
        retrieval_mode="lexical",
    )
    return Frozen(payload=payload, canonical=canonical_json(doc), sha256=canonical_sha256(doc), manifest=manifest)

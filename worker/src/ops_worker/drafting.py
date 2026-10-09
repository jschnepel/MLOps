"""The model router's one route for T08: a deterministic fake DraftGenerator (AM-16; BUILD_SPEC §12).

`DraftGenerator.generate` receives only the request and the evidence bundle — no credential, approval token, SQL or
tool (BUILD_SPEC §12) — and returns a `ModelDraft`, which the contract validates (no authority fields, bounded
lists). `make_generator` is the router: `fake` is the only route until T19 adds `qwen3:8b`; anything else is an
error, never a silent fallback (R130). The fake draft says it is fake in its limitations (BUILD_SPEC §1).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from ops_core.contracts import ModelDraft
from ops_core.routing import ModelRoute

PROMPT_VERSION = "incident-draft-v1"
WORKFLOW_VERSION = "investigation-v1"


@dataclass(frozen=True)
class DraftRequest:
    """What the model may know about the ask; no identity, credential or tool is part of it."""

    asset_id: str
    text: str
    start_at: datetime
    end_at: datetime


@dataclass(frozen=True)
class EvidenceItem:
    """One retrieved procedure section, with the hash that later binds it into the proposal snapshot."""

    evidence_id: str
    document_id: str
    version: str
    section: str
    content_sha256: str
    excerpt: str


class DraftGenerator(Protocol):
    """The model router's seam: a route turns request and evidence into a draft and nothing else."""

    async def generate(self, request: DraftRequest, evidence: list[EvidenceItem]) -> ModelDraft:
        """Draft a proposal from the request and the evidence bundle alone."""
        ...


class ModelRouteError(ValueError):
    """MODEL_MODE names a route this build does not have; the worker refuses to start rather than guess."""


class FakeDraftGenerator:
    """The deterministic route that exercises the control path without a model (BUILD_SPEC §1)."""

    async def generate(self, request: DraftRequest, evidence: list[EvidenceItem]) -> ModelDraft:
        """Draft deterministically from the first evidence item; no evidence is an error."""
        if not evidence:
            raise ValueError("a proposal draft needs at least one evidence item")
        cited = evidence[0]  # the highest-ranked section; deterministic because the search is
        hours = int((request.end_at - request.start_at).total_seconds() // 3600)
        return ModelDraft(
            kind="proposal",
            title=f"Review synthetic warnings on {request.asset_id}",
            summary=(
                f"{request.asset_id} reported warnings in the {hours}-hour window ending "
                f"{request.end_at.isoformat().replace('+00:00', 'Z')}. Procedure {cited.document_id} v{cited.version} "
                f"({cited.section}) applies: {cited.excerpt[:200]}"
            ),
            evidence_refs=[cited.evidence_id],
            assumptions=["Synthetic fixture data; no live equipment was observed."],
            limitations=[f"Drafted by the fake model route ({PROMPT_VERSION}); the control path, not answer quality."],
        )


def make_generator(mode: str) -> DraftGenerator:
    """Return the generator for a model mode; any mode but `fake` raises ModelRouteError."""
    if mode == ModelRoute.FAKE.value:
        return FakeDraftGenerator()
    raise ModelRouteError(f"MODEL_MODE={mode!r} is not a route of this build (only 'fake' until T19)")

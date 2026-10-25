"""The model router (AM-16, SA:379) and the deterministic fake route (BUILD_SPEC §1, §12).

`DraftGenerator.generate` receives only the request and the evidence bundle — no credential, approval token, SQL or
tool (BUILD_SPEC §12) — and returns a `ModelDraft`. BS:437's third argument, `policy_metadata`, is not passed: the one
policy fact a draft depends on, whether the run may propose at all, travels as `DraftRequest.answer_only` (erratum 119).

`make_generator` is the router. `MODEL_MODE` names the route itself, `fake` or `qwen3:8b`; anything else, the 1.0
spelling `ollama` included, refuses to start the worker. The route is chosen once, at startup, and every run records
it in its manifest; a real route that fails mid-run fails that run and never falls back to the fake (R041, R130).
`start_route` adds the startup work a route needs (the real route's digest check and warm-up, R127) and turns every
startup failure into one exception the worker reports before it exits. The fake draft says it is fake in its
limitations (BUILD_SPEC §1).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from ops_core import prompts
from ops_core.contracts import ModelDraft
from ops_core.model_pins import ModelPinsError
from ops_core.routing import ModelRoute

PROMPT_VERSION = prompts.DRAFT_VERSION  # both routes record it; the fake reads no prompt but stands in for it
WORKFLOW_VERSION = "investigation-v1"


@dataclass(frozen=True)
class DraftRequest:
    """What the model may know about the ask; no identity, credential or tool is part of it. Two fields are the
    worker's, never shown to the model: `answer_only`, the router's verdict that this run may not propose an incident
    (SA:153), and `remaining_seconds`, what the run's compute budget has left when drafting starts (BS:555; None when
    no run holds a budget, as in the evidence script)."""

    asset_id: str
    text: str
    start_at: datetime
    end_at: datetime
    answer_only: bool = False
    remaining_seconds: float | None = None


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
    """The model router's seam: a route turns request and evidence into a draft and nothing else. `route` and
    `digest` are what the run manifest records for every run the route serves."""

    route: ModelRoute
    digest: str | None

    async def start(self) -> None:
        """Get ready to draft before the worker claims any job; raise ModelStartError if the route cannot."""
        ...

    async def generate(self, request: DraftRequest, evidence: list[EvidenceItem]) -> ModelDraft:
        """Draft from the request and the evidence bundle alone."""
        ...


class ModelRouteError(ValueError):
    """MODEL_MODE names a route this build does not have; the worker refuses to start rather than guess."""


class ModelStartError(RuntimeError):
    """The chosen route cannot serve drafts (a missing or malformed pin, another digest, Ollama unreachable, a failed
    warm-up); the worker exits non-zero with this message (R127)."""


class ModelUnavailable(Exception):
    """A draft attempt got no reply in its time, or Ollama could not be reached or answered an error; never repaired,
    never retried here (bounded outage retries are T22's and T29's)."""


class ModelOutputInvalid(Exception):
    """The reply failed validation and so did its one repair. `rules` name the repair's failures (R040)."""

    def __init__(self, rules: tuple[str, ...]) -> None:
        self.rules = rules
        super().__init__(", ".join(rules))


class FakeDraftGenerator:
    """The deterministic route that exercises the control path without a model (BUILD_SPEC §1). `delay_seconds` makes
    it as slow as a real model call without blocking the event loop (R088's "> 30 s fake drafter"; tests only)."""

    route = ModelRoute.FAKE
    digest: str | None = None  # nothing to pin; the fake never reads data/model-pins.json

    def __init__(self, delay_seconds: float = 0.0) -> None:
        self.delay_seconds = delay_seconds

    async def start(self) -> None:
        """Nothing to check or warm."""

    async def generate(self, request: DraftRequest, evidence: list[EvidenceItem]) -> ModelDraft:
        """Draft deterministically from the first evidence item; no evidence is an error."""
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
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
    """Return the generator for a model mode, without any I/O beyond reading the real route's pin.

    Raises:
        ModelRouteError: the mode is not `fake` or `qwen3:8b`.
        ModelPinsError: the real route's `data/model-pins.json` is missing or malformed.
    """
    if mode == ModelRoute.FAKE.value:
        return FakeDraftGenerator()
    if mode == ModelRoute.QWEN3_8B.value:
        # Imported here so the fake route, and every test that uses it, never loads LangChain.
        from ops_worker.ollama_drafting import OllamaDraftGenerator

        return OllamaDraftGenerator.from_settings()
    raise ModelRouteError(f"MODEL_MODE={mode!r} is not a route of this build (use 'fake' or 'qwen3:8b')")


async def start_route(mode: str) -> DraftGenerator:
    """The started generator for `mode`: chosen, checked and warmed before the worker claims any job.

    Raises:
        ModelStartError: for every reason the route cannot serve, a bad MODEL_MODE included.
    """
    try:
        generator = make_generator(mode)
    except (ModelRouteError, ModelPinsError) as exc:
        raise ModelStartError(str(exc)) from exc
    await generator.start()
    return generator

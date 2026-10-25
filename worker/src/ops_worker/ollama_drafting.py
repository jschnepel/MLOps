"""The real drafting route: qwen3:8b through LangChain's ChatOllama on local Ollama (T19; AM-31, BUILD_SPEC §12).

One draft is at most two model attempts inside a 90-second budget (BS:443, BS:554-555): the first pass, and one repair
only when the reply failed structural validation (`ops_core.draft_validation`). Each attempt gets the 60-second cap
clipped to what is left of the draft's 90 s and of the run's own compute budget (`DraftRequest.remaining_seconds`,
which the handler measures from the claim, as the heartbeat does). `asyncio.wait_for` around the call is what bounds
an attempt; the HTTP client's own 60 s timeout is only a per-read backstop (on the streaming path it limits the wait
for each chunk, not the attempt). A timeout or an unreachable model is `ModelUnavailable` and is never repaired
(there is no output to repair); an invalid repair is `ModelOutputInvalid`. Both end the run FAILED
(`handlers.investigate`); nothing here retries, falls back to the fake, or calls another model (R041). Bounded retries
of an outage are T22's and T29's.

The model is asked through a `Chat` callable, so the unit tests script every reply without a model or a network;
`ollama_chat` is the real one: `ChatOllama(reasoning=False, num_ctx=16384, num_predict=1000, temperature=0)` wrapped
in `with_structured_output(<model-draft schema>, method="json_schema", include_raw=True)` (SA:596), exactly the probe's
configuration, plus `keep_alive` so the warm model stays loaded. The wrapper's own parse is ignored: validation reads
the raw message text, because what the model emitted is what is judged.

Thinking is kept out by asking Ollama not to think (`reasoning=False` sends `think=false`) and is detected only as
inline `<think>` tags in that raw text. langchain-ollama 1.1.0 copies Ollama's separate `thinking` field into
`reasoning_content` only when `reasoning` is truthy (chat_models.py:1263-1268 and :1345-1350), so under AM-31's
setting the library drops that field before this route sees it. `Reply.reasoning` is therefore always None on the
real route; the channel is a defensive check that fires only for a `Chat` that supplies it, as the unit tests do.
The route relies on Ollama honouring `think=false` (erratum 121).

`start` runs once, before the worker claims a job (SA:597-598, R127): the installed digest from `/api/tags` must be the
pin's (`/api/show` carries none; erratum 115), then one warm-up call loads the model with its own 180-second budget (the
T02 probe's cold call passed 60 s). An Ollama version other than the pin's is logged, not fatal (SA:587). The warm-up
holds no model permit: no job runs before it ends. The `/api/tags` client is T18's `OllamaEmbedder`, whose
`installed_digest` and `version` ask nothing model-specific.
"""

from __future__ import annotations

import asyncio
import functools
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Protocol

import httpx
import ollama
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama
from ops_core import draft_validation, grading, prompts, settings
from ops_core.contracts import ModelDraft
from ops_core.draft_validation import DraftInvalid
from ops_core.embeddings import EmbeddingError, OllamaEmbedder
from ops_core.model_pins import ModelPins, load_model_pins
from ops_core.routing import ModelRoute

from ops_worker.drafting import (
    ATTEMPT_SECONDS,
    BUDGET_SECONDS,
    DraftRequest,
    EvidenceItem,
    ModelOutputInvalid,
    ModelStartError,
    ModelUnavailable,
)

log = logging.getLogger("ops_worker")
MODEL: Final = ModelRoute.QWEN3_8B.value
# TODO(T30): package the pin and the draft schema (`schemas/model-draft.schema.json`, through `grading.DRAFT_SCHEMA`);
# both are read from the checkout until then, as the embedding pin is.
PINS: Final = Path(__file__).resolve().parents[3] / "data" / "model-pins.json"
WARMUP_SECONDS: Final = 180.0  # the T02 probe's cold call passed the 60 s cap (reports/model-probe-qwen3-8b.md)
KEEP_ALIVE: Final = "30m"  # keeps the warmed model loaded between drafts; Ollama's default unloads it after 5 min
NUM_CTX: Final = 16384
NUM_PREDICT: Final = 1000
WARM_UP_REQUEST: Final = "Warm-up call at worker start; no evidence is supplied, so abstain."


@dataclass(frozen=True)
class Reply:
    """What the model emitted: its message text, unmodified, and any reasoning metadata the `Chat` supplies. The real
    `ollama_chat` never supplies it (langchain-ollama drops Ollama's `thinking` field when `reasoning=False`), so on
    the real route only inline `<think>` tags in `text` are caught."""

    text: str
    reasoning: object = None


@dataclass(frozen=True)
class Attempt:
    """One attempt as an observer sees it (the evidence script records these; the worker logs rule names only)."""

    number: int
    seconds: float
    rules: tuple[str, ...]
    kind: str | None
    text: str


# (system message, user message, seconds) -> the reply; raises ModelUnavailable when Ollama answers no draft.
Chat = Callable[[str, str, float], Awaitable[Reply]]


class Tags(Protocol):
    """The two questions `start` asks Ollama before any generation (`OllamaEmbedder` answers both)."""

    async def installed_digest(self, model: str) -> str | None:
        """The digest `/api/tags` reports for `model`, or None when it is not installed."""
        ...

    async def version(self) -> str:
        """The version `/api/version` reports."""
        ...

    async def aclose(self) -> None:
        """Release the connections."""
        ...


def _instant(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


@functools.cache
def draft_schema() -> dict[str, Any]:
    """`schemas/model-draft.schema.json`, read once (no file I/O on the event loop per draft, SA:201); never mutated."""
    schema: dict[str, Any] = json.loads(grading.DRAFT_SCHEMA.read_text(encoding="utf-8"))
    return schema


def payload(request: DraftRequest, evidence: list[EvidenceItem]) -> dict[str, Any]:
    """The user message of the first pass, with the starter's keys (`handoff/prompts/incident-draft-v1.md`)."""
    return {
        "confirmed_request": request.text,
        "asset_id": request.asset_id,
        "interval": {"start_at": _instant(request.start_at), "end_at": _instant(request.end_at)},
        "permitted_evidence": [
            {
                "evidence_id": e.evidence_id,
                "document_id": e.document_id,
                "version": e.version,
                "section": e.section,
                "excerpt": e.excerpt,
            }
            for e in evidence
        ],
        "allowed_evidence_ids": [e.evidence_id for e in evidence],
        "requested_output_schema": draft_schema(),
    }


def repair_payload(first: dict[str, Any], reply: Reply, invalid: DraftInvalid) -> dict[str, Any]:
    """The repair's user message: the failed reply, the instance-free feedback and the same inputs (BS:454). A reply
    that showed thinking is not shown back, so no reasoning text travels further (BS:460)."""
    shown = None if "thinking" in invalid.rules else reply.text
    return {"invalid_output": shown, "validation_errors": list(invalid.feedback), **first}


def ollama_chat(base_url: str) -> Chat:
    """The real `Chat`: one ChatOllama per timeout class (drafting, warm-up), with identical model options, so the
    warm-up loads exactly the model instance the drafts use (another `num_ctx` would reload it)."""
    schema = draft_schema()

    def drafter(client_seconds: float) -> Any:
        llm = ChatOllama(
            model=MODEL,
            base_url=base_url,
            reasoning=False,
            num_ctx=NUM_CTX,
            num_predict=NUM_PREDICT,
            temperature=0,
            keep_alive=KEEP_ALIVE,
            client_kwargs={"timeout": client_seconds},
        )
        return llm.with_structured_output(schema, method="json_schema", include_raw=True)

    drafting, warming = drafter(ATTEMPT_SECONDS), drafter(WARMUP_SECONDS)

    async def chat(system: str, user: str, seconds: float) -> Reply:
        runnable = warming if seconds > ATTEMPT_SECONDS else drafting
        try:
            out = await runnable.ainvoke([SystemMessage(content=system), HumanMessage(content=user)])
        # ChatOllama streams by default, and on the stream path ollama 0.6.3 wraps nothing: a refused connection arrives
        # as httpx.ConnectError and a timeout or a dropped connection as another httpx error; an HTTP error status is
        # ollama.ResponseError, and the non-stream path's ConnectionError is kept for completeness.
        except (ConnectionError, ollama.ResponseError, httpx.HTTPError) as exc:
            raise ModelUnavailable(f"Ollama answered no draft ({type(exc).__name__})") from exc
        except ValueError as exc:
            # langchain-ollama 1.1.0 raises a bare ValueError("No data received from Ollama stream.") when the stream
            # ends empty (chat_models.py:1147 and :1173); that is an outage too. Any other ValueError is a bug.
            if "No data received" not in str(exc):
                raise
            raise ModelUnavailable("Ollama answered no draft (empty stream)") from exc
        raw = out["raw"]
        text = raw.content if isinstance(raw.content, str) else json.dumps(raw.content)
        return Reply(text, raw.additional_kwargs.get("reasoning_content"))

    return chat


class OllamaDraftGenerator:
    """The qwen3:8b route. `digest` is the pin's, which `start` has proved equal to the installed model's."""

    route = ModelRoute.QWEN3_8B

    def __init__(
        self,
        pins: ModelPins,
        chat: Chat,
        tags: Tags,
        *,
        clock: Callable[[], float] = time.monotonic,
        on_attempt: Callable[[Attempt], None] | None = None,
    ) -> None:
        self.pins = pins
        self.digest: str | None = pins.digest
        self.ollama_version: str | None = None  # what `start` saw
        self._chat, self._tags, self._clock, self._on_attempt = chat, tags, clock, on_attempt
        # Read once here, never per draft (SA:201: no synchronous I/O on the event loop).
        self._draft_system = prompts.text(prompts.DRAFT_VERSION)
        self._repair_system = prompts.text(prompts.REPAIR_VERSION)
        draft_schema()

    @classmethod
    def from_settings(cls, *, on_attempt: Callable[[Attempt], None] | None = None) -> OllamaDraftGenerator:
        """Wired from `data/model-pins.json` and `OPS_OLLAMA_URL` (one Ollama serves both pins); `on_attempt` is the
        evidence script's observer (the worker passes none).

        Raises:
            ModelPinsError: the pin file is missing or malformed.
        """
        url = settings.urls().ollama
        return cls(load_model_pins(PINS), ollama_chat(url), OllamaEmbedder(url), on_attempt=on_attempt)

    async def start(self) -> None:
        """Verify the installed digest against the pin, then warm the model; ModelStartError on any failure."""
        asking = "the installed models"
        try:
            if self.pins.model != MODEL:
                raise ModelStartError(f"data/model-pins.json pins {self.pins.model!r}, not this route's {MODEL}")
            installed = await self._tags.installed_digest(MODEL)
            asking = "its version"
            self.ollama_version = await self._tags.version()
        except EmbeddingError as exc:
            raise ModelStartError(f"Ollama could not be asked for {asking} ({exc.code})") from exc
        finally:
            await self._tags.aclose()
        if installed is None:
            raise ModelStartError(f"{MODEL} is not installed in Ollama; nothing is pulled without the owner")
        if installed != self.pins.digest:
            raise ModelStartError(
                f"the installed {MODEL} digest is not the one data/model-pins.json pins (probed {self.pins.probed_at})"
            )
        if self.ollama_version != self.pins.ollama_version:
            log.warning("Ollama %s answers; the pin was probed on %s", self.ollama_version, self.pins.ollama_version)
        warm_up = payload(DraftRequest("WARMUP", WARM_UP_REQUEST, datetime.now(UTC), datetime.now(UTC)), [])
        try:
            await asyncio.wait_for(
                self._chat(self._draft_system, json.dumps(warm_up, ensure_ascii=False), WARMUP_SECONDS),
                WARMUP_SECONDS,
            )
        except Exception as exc:  # a timeout, an outage or a bug alike: never serve on a model that failed to warm
            raise ModelStartError(f"the warm-up call to {MODEL} failed ({type(exc).__name__})") from exc
        log.info("model route %s ready: digest %s, Ollama %s", MODEL, self.digest, self.ollama_version)

    async def _ask(
        self, number: int, system: str, user: str, started: float, request: DraftRequest
    ) -> tuple[Reply, float]:
        # Each attempt: the 60 s cap, clipped to what is left of the draft's 90 s and of the run's compute budget
        # (BS:555). An attempt left with nothing times out at once, as ModelUnavailable.
        elapsed = self._clock() - started
        limit = BUDGET_SECONDS - elapsed
        if request.remaining_seconds is not None:
            limit = min(limit, request.remaining_seconds - elapsed)
        seconds = max(0.0, min(ATTEMPT_SECONDS, limit))
        if seconds <= 0:
            # Nothing left: never start the call (a zero timeout still enters the coroutine up to its first await,
            # which could open a connection to Ollama before the cancel).
            raise ModelUnavailable(f"draft attempt {number} passed its {seconds:.0f} s")
        began = self._clock()
        try:
            reply = await asyncio.wait_for(self._chat(system, user, seconds), seconds)
        except TimeoutError:
            raise ModelUnavailable(f"draft attempt {number} passed its {seconds:.0f} s") from None
        return reply, self._clock() - began

    def _judge(
        self, number: int, reply: Reply, seconds: float, request: DraftRequest, allowed: frozenset[str]
    ) -> ModelDraft | DraftInvalid:
        """The validated draft, or the DraftInvalid that says why not; the observer sees either way."""
        try:
            draft: ModelDraft | DraftInvalid = draft_validation.validate(
                reply.text, reasoning=reply.reasoning, allowed_ids=allowed, answer_only=request.answer_only
            )
        except DraftInvalid as exc:
            draft = exc
        if self._on_attempt is not None:
            rules = draft.rules if isinstance(draft, DraftInvalid) else ()
            kind = None if isinstance(draft, DraftInvalid) else draft.kind
            self._on_attempt(Attempt(number, round(seconds, 2), rules, kind, reply.text))
        return draft

    async def generate(self, request: DraftRequest, evidence: list[EvidenceItem]) -> ModelDraft:
        """At most two attempts within the budget; a validated draft of any kind, or an exception.

        Raises:
            ModelUnavailable: an attempt timed out or Ollama answered no reply.
            ModelOutputInvalid: the first reply and its one repair both failed validation.
        """
        started = self._clock()
        allowed = frozenset(e.evidence_id for e in evidence)
        first = payload(request, evidence)
        reply, seconds = await self._ask(1, self._draft_system, json.dumps(first, ensure_ascii=False), started, request)
        judged = self._judge(1, reply, seconds, request, allowed)
        if isinstance(judged, ModelDraft):
            return judged
        log.info("draft attempt 1 invalid (%s); one repair", ", ".join(judged.rules))
        repair = json.dumps(repair_payload(first, reply, judged), ensure_ascii=False)
        reply, seconds = await self._ask(2, self._repair_system, repair, started, request)
        judged = self._judge(2, reply, seconds, request, allowed)
        if isinstance(judged, ModelDraft):
            return judged
        raise ModelOutputInvalid(judged.rules)

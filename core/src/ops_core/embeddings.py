"""The embedding model's text rules and its Ollama client (T18; Plan N rulings 2-4, 12, 13 and 17; SA:645, SA:348).

`nomic-embed-text` is trained with task prefixes, and SA:645 requires them: a document is embedded as
`search_document: ` + its section heading + a blank line + its body (the heading and the body, as the lexical vector
indexes both), a query as `search_query: ` + the query text. The builders here are the only place those strings are
made; the unit tests assert the request bodies an embedder sends, and every stored row keeps the SHA-256 of the exact
text it was made from.

`OllamaEmbedder` talks to local Ollama (`OPS_OLLAMA_URL`, loopback by default) with `httpx2`, a 10-second timeout per
request and no retry (asset-sim's client pattern). It asks only `/api/version`, `/api/tags` (the pinned digest;
`/api/show` carries none) and `/api/embed`, never a generation endpoint, so it is not a `model_permit` holder (SA:203
governs generation). Failures map to one exception each, which the callers turn into their own answers: unreachable, a timeout
or a 5xx is `Unavailable` (retryable); a digest or model other than the pin is `PinMismatch`; any answer that is not
exactly one list of 768 finite floats per input, with a non-zero norm, is `Malformed`.

Vectors cross into PostgreSQL as pgvector's text form cast in SQL (`%s::public.vector`), each float written with
`repr` so it round-trips exactly; no `pgvector` package is used (erratum 109).
"""

from __future__ import annotations

import asyncio
import hashlib
import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final, Protocol

import httpx2

from ops_core import settings
from ops_core.model_pins import EmbeddingPins

MODEL: Final = "nomic-embed-text"
DIMENSION: Final = 768
DOCUMENT_PREFIX: Final = "search_document: "
QUERY_PREFIX: Final = "search_query: "
BATCH: Final = 16  # inputs per /api/embed request: small enough for one 10-second request on the dev machine
TIMEOUT_SECONDS: Final = 10.0  # Plan N ruling 4, as asset-sim's client
PINS: Final = Path(__file__).resolve().parents[3] / "data" / "embedding-pins.json"  # read from the checkout (T30)

Vector = tuple[float, ...]


class EmbeddingError(Exception):
    """The embedding model gave no usable answer; `code` and `retryable` are what a tool's error envelope carries."""

    code = "UPSTREAM_INVALID"
    retryable = False


class Unavailable(EmbeddingError):
    """Ollama could not be reached, timed out or answered 5xx: try again later."""

    code = "UNAVAILABLE"
    retryable = True


class PinMismatch(EmbeddingError):
    """The installed model is not the pinned one (another digest, or not installed): vector mode is unsupported."""

    code = "UNSUPPORTED_MODE"


class Malformed(EmbeddingError):
    """An answer that is not one finite, non-zero vector of the pinned dimension per input."""


def document_text(section: str, body: str) -> str:
    """The exact text a stored chunk is embedded from: the document prefix, the heading, a blank line, the body."""
    return f"{DOCUMENT_PREFIX}{section}\n\n{body}"


def query_text(query: str) -> str:
    """The exact text a search query is embedded from."""
    return f"{QUERY_PREFIX}{query}"


def input_sha256(text: str) -> str:
    """The SHA-256 of the UTF-8 text sent to the model: the stored proof of which text, prefix included, was used."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def vector_literal(vector: Sequence[float]) -> str:
    """pgvector's text form, `[f1,f2,...]`, with `repr` floats so the value round-trips exactly."""
    return "[" + ",".join(repr(float(value)) for value in vector) + "]"


def parse_vector(text: str) -> Vector:
    """A vector read back in pgvector's text form (tests and the measurement read stored rows this way)."""
    inner = text.strip()
    if not (inner.startswith("[") and inner.endswith("]")):
        raise ValueError("not a vector in pgvector's text form")
    return tuple(float(part) for part in inner[1:-1].split(",")) if inner != "[]" else ()


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity in plain double-precision arithmetic (no numpy, ruling 17)."""
    dot = math.fsum(x * y for x, y in zip(a, b, strict=True))
    return dot / math.sqrt(math.fsum(x * x for x in a) * math.fsum(y * y for y in b))


def checked(raw: object, expected: int, dimension: int = DIMENSION) -> list[Vector]:
    """`/api/embed`'s `embeddings` as vectors, or Malformed: exactly `expected` lists of `dimension` finite numbers
    each (a JSON boolean is not a number), none of them all zeros."""
    if not isinstance(raw, list) or len(raw) != expected:
        raise Malformed("the embedding answer has another number of vectors than inputs")
    out: list[Vector] = []
    for item in raw:
        if not isinstance(item, list) or len(item) != dimension:
            raise Malformed("an embedding has another dimension than the pinned one")
        try:
            numbers = all(isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v) for v in item)
        except OverflowError as exc:  # a JSON integer too large for a double is no number the model can have made
            raise Malformed("an embedding holds a value that is not a finite number") from exc
        if not numbers:
            raise Malformed("an embedding holds a value that is not a finite number")
        vector = tuple(float(v) for v in item)
        if not any(vector):
            raise Malformed("an embedding is all zeros")
        out.append(vector)
    return out


class Embedder(Protocol):
    """What mcp-read and `skeleton.py embed` need from the embedding model, so unit tests can stand one in."""

    async def verify(self, pins: EmbeddingPins) -> None:
        """Raise PinMismatch unless the installed model is the pinned one; Unavailable when it cannot be asked."""
        ...

    async def embed(self, texts: Sequence[str], pins: EmbeddingPins) -> list[Vector]:
        """One vector per text, in order, of the pinned dimension."""
        ...

    async def aclose(self) -> None:
        """Release the connections."""
        ...


class OllamaEmbedder:
    """The real embedder: one pooled httpx2 client to local Ollama."""

    def __init__(self, base_url: str, *, transport: httpx2.AsyncBaseTransport | None = None) -> None:
        """`transport` lets unit tests answer without a socket."""
        self._base = base_url.rstrip("/")
        self._http = httpx2.AsyncClient(timeout=TIMEOUT_SECONDS, transport=transport)

    @classmethod
    def from_settings(cls) -> OllamaEmbedder:
        """Wired from `OPS_OLLAMA_URL` (`settings.Urls.ollama`)."""
        return cls(settings.urls().ollama)

    async def _json(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            async with asyncio.timeout(TIMEOUT_SECONDS):
                response = await self._http.request(method, f"{self._base}{path}", json=payload)
        # A closed client raises RuntimeError and the budget's expiry a TimeoutError (an OSError); neither may escape
        # as anything but Unavailable, and none puts its text in an answer.
        except (httpx2.HTTPError, OSError, RuntimeError) as exc:
            raise Unavailable("the embedding model could not be reached") from exc
        if response.status_code >= 500:
            raise Unavailable("the embedding model is unavailable")
        if response.status_code != 200:
            raise Malformed(f"the embedding model answered {response.status_code}")
        try:
            body = response.json()
        except ValueError as exc:
            raise Malformed("the embedding model answered a body that is not JSON") from exc
        if not isinstance(body, dict):
            raise Malformed("the embedding model answered a body that is not an object")
        return body

    async def version(self) -> str:
        """The Ollama version `/api/version` reports (the pin and the comparison record it)."""
        found = (await self._json("GET", "/api/version")).get("version")
        if not isinstance(found, str):
            raise Malformed("/api/version answered without a version")
        return found

    async def installed_digest(self, model: str) -> str | None:
        """The digest `/api/tags` reports for `model` (`name:latest` when the name has no tag), or None."""
        names = {model, model if ":" in model else f"{model}:latest"}
        body = await self._json("GET", "/api/tags")
        models = body.get("models")
        if not isinstance(models, list):
            raise Malformed("/api/tags answered without a model list")
        for entry in models:
            if isinstance(entry, dict) and (entry.get("name") in names or entry.get("model") in names):
                digest = entry.get("digest")
                return digest if isinstance(digest, str) else None
        return None

    async def dimension(self, model: str) -> int:
        """The dimension of one real `/api/embed` answer for `model`: what the pin script records. The answer must be
        exactly one finite, non-zero vector (Malformed otherwise); whether the length is the pinned 768 is the
        caller's rule, as no pin exists yet when this is asked."""
        body = await self._json("POST", "/api/embed", {"model": model, "input": ["dimension probe"]})
        raw = body.get("embeddings")
        if not isinstance(raw, list) or len(raw) != 1 or not isinstance(raw[0], list):
            raise Malformed("the dimension probe did not answer exactly one vector")
        return len(checked(raw, 1, len(raw[0]))[0])

    async def verify(self, pins: EmbeddingPins) -> None:
        """Refuse a pin for another model or dimension, and an installed model whose `/api/tags` digest is not the
        pin's (PinMismatch); an Ollama that cannot be asked is Unavailable."""
        if pins.model != MODEL or pins.dimension != DIMENSION:
            raise PinMismatch("the pin names another embedding model")
        if await self.installed_digest(pins.model) != pins.digest:
            raise PinMismatch("the installed embedding model is not the pinned one")

    async def embed(self, texts: Sequence[str], pins: EmbeddingPins) -> list[Vector]:
        """One checked vector per text, in order, asked in batches of `BATCH`; it does not verify the pin (the
        caller does, once, before a run or a query)."""
        out: list[Vector] = []
        for start in range(0, len(texts), BATCH):
            batch = list(texts[start : start + BATCH])
            body = await self._json("POST", "/api/embed", {"model": pins.model, "input": batch})
            out.extend(checked(body.get("embeddings"), len(batch), pins.dimension))
        return out

    async def aclose(self) -> None:
        """Close the pooled HTTP client."""
        await self._http.aclose()

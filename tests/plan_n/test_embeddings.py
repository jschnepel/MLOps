"""The embedding text rules and the Ollama client without Ollama (T18 DoD 2; Plan N rulings 2-4, 12, 13 and 17).

Catches: a document or a query embedded without its nomic prefix, with another separator or without the heading (the
request bodies are asserted byte for byte, SA:645); a pin check that trusts `/api/show`, accepts another digest or a
model that is not installed; an answer accepted with another count of vectors, another dimension, a NaN, an infinity,
a boolean or all zeros; an unreachable, slow or failing Ollama reported as anything but the retryable `Unavailable`;
a vector literal that does not round-trip; and a deterministic fake embedder that is not deterministic.
"""

import hashlib
import json
import math
import random
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any

import httpx2
import pytest
from ops_core import embeddings
from ops_core.model_pins import EmbeddingPins

pytestmark = pytest.mark.asyncio

PINS = EmbeddingPins(
    model="nomic-embed-text",
    digest="0a109f422b47e3a30ba2b10eca18548e944e8a23073ee3f3e947efcf3c45e59f",
    dimension=768,
    ollama_version="0.40.4",
    probed_at=datetime(2026, 10, 19, tzinfo=UTC),
)
TAGS = {"models": [{"name": "nomic-embed-text:latest", "model": "nomic-embed-text:latest", "digest": PINS.digest}]}


def unit_vector(text: str, dimension: int = 768) -> list[float]:
    """A deterministic fake embedding: a unit vector seeded by the text's SHA-256 (Plan N ruling 13)."""
    rng = random.Random(hashlib.sha256(text.encode("utf-8")).digest())
    raw = [rng.gauss(0.0, 1.0) for _ in range(dimension)]
    norm = math.sqrt(sum(x * x for x in raw))
    return [x / norm for x in raw]


class FakeEmbedder:
    """The deterministic embedder unit tests stand in for Ollama (mcp-read's tests use it too)."""

    def __init__(self, failure: embeddings.EmbeddingError | None = None) -> None:
        self.failure = failure
        self.texts: list[str] = []
        self.verified = 0

    async def verify(self, pins: EmbeddingPins) -> None:
        self.verified += 1
        if isinstance(self.failure, embeddings.PinMismatch | embeddings.Unavailable):
            raise self.failure

    async def embed(self, texts: Sequence[str], pins: EmbeddingPins) -> list[embeddings.Vector]:
        self.texts.extend(texts)
        if self.failure is not None:
            raise self.failure
        return [tuple(unit_vector(t)) for t in texts]

    async def aclose(self) -> None:
        return None


Answer = Callable[[httpx2.Request], httpx2.Response]


def ollama(embed: Answer | None = None, tags: dict[str, Any] = TAGS) -> tuple[embeddings.OllamaEmbedder, list[Any]]:
    """The real client over a scripted transport; returns it and the JSON bodies it posted."""
    posted: list[Any] = []

    def answer(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/api/tags":
            return httpx2.Response(200, json=tags)
        assert request.url.path == "/api/embed", request.url.path  # never /api/show, /api/generate or a pull
        body = json.loads(request.content)
        posted.append(body)
        if embed is not None:
            return embed(request)
        return httpx2.Response(
            200, json={"model": body["model"], "embeddings": [unit_vector(t) for t in body["input"]]}
        )

    return embeddings.OllamaEmbedder("http://ollama.test", transport=httpx2.MockTransport(answer)), posted


async def test_a_document_is_embedded_as_search_document_heading_blank_line_body() -> None:
    client, posted = ollama()
    text = embeddings.document_text("inspection", "Inspect the seal every 14 days.")
    vectors = await client.embed([text], PINS)
    assert posted == [
        {"model": "nomic-embed-text", "input": ["search_document: inspection\n\nInspect the seal every 14 days."]}
    ]
    assert len(vectors) == 1 and len(vectors[0]) == 768
    assert embeddings.input_sha256(text) == hashlib.sha256(posted[0]["input"][0].encode("utf-8")).hexdigest()


async def test_a_query_is_embedded_as_search_query_and_the_text() -> None:
    client, posted = ollama()
    await client.embed([embeddings.query_text("How often is the seal inspected?")], PINS)
    assert posted == [{"model": "nomic-embed-text", "input": ["search_query: How often is the seal inspected?"]}]


async def test_documents_go_in_batches_of_sixteen_in_order() -> None:
    client, posted = ollama()
    texts = [embeddings.document_text(f"s{i}", "body") for i in range(40)]
    vectors = await client.embed(texts, PINS)
    assert [len(b["input"]) for b in posted] == [16, 16, 8]
    assert [t for b in posted for t in b["input"]] == texts
    assert vectors == [tuple(unit_vector(t)) for t in texts]


async def test_the_pin_is_checked_against_the_tags_digest() -> None:
    client, _ = ollama()
    await client.verify(PINS)  # `nomic-embed-text` is listed as `nomic-embed-text:latest`
    for tags in (
        {"models": [{"name": "nomic-embed-text:latest", "digest": "ab" * 32}]},  # another build
        {"models": [{"name": "qwen3:8b", "digest": PINS.digest}]},  # not installed
    ):
        other, _ = ollama(tags=tags)
        with pytest.raises(embeddings.PinMismatch):
            await other.verify(PINS)
    with pytest.raises(embeddings.PinMismatch):
        await client.verify(PINS.model_copy(update={"model": "mxbai-embed-large"}))


@pytest.mark.parametrize(
    "vectors",
    [
        [],
        [[0.1] * 767],
        [[0.1] * 767 + [float("nan")]],
        [[0.1] * 767 + [float("inf")]],
        [[0.1] * 767 + [10**400]],  # an integer too large for a double: math.isfinite raises OverflowError
        [[0.1] * 767 + [True]],
        [[0.0] * 768],
        [[0.1] * 767 + [1e7]],  # finite in double precision, out of the single-precision range pgvector sums in
        [[-1e7] + [0.1] * 767],
        [[3e38] + [0.0] * 767],  # near float4's maximum: the stored row would turn every similarity into NaN
        [[1e-7] + [0.0] * 767],  # a norm below 1e-6: single precision underflows its square to a zero norm
        "not a list",
    ],
    ids=[
        "no-vector",
        "767",
        "nan",
        "infinity",
        "overflow",
        "boolean",
        "zeros",
        "large-positive",
        "large-negative",
        "near-float4-maximum",
        "tiny-norm",
        "not-a-list",
    ],
)
async def test_a_malformed_answer_is_refused(vectors: Any) -> None:
    def answer(request: httpx2.Request) -> httpx2.Response:
        # json.dumps writes NaN and Infinity as bare tokens, which Python's parser reads back as floats.
        return httpx2.Response(200, content=json.dumps({"embeddings": vectors}).encode())

    client, _ = ollama(answer)
    with pytest.raises(embeddings.Malformed):
        await client.embed(["search_query: x"], PINS)


def test_the_magnitude_bound_keeps_unit_vectors_and_the_edges_of_the_rule() -> None:
    """Plan N final review, m1: components up to 1e6 and a norm of at least 1e-6 are answers; the model's own unit
    vectors are far inside both."""
    ordinary = unit_vector("ordinary")
    edge_large = [1e6] + [0.0] * 767
    edge_small = [1e-6] + [0.0] * 767
    assert embeddings.checked([ordinary, edge_large, edge_small], 3) == [
        tuple(v) for v in (ordinary, edge_large, edge_small)
    ]


@pytest.mark.parametrize("kind", ["connect", "timeout", "503"])
async def test_an_unreachable_or_failing_model_is_unavailable_and_retryable(kind: str) -> None:
    def answer(request: httpx2.Request) -> httpx2.Response:
        if kind == "connect":
            raise httpx2.ConnectError("refused", request=request)
        if kind == "timeout":
            raise httpx2.ReadTimeout("slow", request=request)
        return httpx2.Response(503, json={"error": "loading"})

    client, _ = ollama(answer)
    with pytest.raises(embeddings.Unavailable) as caught:
        await client.embed(["search_query: x"], PINS)
    assert caught.value.code == "UNAVAILABLE" and caught.value.retryable


async def test_vector_literals_round_trip_and_cosine_is_plain_arithmetic() -> None:
    vector = tuple(unit_vector("round trip"))
    literal = embeddings.vector_literal(vector)
    assert literal.startswith("[") and " " not in literal
    assert embeddings.parse_vector(literal) == vector
    assert embeddings.cosine(vector, vector) == pytest.approx(1.0)
    assert embeddings.cosine((1.0, 0.0), (0.0, 1.0)) == 0.0


async def test_the_fake_embedder_is_deterministic() -> None:
    fake = FakeEmbedder()
    first = await fake.embed(["search_query: seal"], PINS)
    assert first == await fake.embed(["search_query: seal"], PINS)
    assert first != await fake.embed(["seal"], PINS)

"""The document embeddings as role `worker` (T18; Plan N rulings 2, 3, 12 and 14; erratum 98's operator-command shape).

`scripts/skeleton.py embed` runs this after `ingest`: it embeds every stored chunk that has no embedding yet, with the
pinned model, from the chunk's stored section and body (`embeddings.document_text`, the `search_document:` prefix
included), and keeps the SHA-256 of that exact text beside the vector. Lifecycle is decided at query time, so every
stored chunk is embedded, whatever its status, and the clock is never consulted (ingestion's rule). The pin is checked
against Ollama's `/api/tags` before anything is written.

Like ingestion, a run plans every tenant first, each in a read-only unit under its tenant setting, and writes nothing
if any tenant is refused: a tenant that already holds an embedding made with another digest than the pin is refused
(a model change is a later revision's re-embedding, never a mix). The vectors are fetched outside any transaction;
then each tenant is written in one transaction that re-reads what is missing and inserts those rows with
`ON CONFLICT DO NOTHING`, so a second run at the same moment neither fails on the key nor writes a row twice, and each
report counts only the rows its own run inserted. A failure while writing (Ollama gone, an answer that is not the
pinned vectors) leaves the tenants already committed as they are and names them (`EmbedInterrupted`, as ingestion's
`IngestInterrupted`); a re-run embeds only what is still missing. A repeat with nothing missing writes nothing.

The pin is asked again for every tenant that has vectors to write, after they are fetched and before its transaction,
so a model re-pulled while the run was going stores nothing under the pinned digest; that mismatch is mapped as any other
failure of the writing phase (the tenants already committed are named).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

import psycopg

from ops_core import embeddings, persistence
from ops_core.model_pins import EmbeddingPins

RELATIONS = ("app.chunks", "app.embeddings")


class EmbedRefused(Exception):
    """The run was refused; `problems` names each tenant and the rule, never a text. `written` names the tenants an
    earlier transaction of this run already committed (empty for every refusal of the planning phase, which writes
    nothing; non-empty only when another digest appeared while writing)."""

    def __init__(self, problems: list[str], written: tuple[str, ...] = ()) -> None:
        self.problems = tuple(problems)
        self.written = written
        super().__init__("\n".join(self.problems))


class EmbedInterrupted(Exception):
    """A failure while writing stopped the run after `written` tenants had committed (the failing tenant rolled back);
    the failure itself is the `__cause__`."""

    def __init__(self, written: tuple[str, ...]) -> None:
        self.written = written
        super().__init__("embedding interrupted after writing " + ", ".join(written))


@dataclass(frozen=True)
class Missing:
    """One stored chunk without an embedding: its evidence ID and the exact text to embed."""

    evidence_id: str
    text: str


@dataclass(frozen=True)
class Report:
    """What one tenant's run wrote and found already present."""

    tenant: str
    added: int
    present: int


async def _read(conn: persistence.Conn, digest: str) -> tuple[list[Missing], int, int]:
    """The caller's tenant's chunks without an embedding (in byte order), how many rows exist, and how many of those
    were made with another digest than `digest`."""
    cur = await conn.execute(
        "SELECT c.evidence_id, c.section, c.body FROM app.chunks c LEFT JOIN app.embeddings e"
        ' USING (tenant_id, evidence_id) WHERE e.embedding IS NULL ORDER BY c.evidence_id COLLATE "C"'
    )
    missing = [
        Missing(str(row["evidence_id"]), embeddings.document_text(str(row["section"]), str(row["body"])))
        for row in await cur.fetchall()
    ]
    cur = await conn.execute(
        "SELECT count(*) AS present, count(*) FILTER (WHERE model_digest <> %s) AS other_digest FROM app.embeddings",
        (digest,),
    )
    row = await cur.fetchone()
    present, foreign = (0, 0) if row is None else (int(row["present"]), int(row["other_digest"]))
    return missing, present, foreign


async def embed(
    conn: persistence.Conn, embedder: embeddings.Embedder, pins: EmbeddingPins, tenants: Mapping[str, UUID]
) -> list[Report]:
    """Embed every stored chunk without an embedding for each named tenant, on a `worker` connection.

    Args:
        conn: an autocommit connection as role `worker` (AM-20.2's corpus cells, SA:431).
        embedder: the embedding model's client (`embeddings.OllamaEmbedder` in production).
        pins: `data/embedding-pins.json` as `model_pins.load_embedding_pins` read it.
        tenants: tenant slug -> tenant UUID.

    Raises:
        PersistenceError: revision 0013 is missing (`persistence.assert_relation`).
        embeddings.EmbeddingError: the model is not the pinned one (PinMismatch), cannot be reached (Unavailable) or
            answered something else than the pinned vectors (Malformed), before any tenant committed; the pin is also
            asked again before each tenant's write transaction. This and any
            `psycopg.Error` or `PersistenceError` propagate unchanged when nothing was written.
        EmbedInterrupted: one of those failures after earlier tenants had committed; `written` names them.
        EmbedRefused: a tenant holds embeddings of another digest (`written` empty: nothing was written), or another
            digest appeared while writing (`written` names the tenants already committed).
    """
    for relation in RELATIONS:
        await persistence.assert_relation(conn, relation)
    await embedder.verify(pins)  # before anything is read for writing (ruling 3)
    order = sorted(tenants.items())
    problems: list[str] = []
    for tenant, tenant_id in order:  # phase 1: refuse a mixed store before anything is written
        async with conn.transaction():
            await persistence.set_tenant(conn, tenant_id)
            _, _, foreign = await _read(conn, pins.digest)
        if foreign:
            problems.append(f"{tenant}: {foreign} stored embeddings were made with another model digest than the pin")
    if problems:
        raise EmbedRefused(problems)
    reports: list[Report] = []
    for tenant, tenant_id in order:  # phase 2: fetch outside a transaction, then one transaction per tenant
        written = tuple(r.tenant for r in reports if r.added)
        try:
            reports.append(await _write(conn, embedder, pins, tenant, tenant_id))
        except EmbedRefused as refusal:
            raise EmbedRefused(list(refusal.problems), written) from refusal
        except (embeddings.EmbeddingError, psycopg.Error, persistence.PersistenceError) as error:
            if not written:
                raise  # nothing committed: the failure itself is the whole story
            raise EmbedInterrupted(written) from error
    return reports


async def _write(
    conn: persistence.Conn, embedder: embeddings.Embedder, pins: EmbeddingPins, tenant: str, tenant_id: UUID
) -> Report:
    """One tenant: what is missing, its vectors (outside a transaction), then one transaction that re-checks and
    inserts."""
    async with conn.transaction():
        await persistence.set_tenant(conn, tenant_id)
        missing, _, _ = await _read(conn, pins.digest)
    vectors: list[embeddings.Vector] = []
    if missing:
        vectors = await embedder.embed([m.text for m in missing], pins)
        # Asked again after the vectors came back and before anything is written: a model re-pulled since the run began
        # must not leave vectors of another digest labelled with the pinned one.
        await embedder.verify(pins)
    made = {m.evidence_id: (m, v) for m, v in zip(missing, vectors, strict=True)}
    async with conn.transaction():
        await persistence.set_tenant(conn, tenant_id)
        still, present, foreign = await _read(conn, pins.digest)
        if foreign:
            raise EmbedRefused([f"{tenant}: another model digest appeared while embedding; this tenant rolled back"])
        added = 0
        for row in still:
            if row.evidence_id not in made:
                continue  # a chunk ingested meanwhile: the next run embeds it
            chunk, vector = made[row.evidence_id]
            cur = await conn.execute(
                "INSERT INTO app.embeddings (tenant_id, evidence_id, model, model_digest, dimension, input_sha256,"
                " embedding) VALUES (%s, %s, %s, %s, %s, %s, %s::public.vector)"
                " ON CONFLICT (tenant_id, evidence_id) DO NOTHING",
                (
                    tenant_id,
                    chunk.evidence_id,
                    pins.model,
                    pins.digest,
                    pins.dimension,
                    embeddings.input_sha256(chunk.text),
                    embeddings.vector_literal(vector),
                ),
            )
            added += cur.rowcount  # 0 when a concurrent run inserted the row first
    return Report(tenant, added, present)

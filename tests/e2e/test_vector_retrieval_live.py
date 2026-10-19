"""The stored embeddings and the vector search against real local Ollama (OPS_LIVE=1; T18 DoD 2; Plan N rulings 2, 7,
12 and 14).

Catches: a stored row whose text was not the prefixed section (its `input_sha256` is not the SHA-256 of
`search_document: ` + heading + blank line + body), made with another model, digest or dimension than the pin, or
missing for a stored chunk; a stored vector that is not the embedding of that prefixed text (a fresh embedding must be
the same vector within the repeat bound, and the unprefixed text's embedding must not be); an `embed` repeat that
writes again; a store with another digest's embeddings written into instead of refused; a failure while writing
reported as "nothing written" after a tenant committed, or a re-run that does not complete the rest; and a definer
whose vector answer is not exactly the brute-force cosine ranking of the stored vectors over the permitted set (same
threshold, same byte-order tie-break) for every development query: no index, nothing approximate.
"""

from collections.abc import Awaitable, Callable, Sequence
from uuid import UUID

import pytest
from ops_core import corpus, embed, embeddings, model_pins, persistence
from ops_core.settings import Role

from scripts import retrieval_baseline as rb
from scripts import retrieval_comparison as rc
from scripts.skeleton import CORPUS, corpus_tenants
from tests.e2e.conftest import lease_for, purge_run
from tests.e2e.test_fenced_definers_live import investigate_job, read_handle
from tests.e2e.test_migration_0011_live import DAY, cleanup, clock, handle_for, stage
from tests.e2e.test_migrations_and_persistence import new_run
from tests.e2e.test_retrieval_baseline_live import QUERIES, REQUESTERS
from tests.plan_l.test_corpus_files import AS_OF

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("embedded")]

RoleConn = Callable[[Role], Awaitable[persistence.Conn]]


def pins() -> model_pins.EmbeddingPins:
    """The committed pin, read when a test runs (never at collection, so the dev gate does not depend on it)."""
    return model_pins.load_embedding_pins(embeddings.PINS)


async def stored(app_conn: persistence.Conn) -> dict[tuple[UUID, str], dict[str, object]]:
    """Every embedding row of the seeded tenants with its chunk's text, read as the superuser."""
    cur = await app_conn.execute(
        "SELECT c.tenant_id, c.evidence_id, c.section, c.body, e.model, e.model_digest, e.dimension, e.input_sha256,"
        " e.embedding::text AS vector FROM app.chunks c LEFT JOIN app.embeddings e USING (tenant_id, evidence_id)"
        " WHERE c.tenant_id = ANY(%s)",
        (list(corpus_tenants().values()),),
    )
    return {(UUID(str(r["tenant_id"])), str(r["evidence_id"])): dict(r) for r in await cur.fetchall()}


async def test_every_stored_chunk_is_embedded_from_its_prefixed_text_with_the_pinned_model(
    app_conn: persistence.Conn,
) -> None:
    rows = await stored(app_conn)
    assert len(rows) == 69  # corpus-1's sections (docs/retrieval.md)
    for key, row in rows.items():
        text = embeddings.document_text(str(row["section"]), str(row["body"]))
        assert row["input_sha256"] == embeddings.input_sha256(text), key  # the prefix proof (DoD 2)
        assert (row["model"], row["model_digest"], row["dimension"]) == (pins().model, pins().digest, 768), key
        assert len(embeddings.parse_vector(str(row["vector"]))) == 768


async def test_a_stored_vector_is_the_prefixed_texts_embedding_and_not_the_bare_texts(
    app_conn: persistence.Conn,
) -> None:
    alpha = corpus_tenants()["alpha"]
    row = (await stored(app_conn))[(alpha, "ALPHA-PUMP-SEAL:v2:inspection")]
    vector = embeddings.parse_vector(str(row["vector"]))
    section, body = str(row["section"]), str(row["body"])
    embedder = embeddings.OllamaEmbedder.from_settings()
    try:
        bare_text = embeddings.document_text(section, body).removeprefix(embeddings.DOCUMENT_PREFIX)
        fresh, bare = await embedder.embed([embeddings.document_text(section, body), bare_text], pins())
    finally:
        await embedder.aclose()
    assert embeddings.cosine(vector, fresh) >= rc.REPEAT_COSINE  # the stored vector is the prefixed text's (ruling 14)
    assert embeddings.cosine(vector, bare) < rc.REPEAT_COSINE  # and the prefix changed it: about 0.96 when measured


async def test_embed_writes_nothing_twice_and_refuses_a_foreign_digest(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    worker = await role_conn(Role.WORKER)
    embedder = embeddings.OllamaEmbedder.from_settings()
    tenant, run, _ = await handle_for(app_conn, role_conn, None)
    try:
        again = await embed.embed(worker, embedder, pins(), corpus_tenants())
        assert [(r.tenant, r.added) for r in again] == [("alpha", 0), ("beta", 0)]
        assert sum(r.present for r in again) == 69
        now = await clock(app_conn)
        await stage(
            app_conn,
            tenant,
            [
                {"id": "OLD-MODEL", "version": "1", "states": [("approved", now - DAY, None)]},
                {"id": "NOT-YET", "version": "1", "states": [("approved", now - DAY, None)]},
            ],
        )
        await app_conn.execute(
            "INSERT INTO app.embeddings (tenant_id, evidence_id, model, model_digest, dimension, input_sha256,"
            " embedding) SELECT %s, 'OLD-MODEL:v1:turbine', 'nomic-embed-text', %s, 768, %s, embedding"
            " FROM app.embeddings LIMIT 1",
            (tenant, "f" * 64, "1" * 64),
        )
        with pytest.raises(embed.EmbedRefused, match="another model digest"):
            await embed.embed(worker, embedder, pins(), {"probe": tenant})
        cur = await app_conn.execute(
            "SELECT count(*) AS n FROM app.embeddings WHERE tenant_id = %s AND evidence_id = 'NOT-YET:v1:turbine'",
            (tenant,),
        )
        assert (await cur.fetchone() or {})["n"] == 0  # refused: nothing written
    finally:
        await embedder.aclose()
        await cleanup(app_conn, [run], [tenant])


class FailingSecond:
    """The real embedder, except that its second `embed` call fails as an Ollama outage would (round 2, Minor 2)."""

    def __init__(self, real: embeddings.OllamaEmbedder) -> None:
        self.real = real
        self.calls = 0

    async def verify(self, pins: model_pins.EmbeddingPins) -> None:
        await self.real.verify(pins)

    async def embed(self, texts: Sequence[str], pins: model_pins.EmbeddingPins) -> list[embeddings.Vector]:
        self.calls += 1
        if self.calls == 2:
            raise embeddings.Unavailable("the embedding model could not be reached")
        return await self.real.embed(texts, pins)

    async def aclose(self) -> None:
        await self.real.aclose()


async def test_a_failure_while_writing_names_the_tenant_written_and_a_rerun_completes(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    """`embed.embed`'s own wrap: the first tenant commits, the second's model call fails, the error names the first
    and carries the outage as its cause; a re-run writes the second and nothing for the first."""
    worker = await role_conn(Role.WORKER)
    first, first_run, _ = await handle_for(app_conn, role_conn, None)
    second, second_run, _ = await handle_for(app_conn, role_conn, None)
    embedder = embeddings.OllamaEmbedder.from_settings()
    try:
        now = await clock(app_conn)
        for tenant, document in ((first, "FIRST-DOC"), (second, "SECOND-DOC")):
            await stage(app_conn, tenant, [{"id": document, "version": "1", "states": [("approved", now - DAY, None)]}])
        tenants = {"a": first, "b": second}  # embedded in slug order: a, then b
        with pytest.raises(embed.EmbedInterrupted) as caught:
            await embed.embed(worker, FailingSecond(embedder), pins(), tenants)
        assert caught.value.written == ("a",)
        assert isinstance(caught.value.__cause__, embeddings.Unavailable)
        cur = await app_conn.execute(
            "SELECT tenant_id, count(*) AS n FROM app.embeddings WHERE tenant_id = ANY(%s) GROUP BY tenant_id",
            ([first, second],),
        )
        assert {UUID(str(r["tenant_id"])): r["n"] for r in await cur.fetchall()} == {first: 1}  # b rolled back
        again = await embed.embed(worker, embedder, pins(), tenants)
        assert [(r.tenant, r.added, r.present) for r in again] == [("a", 0, 1), ("b", 1, 0)]
    finally:
        await embedder.aclose()
        await cleanup(app_conn, [first_run, second_run], [first, second])


async def test_the_definer_is_exact_against_a_brute_force_ranking(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    """Ruling 7: every development query at the labelling instant, limit 8, vector mode, against Python's ranking of the
    stored vectors of the same permitted set with the same threshold and tie-break."""
    governed = corpus.load(CORPUS)
    cases = rb.load_queries(QUERIES)
    allowed = corpus.returnable(governed, AS_OF)
    tenants = corpus_tenants()
    vectors = {
        (key[0], key[1]): embeddings.parse_vector(str(row["vector"])) for key, row in (await stored(app_conn)).items()
    }
    cur = await app_conn.execute("SELECT app._min_similarity() AS m")
    threshold = float((await cur.fetchone() or {})["m"])
    embedder = embeddings.OllamaEmbedder.from_settings()
    try:
        queries = await embedder.embed([embeddings.query_text(c.query) for c in cases], pins())
    finally:
        await embedder.aclose()
    api, worker, mcp_read = await role_conn(Role.API), await role_conn(Role.WORKER), await role_conn(Role.MCP_READ)
    harness = await role_conn(Role.TEST_HARNESS)
    runs: dict[str, UUID] = {}
    compared = 0
    try:
        await harness.execute("UPDATE app.test_clock SET clock_offset = %s - clock_timestamp()", (AS_OF,))
        for slug, tenant in tenants.items():
            _, _, runs[slug] = await new_run(app_conn, tenant, api=api, requester=REQUESTERS[slug])
        leases = {slug: await lease_for(worker, run, owner="t18-exact", seconds=600) for slug, run in runs.items()}
        for case, query in zip(cases, queries, strict=True):
            run = runs[case.tenant]
            handle = await read_handle(worker, run, await investigate_job(app_conn, run), leases[case.tenant])
            answer = await persistence.search_procedures(
                mcp_read,
                handle=handle,
                azp="ops-worker",
                query=case.query,
                asset_type=case.asset_type,
                limit=8,
                mode="vector",
                embedding=query,
            )
            scored = [
                (d.evidence_id(s), embeddings.cosine(query, vectors[(tenants[case.tenant], d.evidence_id(s))]))
                for d in governed.documents
                if d.tenant == case.tenant
                and d.identity in allowed
                and (case.asset_type is None or d.asset_family in (None, case.asset_type))
                for s in d.sections
            ]
            expected = rc.ranked(scored, threshold, 8)
            assert [h.evidence_id for h in answer.results] == [e for e, _ in expected], case.id
            for hit, (_, similarity) in zip(answer.results, expected, strict=True):
                # pgvector sums in single precision; the order above is exact, the value agrees to float precision.
                assert hit.rank == pytest.approx(similarity, abs=1e-5), case.id
            compared += 1
    finally:
        await harness.execute("UPDATE app.test_clock SET clock_offset = interval '0'")
        for run in runs.values():
            await purge_run(app_conn, run)
    assert compared == len(cases) >= 40

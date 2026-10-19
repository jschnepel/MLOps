"""Revision 0013 against the per-session test database (OPS_LIVE=1; Plan N rulings 1, 5, 6 and 7): the vector branch of
`search_procedures_scoped` called by its real caller, `mcp_read`, over rows and synthetic vectors the superuser stages
in random tenants (the real embeddings are tests/e2e/test_vector_retrieval_live.py's).

Catches: a vector answer that is not ordered by cosine similarity, breaks ties other than by evidence_id in byte
order, keeps a similarity at or below `app._min_similarity()`, or returns a superseded, draft, not-yet-effective or
other-family section (the same filters as lexical); another tenant's embedding used; a vector call without an
embedding, with another dimension or a zero vector, or a lexical call with one, answered instead of refused
BAD_ARGUMENT; a permitted chunk without an embedding silently left out instead of EMBEDDINGS_INCOMPLETE (while a draft
chunk without one changes nothing); an empty corpus answered other than `[]`; any role but the worker able to write
an embedding, the worker able to change or delete one or to write another tenant's, a zero vector stored; and a
downgrade that leaves the table or the helper behind, does not restore 0012's body with the same grant, or does not
come back exactly.
"""

import importlib.util
import math
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
import pytest
from ops_core import embeddings, persistence, settings
from ops_core.settings import Profile, Role

from tests.e2e.test_definers_run_path_live import refused
from tests.e2e.test_migration_0011_live import APP_FUNCTIONS, DAY, cleanup, clock, handle_for, stage

pytestmark = pytest.mark.asyncio

RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
AZP = "ops-worker"
CALL = "SELECT * FROM app.search_procedures_scoped(%s, %s, %s, %s::public.vector, %s, %s, %s)"


def direction(similarity: float, axis: int = 1) -> list[float]:
    """A unit vector whose cosine with the first axis is `similarity`, turned towards `axis` (768 dimensions)."""
    vector = [0.0] * embeddings.DIMENSION
    vector[0] = similarity
    vector[axis] = math.sqrt(1 - similarity * similarity)
    return vector


QUERY = direction(1.0)  # the first axis


async def embed_rows(app_conn: persistence.Conn, tenant: UUID, vectors: dict[str, Sequence[float]]) -> None:
    """Synthetic embedding rows written by the superuser (Plan N ruling 13), one per staged evidence ID."""
    for evidence_id, vector in vectors.items():
        await app_conn.execute(
            "INSERT INTO app.embeddings (tenant_id, evidence_id, model, model_digest, dimension, input_sha256,"
            " embedding) VALUES (%s, %s, 'nomic-embed-text', %s, 768, %s, %s::public.vector)",
            (tenant, evidence_id, "0" * 64, "1" * 64, embeddings.vector_literal(vector)),
        )


async def minimum(app_conn: persistence.Conn) -> float:
    cur = await app_conn.execute("SELECT app._min_similarity() AS m")
    return float((await cur.fetchone() or {})["m"])


async def vector_ids(mcp_read: persistence.Conn, handle: str, **over: Any) -> list[tuple[str, float]]:
    answer = await persistence.search_procedures(
        mcp_read,
        handle=handle,
        azp=AZP,
        query="any text",
        asset_type=over.get("asset_type"),
        limit=over.get("limit", 8),
        mode="vector",
        embedding=over.get("embedding", QUERY),
    )
    return [(hit.evidence_id, hit.rank) for hit in answer.results]


async def test_vector_mode_ranks_the_permitted_chunks_by_cosine_with_lexicals_filters(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    mcp_read = await role_conn(Role.MCP_READ)
    tenant, run, handle = await handle_for(app_conn, role_conn, None)
    other, other_run, _ = await handle_for(app_conn, role_conn, None)
    try:
        now = await clock(app_conn)
        low = await minimum(app_conn)
        assert 0.0 <= low <= 0.8  # the geometry below needs room above the minimum (0.68 when frozen)
        old, recent = [("approved", now - 30 * DAY, None)], [("approved", now - DAY, None)]
        await stage(
            app_conn,
            tenant,
            [
                {"id": "BEST", "version": "1", "states": old, "section": "best"},
                {"id": "TIE-B", "version": "1", "states": old, "section": "tie"},
                {"id": "TIE-A", "version": "1", "states": old, "section": "tie"},
                {"id": "EDGE", "version": "1", "states": old, "section": "edge"},
                {"id": "BELOW", "version": "1", "states": old, "section": "below"},
                {"id": "PUMP-ONLY", "version": "1", "states": old, "section": "pump", "family": "pump"},
                {"id": "RETIRED", "version": "1", "states": old, "section": "old"},
                {"id": "RETIRED", "version": "2", "supersedes": "1", "states": recent, "section": "new"},
                {"id": "DRAFT", "version": "1", "states": [("draft", now - DAY, None)], "section": "draft"},
                {"id": "LATER", "version": "1", "states": [("approved", now + DAY, None)], "section": "later"},
            ],
        )
        await embed_rows(
            app_conn,
            tenant,
            {
                "BEST:v1:best": QUERY,
                "TIE-B:v1:tie": direction(low + 0.1, 2),
                "TIE-A:v1:tie": direction(low + 0.1, 3),  # the same similarity: byte order decides
                "EDGE:v1:edge": direction(low + 0.02),
                "BELOW:v1:below": direction(low - 0.02),  # under the minimum: dropped
                "PUMP-ONLY:v1:pump": direction(0.99),
                "RETIRED:v1:old": QUERY,  # retired by v2, whatever its similarity
                "RETIRED:v2:new": direction(0.95),
                "DRAFT:v1:draft": QUERY,
                "LATER:v1:later": QUERY,
            },
        )
        await stage(app_conn, other, [{"id": "FOREIGN", "version": "1", "states": old, "section": "foreign"}])
        await embed_rows(app_conn, other, {"FOREIGN:v1:foreign": QUERY})  # another tenant's: never seen
        found = await vector_ids(mcp_read, handle)
        assert [e for e, _ in found] == [
            "BEST:v1:best",
            "PUMP-ONLY:v1:pump",  # no asset type asked: any family
            "RETIRED:v2:new",
            "TIE-A:v1:tie",
            "TIE-B:v1:tie",
            "EDGE:v1:edge",
        ]
        assert found[0][1] == pytest.approx(1.0, abs=1e-6) and found[-1][1] == pytest.approx(low + 0.02, abs=1e-5)
        assert [e for e, _ in await vector_ids(mcp_read, handle, asset_type="valve", limit=2)] == [
            "BEST:v1:best",
            "RETIRED:v2:new",
        ]
        assert await vector_ids(mcp_read, handle, embedding=direction(0.0, 5)) == []  # nothing similar enough
        lexical = await persistence.search_procedures(
            mcp_read, handle=handle, azp=AZP, query="turbine", asset_type=None, limit=8
        )
        vector = await persistence.search_procedures(
            mcp_read, handle=handle, azp=AZP, query="turbine", asset_type=None, limit=8, mode="vector", embedding=QUERY
        )
        # The same answer shape in both modes (ruling 5): corpus version, instant and every key but the score's meaning.
        assert (
            (vector.corpus_version, vector.truncated)
            == (lexical.corpus_version, lexical.truncated)
            == ("live-1", False)
        )
        assert abs((vector.retrieved_at - lexical.retrieved_at).total_seconds()) < 5
    finally:
        await cleanup(app_conn, [run, other_run], [tenant, other])


async def test_arguments_completeness_and_the_empty_corpus(app_conn: persistence.Conn, role_conn: RoleConn) -> None:
    mcp_read = await role_conn(Role.MCP_READ)
    tenant, run, handle = await handle_for(app_conn, role_conn, None)
    try:
        assert await vector_ids(mcp_read, handle) == []  # no corpus yet: [] as lexical answers
        now = await clock(app_conn)
        old = [("approved", now - 30 * DAY, None)]
        await stage(
            app_conn,
            tenant,
            [
                {"id": "KEPT", "version": "1", "states": old},
                {"id": "MISSING", "version": "1", "states": old},
                {"id": "DRAFT", "version": "1", "states": [("draft", now - DAY, None)]},
            ],
        )
        await embed_rows(app_conn, tenant, {"KEPT:v1:turbine": QUERY})
        with pytest.raises(persistence.Refused, match="EMBEDDINGS_INCOMPLETE"):  # never a silent omission
            await vector_ids(mcp_read, handle)
        await embed_rows(app_conn, tenant, {"MISSING:v1:turbine": direction(0.99)})
        assert [e for e, _ in await vector_ids(mcp_read, handle)] == ["KEPT:v1:turbine", "MISSING:v1:turbine"]
        # The draft has no embedding and is not permitted: it changes nothing.
        literal = embeddings.vector_literal
        for args in (
            (handle, AZP, "turbine", None, None, 5, "vector"),  # no embedding
            (handle, AZP, "turbine", literal([1.0, 0.0, 0.0]), None, 5, "vector"),  # three dimensions
            (handle, AZP, "turbine", literal([0.0] * 768), None, 5, "vector"),  # no direction
            (handle, AZP, "turbine", literal(QUERY), None, 5, "lexical"),  # an embedding in lexical mode
            (handle, AZP, "", literal(QUERY), None, 5, "vector"),  # the text query is still bounded
            (handle, AZP, "turbine", literal(QUERY), None, 9, "vector"),
            (handle, AZP, "turbine", literal(QUERY), None, 5, "approximate"),
        ):
            with pytest.raises(persistence.Refused, match="BAD_ARGUMENT"):
                await persistence._call(mcp_read, CALL, args)
        with pytest.raises(persistence.HandleRejected):  # the handle is checked before any argument
            await persistence._call(mcp_read, CALL, ("not-a-handle", AZP, "turbine", literal(QUERY), None, 5, "vector"))
    finally:
        await cleanup(app_conn, [run], [tenant])


async def test_only_the_worker_writes_embeddings_and_only_its_tenants(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    tenant, run, _ = await handle_for(app_conn, role_conn, None)
    other, other_run, _ = await handle_for(app_conn, role_conn, None)
    try:
        now = await clock(app_conn)
        await stage(app_conn, tenant, [{"id": "OWN", "version": "1", "states": [("approved", now - DAY, None)]}])
        await stage(app_conn, other, [{"id": "THEIRS", "version": "1", "states": [("approved", now - DAY, None)]}])
        insert = (
            "INSERT INTO app.embeddings (tenant_id, evidence_id, model, model_digest, dimension, input_sha256,"
            " embedding) VALUES (%s, %s, 'nomic-embed-text', %s, 768, %s, %s::public.vector)"
        )
        row = (tenant, "OWN:v1:turbine", "0" * 64, "1" * 64, embeddings.vector_literal(QUERY))
        with pytest.raises(psycopg.errors.CheckViolation):  # not even the superuser stores a zero vector
            await app_conn.execute(insert, (*row[:4], embeddings.vector_literal([0.0] * 768)))
        for role in (Role.API, Role.SWEEPER, Role.MCP_READ, Role.MCP_EXEC, Role.OPERATOR):
            assert await refused(await role_conn(role), "SELECT 1 FROM app.embeddings", ()) == "42501", role
            assert await refused(await role_conn(role), insert, row) == "42501", role
        worker = await role_conn(Role.WORKER)
        async with worker.transaction():
            await persistence.set_tenant(worker, tenant)
            await worker.execute(insert, row)  # AM-20.2's ingestion cell (SA:431)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):  # RLS WITH CHECK: another tenant's row
            async with worker.transaction():
                await persistence.set_tenant(worker, tenant)
                await worker.execute(insert, (other, "THEIRS:v1:turbine", *row[2:]))
        cur = await worker.execute("SELECT count(*) AS n FROM app.embeddings")
        assert (await cur.fetchone() or {})["n"] == 0  # no tenant set: RLS admits nothing
        for statement in ("UPDATE app.embeddings SET dimension = 768", "DELETE FROM app.embeddings"):
            assert await refused(worker, statement, ()) == "42501", statement  # append-only
    finally:
        await cleanup(app_conn, [run, other_run], [tenant, other])


def revision_0013() -> Any:
    path = Path(__file__).resolve().parents[2] / "migrations" / "app" / "versions" / "0013_embeddings.py"
    spec = importlib.util.spec_from_file_location("live_rev_0013", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def snapshot(conn: persistence.Conn) -> dict[str, dict[str, Any]]:
    cur = await conn.execute(APP_FUNCTIONS)
    return {row["signature"]: {k: v for k, v in row.items() if k != "signature"} for row in await cur.fetchall()}


async def test_the_round_trip_restores_0012(app_conn: persistence.Conn, role_conn: RoleConn) -> None:
    from scripts.skeleton import downgrade, migrate

    module = revision_0013()
    search = f"app.search_procedures_scoped({module.SEARCH_ARGS})"
    superuser = settings.superuser_postgres()
    mcp_read = await role_conn(Role.MCP_READ)
    head = await snapshot(app_conn)
    assert any(s.startswith("app._min_similarity(") for s in head)
    await persistence.assert_function_text(mcp_read, *persistence.VECTOR_SEARCH)  # mcp-read starts on the head
    try:
        downgrade("app", superuser, "0012_asset_scope")
        cur = await app_conn.execute("SELECT to_regclass('app.embeddings') IS NULL AS gone")
        assert (await cur.fetchone() or {})["gone"]
        after = await snapshot(app_conn)
        assert set(after) == {s for s in head if not s.startswith("app._min_similarity(")}
        cur = await app_conn.execute("SELECT prosrc FROM pg_proc WHERE oid = %s::regprocedure", (search,))
        assert (await cur.fetchone() or {})["prosrc"] == module.BODY_0012.split("$fn$")[1]
        for signature, details in after.items():
            if signature.startswith("app.search_procedures_scoped("):
                assert details["acl"] == head[signature]["acl"]  # CREATE OR REPLACE kept the grant, both ways
            else:
                assert details == head[signature], signature
        with pytest.raises(persistence.PersistenceError, match="predates this service"):
            await persistence.assert_function_text(mcp_read, *persistence.VECTOR_SEARCH)  # mcp-read refuses 0012
    finally:
        assert migrate(Profile.TEST) == 0  # every later test needs the head (the `embedded` fixture re-embeds)
    assert await snapshot(app_conn) == head

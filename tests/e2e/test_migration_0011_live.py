"""Revision 0011 against the per-session test database (OPS_LIVE=1; Plan L rulings 1-3, 7, 8, 10, 11, 18 and 24),
`search_procedures_scoped` called by its real caller, `mcp_read`, over rows the superuser stages directly (the
ingestion runner is tested on its own in test_ingest_live.py).

Catches: a superseded, expired, revoked, draft or not-yet-effective version returned; a retired version returned (a
later version that left draft and reached its effective_from retires every earlier one for good, ruling 7 as round 1
amended it), and a draft or not-yet-effective successor retiring anything; a rank at or below `app._min_rank()`
kept; a lifecycle read from the oldest state row instead of the latest; an
effective interval compared with the server's `now()` instead of `app.current_time()`; another tenant's chunk, or a
chunk of another asset family, returned; ties ordered differently on a retry; a limit, a stop-word query, the vector
mode or a dead handle answered with rows; any runtime role other than `mcp_read` able to call the function; the worker
reading another tenant's corpus or changing a stored row; and a downgrade that leaves a table, an index or a function
of 0011 behind (the list comes from the revision's own frozen tuples, so a later helper cannot be forgotten here),
removes the bootstrap's `vector` extension, or does not come back exactly with the upgrade.
"""

import importlib.util
import re
from collections.abc import Awaitable, Callable
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
import pytest
from ops_core import persistence, settings
from ops_core.settings import Profile, Role

from tests.e2e.conftest import lease_for, purge_corpus, purge_run, purge_tenant
from tests.e2e.test_definers_run_path_live import refused
from tests.e2e.test_fenced_definers_live import investigate_job, read_handle
from tests.e2e.test_migrations_and_persistence import new_run

pytestmark = pytest.mark.asyncio

RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
AZP = "ops-worker"
LOCK = "a" * 64
DAY = timedelta(days=1)
APP_FUNCTIONS = (
    "SELECT p.oid::regprocedure::text AS signature, pg_get_functiondef(p.oid) AS body, p.proacl::text AS acl"
    " FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = 'app'"
)


async def clock(app_conn: persistence.Conn) -> Any:
    cur = await app_conn.execute("SELECT app.current_time() AS now")
    return (await cur.fetchone() or {})["now"]


async def stage(
    app_conn: persistence.Conn,
    tenant: UUID,
    documents: list[dict[str, Any]],
) -> None:
    """Write one ingestion row and each document with its state rows and one section, as the superuser.

    Each document is a dict: `id`, `version`, `states` (a list of (status, effective_from, effective_to)), and
    optionally `supersedes`, `family`, `text` (default: a sentence with the shared word the tests search for) and
    `section` (default `turbine`: a heading word weighs 1.0 in the rank, well above the 0.25 minimum, where one
    body occurrence weighs 0.1).
    """
    await app_conn.execute(
        "INSERT INTO app.corpus_ingestions (tenant_id, seq, corpus_version, lock_sha256, documents_added,"
        " states_added) VALUES (%s, 1, 'live-1', %s, %s, %s)",
        (tenant, LOCK, len(documents), sum(len(d["states"]) for d in documents)),
    )
    for doc in documents:
        await app_conn.execute(
            "INSERT INTO app.documents (tenant_id, document_id, version, path, content_sha256, asset_family, label,"
            " supersedes, conflicts_with, ingestion_seq) VALUES (%s, %s, %s, %s, %s, %s, 'normal', %s, NULL, 1)",
            (
                tenant,
                doc["id"],
                doc["version"],
                f"{doc['id'].lower()}-v{doc['version']}.md",
                "b" * 64,
                doc.get("family"),
                doc.get("supersedes"),
            ),
        )
        for seq, (status, start, end) in enumerate(doc["states"], start=1):
            await app_conn.execute(
                "INSERT INTO app.document_states (tenant_id, document_id, version, seq, status, effective_from,"
                " effective_to, ingestion_seq) VALUES (%s, %s, %s, %s, %s, %s, %s, 1)",
                (tenant, doc["id"], doc["version"], seq, status, start, end),
            )
        text = doc.get("text", "The turbine casing is inspected for cracks.")
        section = doc.get("section", "turbine")
        await app_conn.execute(
            "INSERT INTO app.chunks (tenant_id, document_id, version, ordinal, section, evidence_id, body,"
            " content_sha256, start_offset, end_offset, word_count)"
            " VALUES (%s, %s, %s, 1, %s, %s, %s, %s, 10, %s, %s)",
            (
                tenant,
                doc["id"],
                doc["version"],
                section,
                f"{doc['id']}:v{doc['version']}:{section}",
                text,
                "c" * 64,
                10 + len(text),
                len(text.split()),
            ),
        )


async def handle_for(app_conn: persistence.Conn, role_conn: RoleConn, tenant: UUID | None) -> tuple[UUID, UUID, str]:
    """A run in `tenant` (a fresh random tenant when None), its lease and a read handle: (tenant, run, handle)."""
    api, worker = await role_conn(Role.API), await role_conn(Role.WORKER)
    tenant_id, _, run = await new_run(app_conn, tenant, api=api)
    lease = await lease_for(worker, run, owner="t17-live", seconds=600)
    return tenant_id, run, await read_handle(worker, run, await investigate_job(app_conn, run), lease)


async def found(mcp_read: persistence.Conn, handle: str, query: str = "turbine", **over: Any) -> list[str]:
    """The evidence ids `search_procedures_scoped` returns, best first."""
    answer = await persistence.search_procedures(
        mcp_read,
        handle=handle,
        azp=AZP,
        query=query,
        asset_type=over.get("asset_type"),
        limit=over.get("limit", 8),
    )
    return [hit.evidence_id for hit in answer.results]


async def cleanup(app_conn: persistence.Conn, runs: list[UUID], tenants: list[UUID]) -> None:
    for run in runs:
        await purge_run(app_conn, run)
    for tenant in tenants:
        await purge_corpus(app_conn, tenant)
        await purge_tenant(app_conn, tenant)


async def test_only_approved_effective_unretired_versions_are_returned(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    mcp_read, harness = await role_conn(Role.MCP_READ), await role_conn(Role.TEST_HARNESS)
    tenant, run, handle = await handle_for(app_conn, role_conn, None)
    runs, tenants = [run], [tenant]
    try:
        now = await clock(app_conn)
        await stage(
            app_conn,
            tenant,
            [
                {"id": "DOC-A", "version": "1", "states": [("approved", now - 30 * DAY, None)]},
                {"id": "DOC-A", "version": "2", "supersedes": "1", "states": [("approved", now - DAY, None)]},
                {"id": "DOC-B", "version": "1", "states": [("approved", now - 30 * DAY, now - DAY)]},  # expired
                {"id": "DOC-C", "version": "1", "states": [("revoked", now - 30 * DAY, None)]},
                {"id": "DOC-D", "version": "1", "states": [("draft", now - 30 * DAY, None)]},
                {"id": "DOC-E", "version": "1", "states": [("approved", now + DAY, None)]},  # not yet effective
                {"id": "DOC-F", "version": "1", "states": [("superseded", now - 30 * DAY, None)]},
                # The latest state row decides, never the first: approved then revoked, draft then approved.
                {
                    "id": "DOC-G",
                    "version": "1",
                    "states": [("approved", now - 30 * DAY, None), ("revoked", now - 30 * DAY, None)],
                },
                {
                    "id": "DOC-H",
                    "version": "1",
                    "states": [("draft", now - 30 * DAY, None), ("approved", now - 30 * DAY, None)],
                },
                # A successor that is not effective yet retires nothing.
                {"id": "DOC-I", "version": "1", "states": [("approved", now - 30 * DAY, None)]},
                {"id": "DOC-I", "version": "2", "supersedes": "1", "states": [("approved", now + DAY, None)]},
            ],
        )
        assert await found(mcp_read, handle) == ["DOC-A:v2:turbine", "DOC-H:v1:turbine", "DOC-I:v1:turbine"]
        try:
            # Two days on the database clock (ruling 8): DOC-E and DOC-I v2 become effective. The lease lapsed with
            # the move, so the handle is minted again under a new one (Global Constraints, "Clock").
            await harness.execute("UPDATE app.test_clock SET clock_offset = interval '2 days'")
            worker = await role_conn(Role.WORKER)
            lease = await lease_for(worker, run, owner="t17-later", seconds=600)
            later = await read_handle(worker, run, await investigate_job(app_conn, run), lease)
            expected = ["DOC-A:v2:turbine", "DOC-E:v1:turbine", "DOC-H:v1:turbine", "DOC-I:v2:turbine"]
            assert await found(mcp_read, later) == expected
        finally:
            await harness.execute("UPDATE app.test_clock SET clock_offset = interval '0'")
    finally:
        await cleanup(app_conn, runs, tenants)


async def test_the_handle_decides_the_tenant_and_the_asset_type_filters(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    mcp_read = await role_conn(Role.MCP_READ)
    first, run, handle = await handle_for(app_conn, role_conn, None)
    other, other_run, other_handle = await handle_for(app_conn, role_conn, None)
    empty, empty_run, empty_handle = await handle_for(app_conn, role_conn, None)
    runs, tenants = [run, other_run, empty_run], [first, other, empty]
    try:
        now = await clock(app_conn)
        always = [("approved", now - 30 * DAY, None)]
        await stage(
            app_conn,
            first,
            [
                {"id": "PUMP-DOC", "version": "1", "family": "pump", "states": always},
                {"id": "SHARED-DOC", "version": "1", "states": always},
                {"id": "COMPRESSOR-DOC", "version": "1", "family": "compressor", "states": always},
            ],
        )
        await stage(app_conn, other, [{"id": "OTHER-DOC", "version": "1", "states": always}])
        assert await found(mcp_read, handle) == [
            "COMPRESSOR-DOC:v1:turbine",
            "PUMP-DOC:v1:turbine",
            "SHARED-DOC:v1:turbine",
        ]
        assert await found(mcp_read, other_handle) == ["OTHER-DOC:v1:turbine"]  # the other tenant's handle, its own
        assert await found(mcp_read, handle, asset_type="pump") == ["PUMP-DOC:v1:turbine", "SHARED-DOC:v1:turbine"]
        assert await found(mcp_read, handle, asset_type="valve") == ["SHARED-DOC:v1:turbine"]  # NULL means any asset
        answer = await persistence.search_procedures(
            mcp_read, handle=handle, azp=AZP, query="turbine", asset_type=None, limit=8
        )
        assert answer.corpus_version == "live-1"
        nothing = await persistence.search_procedures(
            mcp_read, handle=empty_handle, azp=AZP, query="turbine", asset_type=None, limit=8
        )
        assert (nothing.corpus_version, nothing.results) == ("none", ())  # a tenant never ingested
    finally:
        await cleanup(app_conn, runs, tenants)


async def test_ties_limits_and_refusals(app_conn: persistence.Conn, role_conn: RoleConn) -> None:
    mcp_read = await role_conn(Role.MCP_READ)
    tenant, run, handle = await handle_for(app_conn, role_conn, None)
    try:
        now = await clock(app_conn)
        always = [("approved", now - 30 * DAY, None)]
        same = "Check the turbine casing and the turbine bearing."
        await stage(
            app_conn,
            tenant,
            [
                {"id": "TIE-B", "version": "1", "states": always, "text": same, "section": "body"},
                {"id": "TIE-A", "version": "1", "states": always, "text": same, "section": "body"},
                {
                    "id": "TIE-C",
                    "version": "1",
                    "states": always,
                    "text": "Only the casing is mentioned here.",
                    "section": "body",
                },
            ],
        )
        # Equal ranks come back in evidence_id order, and the same call answers the same way (BUILD_SPEC section 6).
        assert await found(mcp_read, handle, "turbine bearing") == ["TIE-A:v1:body", "TIE-B:v1:body"]
        assert await found(mcp_read, handle, "turbine bearing") == ["TIE-A:v1:body", "TIE-B:v1:body"]
        assert await found(mcp_read, handle, "turbine casing", limit=1) == ["TIE-A:v1:body"]
        assert await found(mcp_read, handle, "the and of") == []  # stop words only: no lexeme, no rows
        hits = (
            await persistence.search_procedures(
                mcp_read, handle=handle, azp=AZP, query="Turbine!!! casing??", asset_type=None, limit=8
            )
        ).results
        # A and B hold three query words in their bodies (rank 0.3 each); C holds one (0.1), at or below the minimum
        # rank of 0.25, so it is dropped although it matches (Plan L ruling 18, round 1).
        assert [h.evidence_id for h in hits] == ["TIE-A:v1:body", "TIE-B:v1:body"]
        assert hits[0].rank == hits[1].rank > 0.25 and hits[0].excerpt == same
        call = "SELECT * FROM app.search_procedures_scoped(%s, %s, %s, NULL, NULL, %s, %s)"
        with pytest.raises(persistence.Refused, match="VECTOR_MODE_UNAVAILABLE"):
            await persistence._call(mcp_read, call, (handle, AZP, "turbine", 5, "vector"))
        with pytest.raises(persistence.Refused, match="BAD_ARGUMENT"):
            await persistence._call(mcp_read, call, (handle, AZP, "turbine", 9, "lexical"))
        with pytest.raises(persistence.HandleRejected):
            await persistence._call(mcp_read, call, ("not-a-handle", AZP, "turbine", 5, "lexical"))
        with pytest.raises(persistence.HandleRejected):
            await persistence._call(mcp_read, call, (handle, "ops-mcp-read", "turbine", 5, "lexical"))  # another azp
    finally:
        await cleanup(app_conn, [run], [tenant])


async def test_a_retired_version_never_comes_back(app_conn: persistence.Conn, role_conn: RoleConn) -> None:
    """Ruling 7 as round 1 amended it, at the definer, on the shapes the round-1 review found; the loader refuses the
    first two in a catalog, so they are staged directly. Each predecessor stays out."""
    mcp_read = await role_conn(Role.MCP_READ)
    tenant, run, handle = await handle_for(app_conn, role_conn, None)
    try:
        now = await clock(app_conn)
        old = [("approved", now - 30 * DAY, None)]
        await stage(
            app_conn,
            tenant,
            [
                # (a) a successor without `supersedes`
                {"id": "NO-LINK", "version": "1", "states": old},
                {"id": "NO-LINK", "version": "2", "states": [("approved", now - DAY, None)]},
                # (b) a successor naming an older version than its predecessor
                {"id": "WRONG-LINK", "version": "1", "states": old},
                {"id": "WRONG-LINK", "version": "2", "supersedes": "1", "states": [("approved", now - 2 * DAY, None)]},
                {"id": "WRONG-LINK", "version": "3", "supersedes": "1", "states": [("approved", now - DAY, None)]},
                # (c) a gap: the middle version revoked
                {"id": "GAP", "version": "1", "states": old},
                {"id": "GAP", "version": "2", "supersedes": "1", "states": [("revoked", now - 2 * DAY, None)]},
                {"id": "GAP", "version": "3", "supersedes": "2", "states": [("approved", now - DAY, None)]},
                # (d) the successor revoked after it took effect: nothing comes back
                {"id": "REVOKED-NEXT", "version": "1", "states": old},
                {
                    "id": "REVOKED-NEXT",
                    "version": "2",
                    "supersedes": "1",
                    "states": [("approved", now - DAY, None), ("revoked", now - DAY, None)],
                },
                # An expired successor retires for good; a draft one retires nothing; versions compare as numbers.
                {"id": "EXPIRED-NEXT", "version": "1", "states": old},
                {
                    "id": "EXPIRED-NEXT",
                    "version": "2",
                    "supersedes": "1",
                    "states": [("approved", now - 10 * DAY, now - DAY)],
                },
                {"id": "DRAFT-NEXT", "version": "1", "states": old},
                {"id": "DRAFT-NEXT", "version": "2", "supersedes": "1", "states": [("draft", now - DAY, None)]},
                {"id": "NUMBERS", "version": "9", "states": old},
                {"id": "NUMBERS", "version": "10", "supersedes": "9", "states": [("approved", now - DAY, None)]},
            ],
        )
        assert await found(mcp_read, handle) == [
            "DRAFT-NEXT:v1:turbine",
            "GAP:v3:turbine",
            "NO-LINK:v2:turbine",
            "NUMBERS:v10:turbine",
            "WRONG-LINK:v3:turbine",
        ]
    finally:
        await cleanup(app_conn, [run], [tenant])


async def test_only_mcp_read_calls_it_and_the_worker_sees_its_tenant_only(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    call = "SELECT * FROM app.search_procedures_scoped(%s, 'ops-worker', 'turbine', NULL, NULL, 1, 'lexical')"
    for role in (Role.API, Role.WORKER, Role.SWEEPER, Role.MCP_EXEC, Role.OPERATOR):
        assert await refused(await role_conn(role), call, ("not-a-handle",)) == "42501", role
    tenant, run, _ = await handle_for(app_conn, role_conn, None)
    other, other_run, _ = await handle_for(app_conn, role_conn, None)
    try:
        now = await clock(app_conn)
        await stage(app_conn, tenant, [{"id": "SEEN-DOC", "version": "1", "states": [("approved", now - DAY, None)]}])
        # A second tenant's chunk: a policy that ignored the tenant setting would count 2 below.
        await stage(app_conn, other, [{"id": "HIDDEN-DOC", "version": "1", "states": [("approved", now - DAY, None)]}])
        worker = await role_conn(Role.WORKER)
        cur = await worker.execute("SELECT count(*) AS n FROM app.chunks")
        assert (await cur.fetchone() or {})["n"] == 0  # no tenant set: RLS admits nothing (defense in depth, SA:522)
        async with worker.transaction():
            await persistence.set_tenant(worker, tenant)
            cur = await worker.execute("SELECT count(*) AS n FROM app.chunks")
            assert (await cur.fetchone() or {})["n"] == 1
        for statement in ("UPDATE app.chunks SET body = 'x'", "DELETE FROM app.document_states"):
            assert await refused(worker, statement, ()) == "42501", statement  # append-only: no UPDATE, no DELETE
    finally:
        await cleanup(app_conn, [run, other_run], [tenant, other])


async def snapshot(conn: persistence.Conn) -> dict[str, dict[str, Any]]:
    cur = await conn.execute(APP_FUNCTIONS)
    return {row["signature"]: {k: v for k, v in row.items() if k != "signature"} for row in await cur.fetchall()}


def revision_0011() -> Any:
    """Revision 0011 loaded by path: its frozen tables, index statements and functions are what the round trip
    must remove and restore (round 2, B1)."""
    path = Path(__file__).resolve().parents[2] / "migrations" / "app" / "versions" / "0011_governed_corpus.py"
    spec = importlib.util.spec_from_file_location("live_rev_0011", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


REVISION = revision_0011()
OWN_FUNCTIONS = tuple(f"app.{name}(" for name, _, _, _ in REVISION.FUNCTIONS)
OWN_RELATIONS = tuple(f"app.{table}" for table in REVISION.TABLES_0011) + tuple(
    f"app.{m.group(1)}" for s in REVISION.SCHEMA_CHANGES if (m := re.match(r"CREATE INDEX (\w+) ON", s))
)


async def relations(conn: persistence.Conn) -> dict[str, bool]:
    names = OWN_RELATIONS
    out = {}
    for name in names:
        cur = await conn.execute("SELECT to_regclass(%s) IS NOT NULL AS present", (name,))
        out[name] = bool((await cur.fetchone() or {})["present"])
    return out


async def test_the_round_trip_restores_0010_and_keeps_the_extension(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    from scripts.skeleton import downgrade, migrate

    superuser = settings.superuser_postgres()
    mcp_read = await role_conn(Role.MCP_READ)
    head = await snapshot(app_conn)
    assert OWN_FUNCTIONS == ("app._min_rank(", "app.search_procedures_scoped(")
    assert all(any(s.startswith(own) for s in head) for own in OWN_FUNCTIONS)
    assert len(OWN_RELATIONS) == 5 and all((await relations(app_conn)).values())  # four tables and the GIN index
    await persistence.assert_function_text(mcp_read, *persistence.GOVERNED_CORPUS)  # mcp-read starts on the head
    try:
        downgrade("app", superuser, "0010_write_path")
        assert not any((await relations(app_conn)).values())
        after = await snapshot(app_conn)
        assert not any(s.startswith(OWN_FUNCTIONS) for s in after)
        assert {s for s in head if not s.startswith(OWN_FUNCTIONS)} == set(after)
        cur = await app_conn.execute("SELECT to_regtype('public.vector') IS NOT NULL AS present")
        assert (await cur.fetchone() or {})["present"]  # the bootstrap's extension stays
        with pytest.raises(persistence.PersistenceError, match="predates this service"):
            await persistence.assert_function_text(mcp_read, *persistence.GOVERNED_CORPUS)  # mcp-read refuses 0010
    finally:
        assert migrate(Profile.TEST) == 0  # every later test needs the head
    assert await snapshot(app_conn) == head
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        await mcp_read.execute("SELECT 1 FROM app.chunks LIMIT 1")  # mcp_read holds no table grant (SA:437)

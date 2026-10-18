"""Ingestion as role `worker` against the per-session test database (OPS_LIVE=1; R032; Plan L rulings 5-8).

The committed corpus is ingested into two fresh tenants from a copy whose catalog names a test version, so the rules
can be exercised by editing the copy without touching `data/corpus` or the seeded tenants' corpus. Catches: a
repeated ingestion that writes a row; a changed file under the same version that is stored, or that leaves any row
behind in any tenant (the whole run is refused before anything is written); a revoked version still retrieved, or
brought back by a later catalog; a successor pulled back to draft or postponed, which would bring its retired
predecessor back (both refused, round 2); a new approved version that does not supersede its predecessor at
retrieval; a tool
answer that names an older corpus version than the tenant's latest ingestion; and a seeded tenant whose ingested
corpus differs from the committed catalog.
"""

import json
import shutil
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from ops_core import corpus, ingest, persistence
from ops_core.lease import Lease
from ops_core.settings import Role

from scripts import gen_corpus_meta
from scripts.skeleton import CORPUS, corpus_tenants
from tests.e2e.conftest import lease_for, purge_corpus, purge_run, purge_tenant
from tests.e2e.test_fenced_definers_live import investigate_job, read_handle
from tests.e2e.test_migrations_and_persistence import new_run

pytestmark = pytest.mark.asyncio

RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
TABLES = ("corpus_ingestions", "documents", "document_states", "chunks")


def edit(root: Path, version: str, change: Callable[[dict[str, Any]], None] | None = None) -> corpus.Corpus:
    """Rewrite the copy's catalog (`change` edits it in place), name `version`, re-lock and load it unreleased."""
    path = root / corpus.CATALOG
    catalog = json.loads(path.read_text(encoding="utf-8"))
    catalog["corpus_version"] = version
    if change is not None:
        change(catalog)
    path.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8", newline="\n")
    gen_corpus_meta.write_lock(root)
    return corpus.load(root, released=None)


def entry(catalog: dict[str, Any], document_id: str, version: str = "1") -> dict[str, Any]:
    return next(d for d in catalog["documents"] if (d["document_id"], d["version"]) == (document_id, version))


async def counts(app_conn: persistence.Conn, tenants: list[UUID]) -> dict[str, int]:
    out = {}
    for table in TABLES:
        cur = await app_conn.execute(f"SELECT count(*) AS n FROM app.{table} WHERE tenant_id = ANY(%s)", (tenants,))
        out[table] = int((await cur.fetchone() or {})["n"])
    return out


async def search(
    app_conn: persistence.Conn, role_conn: RoleConn, run: UUID, lease: Lease, query: str
) -> persistence.Procedures:
    """The definer's answer for a fresh read handle of `run` under the test's one lease (a handle lives 60 s, so
    one per call; a second lease would be refused as busy while the first is live)."""
    worker = await role_conn(Role.WORKER)
    handle = await read_handle(worker, run, await investigate_job(app_conn, run), lease)
    return await persistence.search_procedures(
        await role_conn(Role.MCP_READ), handle=handle, azp="ops-worker", query=query, asset_type=None, limit=8
    )


async def test_r032_repeat_change_revoke_and_supersede(
    app_conn: persistence.Conn, role_conn: RoleConn, tmp_path: Path
) -> None:
    alpha, beta = uuid4(), uuid4()
    for tenant in (alpha, beta):
        await app_conn.execute("INSERT INTO app.tenants (tenant_id, name) VALUES (%s, %s)", (tenant, f"t-{tenant}"))
    tenants = {"alpha": alpha, "beta": beta}
    root = tmp_path / "corpus"
    shutil.copytree(CORPUS, root)
    worker = await role_conn(Role.WORKER)
    run = None
    try:
        _, _, run = await new_run(app_conn, alpha, api=await role_conn(Role.API))
        lease = await lease_for(worker, run, owner="t17-ingest", seconds=600)
        first = await ingest.ingest(worker, edit(root, "live-1"), tenants)
        assert [(r.tenant, r.documents_added, r.recorded) for r in first] == [("alpha", 9, True), ("beta", 7, True)]
        stored = await counts(app_conn, [alpha, beta])
        assert stored == {"corpus_ingestions": 2, "documents": 16, "document_states": 16, "chunks": 69}

        again = await ingest.ingest(worker, edit(root, "live-1"), tenants)  # the same files: nothing at all
        assert [(r.documents_added, r.states_added, r.recorded) for r in again] == [(0, 0, False), (0, 0, False)]
        assert await counts(app_conn, [alpha, beta]) == stored

        review = root / "alpha-alert-review.md"
        original = review.read_bytes()
        review.write_bytes(original + b"A sentence added under the same version.\n")
        with pytest.raises(ingest.IngestRefused, match="ALPHA-ALERT-REVIEW v1: the content changed"):
            await ingest.ingest(worker, edit(root, "live-2"), tenants)
        assert await counts(app_conn, [alpha, beta]) == stored  # refused as a whole: beta got nothing either
        review.write_bytes(original)

        before = await search(app_conn, role_conn, run, lease, "repeated alerts summarized in one incident draft")
        assert "ALPHA-ALERT-REVIEW:v1:repeated-alerts" in [h.evidence_id for h in before.results]
        assert before.corpus_version == "live-1"

        def revoke(catalog: dict[str, Any]) -> None:
            entry(catalog, "ALPHA-ALERT-REVIEW")["status"] = "revoked"

        revoked = await ingest.ingest(worker, edit(root, "live-3", revoke), tenants)
        assert [(r.tenant, r.states_added, r.recorded) for r in revoked] == [("alpha", 1, True), ("beta", 0, True)]
        cur = await app_conn.execute(
            "SELECT seq, status FROM app.document_states WHERE tenant_id = %s AND document_id = 'ALPHA-ALERT-REVIEW'"
            " ORDER BY seq",
            (alpha,),
        )
        assert [(r["seq"], r["status"]) for r in await cur.fetchall()] == [(1, "approved"), (2, "revoked")]
        after = await search(app_conn, role_conn, run, lease, "repeated alerts summarized in one incident draft")
        assert not any(h.document_id == "ALPHA-ALERT-REVIEW" for h in after.results)
        assert after.corpus_version == "live-3"

        def unrevoke(catalog: dict[str, Any]) -> None:
            revoke(catalog)
            entry(catalog, "ALPHA-ALERT-REVIEW")["status"] = "approved"

        settled = await counts(app_conn, [alpha, beta])
        with pytest.raises(ingest.IngestRefused, match="a revoked version cannot change again"):
            await ingest.ingest(worker, edit(root, "live-4", unrevoke), tenants)
        assert await counts(app_conn, [alpha, beta]) == settled

        def pull_back(catalog: dict[str, Any]) -> None:
            revoke(catalog)
            entry(catalog, "ALPHA-PUMP-SEAL", "2")["status"] = "draft"

        def postpone(catalog: dict[str, Any]) -> None:
            revoke(catalog)
            # Approved again (pull_back's draft stays in the file), so only the postponement can refuse.
            entry(catalog, "ALPHA-PUMP-SEAL", "2").update(status="approved", effective_from="2027-01-01T00:00:00Z")

        # Round 2, I1: pulling the successor back to draft, or postponing it, would un-retire v1; both are refused
        # whole, nothing is written, and v1 stays out of every answer.
        for change, reason in ((pull_back, "cannot return to it"), (postpone, "keeps its effective_from")):
            with pytest.raises(ingest.IngestRefused, match=reason):
                await ingest.ingest(worker, edit(root, "live-4b", change), tenants)
            assert await counts(app_conn, [alpha, beta]) == settled
        seal = await search(app_conn, role_conn, run, lease, "mechanical seal inspection interval days")
        seal_versions = {h.version for h in seal.results if h.document_id == "ALPHA-PUMP-SEAL"}
        assert seal_versions == {"2"}  # v1 (the 30-day interval) stays retired

        portal = (root / "alpha-vendor-portal.md").read_text(encoding="utf-8")
        (root / "alpha-vendor-portal-v2.md").write_text(
            portal.replace("by the maintenance planner", "by the reliability planner"), encoding="utf-8", newline="\n"
        )

        def supersede(catalog: dict[str, Any]) -> None:
            revoke(catalog)
            # The refused edits above stay in the copy's catalog file; put ALPHA-PUMP-SEAL v2 back as stored.
            entry(catalog, "ALPHA-PUMP-SEAL", "2").update(status="approved", effective_from="2026-10-01T00:00:00Z")
            successor = dict(entry(catalog, "ALPHA-VENDOR-PORTAL"))
            successor.update(version="2", supersedes="1", path="alpha-vendor-portal-v2.md")
            successor["effective_from"] = "2026-10-02T00:00:00Z"
            catalog["documents"].append(successor)

        superseded = await ingest.ingest(worker, edit(root, "live-5", supersede), tenants)
        assert [(r.tenant, r.documents_added) for r in superseded] == [("alpha", 1), ("beta", 0)]
        portal_hits = await search(app_conn, role_conn, run, lease, "vendor portal visit window planner")
        versions = {(h.document_id, h.version) for h in portal_hits.results if h.document_id == "ALPHA-VENDOR-PORTAL"}
        assert versions == {("ALPHA-VENDOR-PORTAL", "2")}  # v1 is superseded the moment v2 is effective
    finally:
        if run is not None:
            await purge_run(app_conn, run)
        for tenant in (alpha, beta):
            await purge_corpus(app_conn, tenant)
            await purge_tenant(app_conn, tenant)


async def test_the_seeded_tenants_hold_the_committed_corpus_once(
    ingested: None, app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    governed = corpus.load(CORPUS)
    worker = await role_conn(Role.WORKER)
    repeated = await ingest.ingest(worker, governed, corpus_tenants())
    assert [(r.documents_added, r.states_added, r.recorded) for r in repeated] == [(0, 0, False), (0, 0, False)]
    for slug, tenant in corpus_tenants().items():
        cur = await app_conn.execute(
            "SELECT evidence_id, content_sha256, start_offset, end_offset FROM app.chunks WHERE tenant_id = %s",
            (tenant,),
        )
        rows = {
            r["evidence_id"]: (r["content_sha256"], r["start_offset"], r["end_offset"]) for r in await cur.fetchall()
        }
        expected = {
            d.evidence_id(s): (s.sha256, s.start, s.end)
            for d in governed.documents
            if d.tenant == slug
            for s in d.sections
        }
        assert rows == expected, slug
        cur = await app_conn.execute(
            "SELECT corpus_version, lock_sha256 FROM app.corpus_ingestions WHERE tenant_id = %s ORDER BY seq DESC"
            " LIMIT 1",
            (tenant,),
        )
        assert dict(await cur.fetchone() or {}) == {
            "corpus_version": "corpus-1",
            "lock_sha256": governed.lock_sha256,
        }

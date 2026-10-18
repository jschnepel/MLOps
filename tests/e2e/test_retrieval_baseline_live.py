"""The lexical baseline measured through the real SQL path (OPS_LIVE=1; R033, T17 DoD 3; Plan L rulings 19 and 20).

Every development query is run through `app.search_procedures_scoped` as `mcp_read`, with a read handle of a run in
the query's tenant (one staged run per seeded tenant, a fresh handle per query because a handle lives 60 seconds), at
k = 5 and with the query's asset type. The ranked answers become reports/retrieval/t17-lexical-baseline.json and .md
(rewritten only when the whole measurement ran). Catches: a forbidden section (another tenant's, superseded, expired,
revoked or draft) returned for any query, which is the one hard rule here; a query that was not run; a search that
finds nothing labelled at all (a broken search, not a weak one); and a report whose corpus identity is not the
ingested one. The quality numbers themselves are measurements, not gates (BS:611: report denominators, not claims).
"""

import json
from collections.abc import Awaitable, Callable
from datetime import UTC
from pathlib import Path
from uuid import UUID

import pytest
from ops_core import corpus, persistence
from ops_core.settings import Role

from scripts import retrieval_baseline as rb
from scripts.skeleton import CORPUS, corpus_tenants
from tests.e2e.conftest import lease_for, purge_run
from tests.e2e.test_fenced_definers_live import investigate_job, read_handle
from tests.e2e.test_migrations_and_persistence import new_run

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("ingested")]

RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
ROOT = Path(__file__).resolve().parents[2]
QUERIES = ROOT / "evals" / "retrieval" / "dev-queries.jsonl"
REPORT = ROOT / "reports" / "retrieval" / "t17-lexical-baseline"  # absolute: the test must not depend on the cwd


async def test_r033_the_lexical_baseline_on_the_development_queries(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    governed = corpus.load(CORPUS)
    cases = rb.load_queries(QUERIES)
    tenants = corpus_tenants()
    api, worker, mcp_read = await role_conn(Role.API), await role_conn(Role.WORKER), await role_conn(Role.MCP_READ)
    runs: dict[str, UUID] = {}
    try:
        for slug, tenant in tenants.items():
            _, _, runs[slug] = await new_run(app_conn, tenant, api=api)
        leases = {slug: await lease_for(worker, run, owner="t17-baseline", seconds=600) for slug, run in runs.items()}
        cur = await app_conn.execute("SELECT app.current_time() AS now")
        now = (await cur.fetchone() or {})["now"]
        allowed = corpus.returnable(governed, now)
        permitted = {
            slug: {
                d.evidence_id(s)
                for d in governed.documents
                if d.identity in allowed and d.tenant == slug
                for s in d.sections
            }
            for slug in tenants
        }
        outcomes = []
        for case in cases:
            run = runs[case.tenant]
            handle = await read_handle(worker, run, await investigate_job(app_conn, run), leases[case.tenant])
            answer = await persistence.search_procedures(
                mcp_read, handle=handle, azp="ops-worker", query=case.query, asset_type=case.asset_type, limit=rb.K
            )
            assert answer.corpus_version == governed.corpus_version, case.id
            returned = [(hit.evidence_id, hit.rank) for hit in answer.results]
            outcomes.append(rb.evaluate(case, returned, permitted[case.tenant]))
    finally:
        for run in runs.values():
            await purge_run(app_conn, run)
    doc = rb.report(
        outcomes,
        corpus_version=governed.corpus_version,
        lock_sha256=governed.lock_sha256,
        measured_at=now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        chunk_words=[s.words for d in governed.documents for s in d.sections],
    )
    summary = doc["summary"]
    assert summary["cases"] == len(cases) >= 40
    forbidden = [(o.case.id, o.forbidden) for o in outcomes if o.forbidden]
    assert forbidden == []  # no superseded, expired, revoked, draft or foreign section reached any answer (DoD 2)
    assert summary["hit_at_k"]["successes"] > 0  # a sanity floor against a search that finds nothing, not a target
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.with_suffix(".json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8", newline="\n")
    REPORT.with_suffix(".md").write_text(rb.markdown(doc), encoding="utf-8", newline="\n")

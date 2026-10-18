"""The lexical baseline measured through the real SQL path (OPS_LIVE=1; R033, T17 DoD 3; Plan L rulings 19 and 20).

Every development query is run through `app.search_procedures_scoped` as `mcp_read`, with a read handle of a run in
the query's tenant (one staged run per seeded tenant, a fresh handle per query because a handle lives 60 seconds), at
k = 5 and with the query's asset type. The database test clock is set to corpus-1's labelling instant (AS_OF of
tests/plan_l/test_corpus_files.py) for the whole measurement and reset afterwards, so the figures do not depend on the
date the test runs (the seasonal versions would otherwise expire, the successors take effect). The ranked answers
become reports/retrieval/t17-lexical-baseline.json and .md (rewritten only when the whole measurement ran). Catches: a
forbidden section (another tenant's, superseded, expired, revoked or draft) returned for any query, which is the one
hard rule here; a query that was not run; a search that finds nothing labelled at all (a broken search, not a weak
one); a permitted set that is not the hand-written one of test_the_returnable_set_at_the_labelling_instant (the oracle
`corpus.returnable` restates the SQL's rule, so only that hand-written set is an independent anchor); and a report
whose corpus identity is not the ingested one. The quality numbers themselves are measurements, not gates (BS:611:
report denominators, not claims).
"""

import hashlib
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
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
from tests.plan_l.test_corpus_files import AS_OF, RETURNABLE_AT_AS_OF

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("ingested")]

RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
# Each tenant's seeded requester (data/seed-ids.json): the definer re-checks the run's requester since 0012 (T16).
REQUESTERS = {
    "alpha": UUID("2fc05986-c7ec-544c-b628-fdb112bbf18a"),
    "beta": UUID("2f73af91-4906-5b79-9144-22c0df4e2316"),
}
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
    harness = await role_conn(Role.TEST_HARNESS)  # the one role that may move app.test_clock (AM-20.6)
    runs: dict[str, UUID] = {}
    try:
        # Before the runs and leases exist: everything they stamp then lives on the moved clock, which keeps ticking.
        await harness.execute("UPDATE app.test_clock SET clock_offset = %s - clock_timestamp()", (AS_OF,))
        for slug, tenant in tenants.items():
            _, _, runs[slug] = await new_run(app_conn, tenant, api=api, requester=REQUESTERS[slug])
        leases = {slug: await lease_for(worker, run, owner="t17-baseline", seconds=600) for slug, run in runs.items()}
        cur = await app_conn.execute("SELECT app.current_time() AS now")
        now = (await cur.fetchone() or {})["now"]
        assert abs(now - AS_OF).total_seconds() < 60, now  # the clock sits at the labelling instant, give or take
        allowed = corpus.returnable(governed, now)
        # The oracle at the database's instant, at AS_OF, and the hand-written set must agree: the first two are the
        # same rule restated, the third is the independent anchor (a drift in either the SQL's or the oracle's rule
        # shows up in the permitted set that the forbidden check uses).
        assert allowed == corpus.returnable(governed, AS_OF) == RETURNABLE_AT_AS_OF
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
        await harness.execute("UPDATE app.test_clock SET clock_offset = interval '0'")
        for run in runs.values():
            await purge_run(app_conn, run)
    doc = rb.report(
        outcomes,
        corpus_version=governed.corpus_version,
        lock_sha256=governed.lock_sha256,
        measured_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),  # wall clock; the rules ran at as_of
        as_of=AS_OF.strftime("%Y-%m-%dT%H:%M:%SZ"),
        queries_sha256=hashlib.sha256(QUERIES.read_bytes()).hexdigest(),
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

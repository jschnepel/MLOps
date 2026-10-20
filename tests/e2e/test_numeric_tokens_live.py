"""The numeric-token measurement through the real SQL path and real local Ollama (OPS_LIVE=1; Plan O ruling 7).

T18's harness on the twelve queries of evals/retrieval/numeric-queries.jsonl: each runs through
`app.search_procedures_scoped` as `mcp_read` in lexical mode and in vector mode (the `search_query:` embedding from
`ops_core.embeddings`, as mcp-read computes it), with a read handle of a run in its tenant, k = 5, on the database test
clock at T17's labelling instant. The answers become reports/retrieval/t23-numeric-tokens.json and .md (rewritten only
when the whole measurement ran). Catches: a forbidden section in either mode, a query that was not run, and a report
whose corpus or query identity is not the measured one. Whether a number costs a hit is the measurement, not a gate
(BS:611); ruling 7 decides what the finding leads to.
"""

import hashlib
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from ops_core import corpus, embeddings, model_pins, persistence
from ops_core.settings import Role

from scripts import numeric_tokens as nt
from scripts import retrieval_baseline as rb
from scripts.skeleton import CORPUS, corpus_tenants
from tests.e2e.conftest import lease_for, purge_run
from tests.e2e.test_fenced_definers_live import investigate_job, read_handle
from tests.e2e.test_migrations_and_persistence import new_run
from tests.e2e.test_retrieval_baseline_live import REQUESTERS
from tests.plan_l.test_corpus_files import AS_OF, RETURNABLE_AT_AS_OF

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("embedded")]

RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
REPORT = Path(__file__).resolve().parents[2] / "reports" / "retrieval" / "t23-numeric-tokens"


async def test_numeric_tokens_against_their_controls_in_both_modes(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    governed = corpus.load(CORPUS)
    pairs = nt.load_pairs()
    cases = [c for p in pairs for c in (p.numeric, p.control)]
    tenants = corpus_tenants()
    pins = model_pins.load_embedding_pins(embeddings.PINS)
    embedder = embeddings.OllamaEmbedder.from_settings()
    try:
        await embedder.verify(pins)
        vectors = await embedder.embed([embeddings.query_text(c.query) for c in cases], pins)
    finally:
        await embedder.aclose()
    allowed = corpus.returnable(governed, AS_OF)
    assert allowed == RETURNABLE_AT_AS_OF  # the hand-written anchor of T17's measurement
    permitted = {
        slug: {
            d.evidence_id(s)
            for d in governed.documents
            if d.identity in allowed and d.tenant == slug
            for s in d.sections
        }
        for slug in tenants
    }
    api, worker, mcp_read = await role_conn(Role.API), await role_conn(Role.WORKER), await role_conn(Role.MCP_READ)
    harness = await role_conn(Role.TEST_HARNESS)
    runs: dict[str, UUID] = {}
    outcomes: dict[str, dict[str, rb.Outcome]] = {mode: {} for mode in nt.MODES}
    try:
        await harness.execute("UPDATE app.test_clock SET clock_offset = %s - clock_timestamp()", (AS_OF,))
        for slug, tenant in tenants.items():
            _, _, runs[slug] = await new_run(app_conn, tenant, api=api, requester=REQUESTERS[slug])
        leases = {slug: await lease_for(worker, run, owner="t23-numeric", seconds=600) for slug, run in runs.items()}
        cur = await app_conn.execute("SELECT app.current_time() AS now")
        now = (await cur.fetchone() or {})["now"]
        assert abs(now - AS_OF).total_seconds() < 60, now  # the clock sits at the labelling instant, give or take
        for case, vector in zip(cases, vectors, strict=True):
            run = runs[case.tenant]
            for mode in nt.MODES:
                handle = await read_handle(worker, run, await investigate_job(app_conn, run), leases[case.tenant])
                answer = await persistence.search_procedures(
                    mcp_read,
                    handle=handle,
                    azp="ops-worker",
                    query=case.query,
                    asset_type=case.asset_type,
                    limit=rb.K,
                    mode="lexical" if mode == "lexical" else "vector",
                    embedding=None if mode == "lexical" else vector,
                )
                assert answer.corpus_version == governed.corpus_version, case.id
                returned = [(h.evidence_id, h.rank) for h in answer.results]
                outcomes[mode][case.id] = rb.evaluate(case, returned, permitted[case.tenant])
    finally:
        await harness.execute("UPDATE app.test_clock SET clock_offset = interval '0'")
        for run in runs.values():
            await purge_run(app_conn, run)
    assert all(len(outcomes[mode]) == len(cases) == 12 for mode in nt.MODES)
    doc = nt.report(
        pairs,
        outcomes,
        corpus_version=governed.corpus_version,
        lock_sha256=governed.lock_sha256,
        queries_sha256=hashlib.sha256(nt.QUERIES.read_bytes()).hexdigest(),
        as_of=AS_OF.strftime("%Y-%m-%dT%H:%M:%SZ"),
        measured_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    assert all(doc["summary"][mode]["forbidden_rows"] == 0 for mode in nt.MODES)  # the one hard rule
    REPORT.with_suffix(".json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8", newline="\n")
    REPORT.with_suffix(".md").write_text(nt.markdown(doc), encoding="utf-8", newline="\n")

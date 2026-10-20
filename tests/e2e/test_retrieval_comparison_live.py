"""Exact vector search measured against the lexical baseline through the real SQL path and real local Ollama
(OPS_LIVE=1; R034, T18 DoD 1; Plan N rulings 6-11 and 14).

T17's harness, twice: every development query runs through `app.search_procedures_scoped` as `mcp_read` in lexical
mode and in vector mode (the query's `search_query:` embedding computed with `ops_core.embeddings`, the code mcp-read
uses), with a read handle of a run in the query's tenant, at k = 5 and with the query's asset type, on the database
test clock at corpus-1's labelling instant. The answers become reports/retrieval-comparison.json and .md (rewritten
only when the whole measurement ran; the T17 report is not touched). Catches: a forbidden section in either mode (the
one hard quality rule); the lexical path moved since T17 (its answers must reproduce the committed baseline's,
digest for digest); a vector threshold that the fixed rule no longer chooses on the stored vectors; two embeddings of
one query that are not the same vector within the bound; a window experiment that lets a forbidden section in; and a
report whose corpus or query identity is not the measured one. The quality numbers themselves are measurements, not
gates (BS:611).
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

from scripts import retrieval_baseline as rb
from scripts import retrieval_comparison as rc
from scripts.skeleton import CORPUS, corpus_tenants
from tests.e2e.conftest import lease_for, purge_run
from tests.e2e.test_fenced_definers_live import investigate_job, read_handle
from tests.e2e.test_migrations_and_persistence import new_run
from tests.e2e.test_retrieval_baseline_live import QUERIES, REQUESTERS
from tests.plan_l.test_corpus_files import AS_OF, RETURNABLE_AT_AS_OF

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("embedded")]

RoleConn = Callable[[Role], Awaitable[persistence.Conn]]
REPORT = Path(__file__).resolve().parents[2] / "reports" / "retrieval-comparison"  # the DoD's path


async def test_r034_exact_vector_search_against_the_lexical_baseline(
    app_conn: persistence.Conn, role_conn: RoleConn
) -> None:
    governed = corpus.load(CORPUS)
    cases = rb.load_queries(QUERIES)
    tenants = corpus_tenants()
    pins = model_pins.load_embedding_pins(embeddings.PINS)
    embedder = embeddings.OllamaEmbedder.from_settings()
    try:
        await embedder.verify(pins)
        version = await embedder.version()
        texts = [embeddings.query_text(c.query) for c in cases]
        queries, repeated = await embedder.embed(texts, pins), await embedder.embed(texts, pins)
        windows = rc.corpus_windows(governed)
        window_vectors = await embedder.embed([w.text for w in windows], pins)
    finally:
        await embedder.aclose()
    repeat = rc.repeat_check(queries, repeated)
    assert repeat["min_cosine"] >= rc.REPEAT_COSINE  # ruling 14
    cur = await app_conn.execute(
        "SELECT tenant_id, evidence_id, embedding::text AS vector FROM app.embeddings WHERE tenant_id = ANY(%s)",
        (list(tenants.values()),),
    )
    stored = {
        (UUID(str(r["tenant_id"])), str(r["evidence_id"])): embeddings.parse_vector(str(r["vector"]))
        for r in await cur.fetchall()
    }
    cur = await app_conn.execute("SELECT app._min_similarity() AS m")
    threshold = float((await cur.fetchone() or {})["m"])
    allowed = corpus.returnable(governed, AS_OF)
    assert allowed == RETURNABLE_AT_AS_OF  # the hand-written anchor of T17's measurement
    assert rc.AS_OF == AS_OF  # the instant the report records is the one measured
    cur = await app_conn.execute("SELECT app._min_rank() AS m")
    min_rank = float((await cur.fetchone() or {})["m"])
    assert min_rank == rc.LEXICAL_GRID[0]  # the lexical sweep starts at the stored minimum
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
    lexical, vector = [], []
    try:
        await harness.execute("UPDATE app.test_clock SET clock_offset = %s - clock_timestamp()", (AS_OF,))
        for slug, tenant in tenants.items():
            _, _, runs[slug] = await new_run(app_conn, tenant, api=api, requester=REQUESTERS[slug])
        leases = {slug: await lease_for(worker, run, owner="t18-compare", seconds=600) for slug, run in runs.items()}
        for case, query in zip(cases, queries, strict=True):
            run = runs[case.tenant]
            for mode, out in (("lexical", lexical), ("vector", vector)):
                # A fresh handle per call: a handle lives 60 seconds, and the two modes must not share a failure.
                handle = await read_handle(worker, run, await investigate_job(app_conn, run), leases[case.tenant])
                answer = await persistence.search_procedures(
                    mcp_read,
                    handle=handle,
                    azp="ops-worker",
                    query=case.query,
                    asset_type=case.asset_type,
                    limit=rb.K,
                    mode="lexical" if mode == "lexical" else "vector",
                    embedding=None if mode == "lexical" else query,
                )
                assert answer.corpus_version == governed.corpus_version, case.id
                out.append(rb.evaluate(case, [(h.evidence_id, h.rank) for h in answer.results], permitted[case.tenant]))
    finally:
        await harness.execute("UPDATE app.test_clock SET clock_offset = interval '0'")
        for run in runs.values():
            await purge_run(app_conn, run)
    # Hard rules: no forbidden section in either mode, and the lexical path is T17's, answer for answer.
    assert [(o.case.id, o.forbidden) for o in lexical + vector if o.forbidden] == []
    relisted = [
        {"id": o.case.id, "returned": [{"evidence_id": e, "rank": round(r, 6)} for e, r in o.returned]} for o in lexical
    ]
    assert rc.answers_digest(relisted) == rc.T17_ANSWERS_SHA256  # the lexical path did not move (ruling 11)
    scored = {
        c.id: [
            (d.evidence_id(s), embeddings.cosine(q, stored[(tenants[c.tenant], d.evidence_id(s))]))
            for d in governed.documents
            if d.tenant == c.tenant
            and d.identity in allowed
            and (c.asset_type is None or d.asset_family in (None, c.asset_type))
            for s in d.sections
        ]
        for c, q in zip(cases, queries, strict=True)
    }
    sweep = rc.sweep(cases, scored, rc.GRID)
    assert rc.choose_threshold(sweep) == pytest.approx(threshold)  # the frozen value is still the rule's (ruling 6)
    candidates = {
        c.id: [
            (w, embeddings.cosine(q, v))
            for w, v in zip(windows, window_vectors, strict=True)
            if w.tenant == c.tenant and (c.asset_type is None or w.asset_family in (None, c.asset_type))
        ]
        for c, q in zip(cases, queries, strict=True)
    }
    window = rc.window_metrics(cases, candidates, permitted, windows, threshold)
    assert window["forbidden_windows"] == 0
    # On corpus-1 the 300-word rule gives one window per returnable version; the report says so.
    assert window["every_window_a_whole_version"] and window["windows"] == 8
    settings = {
        "model": pins.model,
        "model_digest": pins.digest,
        "dimension": pins.dimension,
        "ollama_version": version,
        "document_prefix": embeddings.DOCUMENT_PREFIX,
        "document_text": "search_document: + section heading + blank line + body",
        "query_prefix": embeddings.QUERY_PREFIX,
        "distance": "cosine (pgvector <=>); rank = 1 - distance, the cosine similarity",
        "vector_minimum_similarity": threshold,
        "lexical_minimum_rank": min_rank,
        "index": "none: a sequential scan over the tenant's permitted chunks, exact by construction",
        "window": "one chunk per ## section (the stored unit)",
        "window_experiment": {"min_words": rc.WINDOW_WORDS, "rule": "adjacent sections of one version"},
        "tie_break": 'evidence_id ascending in byte order (COLLATE "C")',
        "ks": list(rc.KS),
        "filters": rb.SETTINGS["filters"],
    }
    doc = rc.comparison(
        lexical,
        vector,
        settings=settings,
        vector_sweep=sweep,
        lexical_sweep_rows=rc.lexical_sweep(lexical, rc.LEXICAL_GRID),
        window=window,
        repeat=repeat,
        corpus_version=governed.corpus_version,
        lock_sha256=governed.lock_sha256,
        queries_sha256=hashlib.sha256(QUERIES.read_bytes()).hexdigest(),
        measured_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    assert doc["summary"]["vector_exact"]["5"]["hit_at_k"]["successes"] > 0  # a floor against a broken search
    REPORT.with_suffix(".json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8", newline="\n")
    REPORT.with_suffix(".md").write_text(rc.markdown(doc), encoding="utf-8", newline="\n")

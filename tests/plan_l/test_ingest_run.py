"""`ops_core.ingest.ingest` against a stub connection, without a database (R032; BS:413; Plan L ruling 6).

The stub records every statement and transaction boundary in order, so these tests can prove the property the live
suite can only sample: the whole catalog is planned, for every tenant, before the first INSERT. Catches: a
per-tenant plan-then-write loop (a refusal in a later tenant would leave an earlier one written), a phase-1 refusal
that still writes, a "store moved" refusal in phase 2 that forgets which tenants already committed, and a store
failure that loses the same list on its way to the command.
"""

from typing import Any
from uuid import UUID

import psycopg
import pytest
from ops_core import corpus, ingest, persistence

from scripts import skeleton

ALPHA = UUID("3ea79c95-914c-52cb-9d10-c4e19dda8ff7")
BETA = UUID("5ab45c2c-1e12-5a0c-a2b9-66cd2ff05201")
GOVERNED = corpus.load(skeleton.CORPUS)
TENANTS = {"alpha": ALPHA, "beta": BETA}
Event = tuple[str, str]


class Cursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    async def fetchone(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None

    async def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


class Unit:
    def __init__(self, conn: "StubConn") -> None:
        self.conn = conn

    async def __aenter__(self) -> None:
        self.conn.depth = True
        self.conn.events.append(("begin", ""))

    async def __aexit__(self, kind: type[BaseException] | None, *_: object) -> None:
        self.conn.depth = False
        self.conn.events.append(("rollback" if kind else "commit", ""))
        self.conn.tenant = None


class Info:
    def __init__(self, conn: "StubConn") -> None:
        self.conn = conn

    @property
    def transaction_status(self) -> Any:
        return psycopg.pq.TransactionStatus.INTRANS if self.conn.depth else psycopg.pq.TransactionStatus.IDLE


class StubConn:
    """Answers the few statements `ingest` issues. `stores[tenant]` lists what each successive read of that tenant's
    store returns (the last entry repeats), so a test can make the store move between phase 1 and phase 2."""

    def __init__(self, known: set[UUID], stores: dict[UUID, list[list[dict[str, Any]]]] | None = None) -> None:
        self.known, self.stores = known, stores or {}
        self.events: list[Event] = []
        self.reads: dict[UUID, int] = {}
        self.tenant: UUID | None = None
        self.depth = False
        self.info = Info(self)

    def transaction(self) -> Unit:
        return Unit(self)

    async def execute(self, sql: str, params: Any = None) -> Cursor:
        if "to_regclass" in sql:
            return Cursor([{"missing": False}])
        if "FROM app.tenants" in sql:
            return Cursor([{"?column?": 1}] if params[0] in self.known else [])
        if "set_config" in sql:
            self.tenant = UUID(params[0])
            return Cursor([])
        if "JOIN LATERAL" in sql:
            assert self.tenant is not None, "the store was read before the tenant was set"
            self.events.append(("read", str(self.tenant)))
            reads = self.reads[self.tenant] = self.reads.get(self.tenant, 0) + 1
            history = self.stores.get(self.tenant, [[]])
            return Cursor(history[min(reads, len(history)) - 1])
        if "FROM app.corpus_ingestions" in sql:
            return Cursor([])
        assert sql.startswith("INSERT"), sql
        self.events.append(("insert", sql.split()[2]))
        return Cursor([])


def stored_row(doc: corpus.Document, **over: Any) -> dict[str, Any]:
    """The row `read_store` would get for `doc` as ingested, with `over` applied."""
    row = {
        "document_id": doc.document_id,
        "version": doc.version,
        "path": doc.path,
        "content_sha256": doc.content_sha256,
        "asset_family": doc.asset_family,
        "label": doc.label,
        "supersedes": doc.supersedes,
        "conflicts_with": doc.conflicts_with,
        "seq": 1,
        "status": doc.status,
        "effective_from": doc.effective_from,
        "effective_to": doc.effective_to,
        "sections": [s.name for s in doc.sections],
    }
    return row | over


def rows(slug: str, **over: Any) -> list[dict[str, Any]]:
    return [stored_row(d, **over) for d in GOVERNED.documents if d.tenant == slug]


@pytest.mark.asyncio
async def test_no_insert_precedes_the_last_tenants_planning() -> None:
    conn = StubConn({ALPHA, BETA})
    reports = await ingest.ingest(conn, GOVERNED, TENANTS)  # type: ignore[arg-type]
    assert [(r.tenant, r.recorded) for r in reports] == [("alpha", True), ("beta", True)]
    kinds = [event[0] for event in conn.events]
    first_insert = kinds.index("insert")
    reads = [e for e in conn.events[:first_insert] if e[0] == "read"]
    assert reads[:2] == [("read", str(ALPHA)), ("read", str(BETA))]  # both tenants are planned first ...
    assert kinds[:first_insert].count("commit") == 2  # ... in two read-only units that closed before any write
    assert kinds.count("rollback") == 0
    # Phase 2 plans each tenant again inside its own unit and writes the ingestion row (the parent) first.
    inserts = [e for e in conn.events if e[0] == "insert"]
    assert inserts[0] == ("insert", "app.corpus_ingestions")


@pytest.mark.asyncio
async def test_a_refusal_in_the_last_tenant_writes_nothing_for_the_first() -> None:
    changed = rows("beta", content_sha256="0" * 64)
    conn = StubConn({ALPHA, BETA}, {BETA: [changed]})
    with pytest.raises(ingest.IngestRefused) as refused:
        await ingest.ingest(conn, GOVERNED, TENANTS)  # type: ignore[arg-type]
    assert all("the content changed" in p and p.startswith("beta ") for p in refused.value.problems)
    assert refused.value.written == ()
    assert not any(kind == "insert" for kind, _ in conn.events)


@pytest.mark.asyncio
async def test_an_unknown_tenant_is_refused_before_anything_is_written() -> None:
    conn = StubConn({ALPHA})  # beta has no app.tenants row
    with pytest.raises(ingest.IngestRefused) as refused:
        await ingest.ingest(conn, GOVERNED, TENANTS)  # type: ignore[arg-type]
    assert refused.value.problems == ("beta: no such tenant in app.tenants",) and refused.value.written == ()
    assert not any(kind == "insert" for kind, _ in conn.events)


@pytest.mark.asyncio
async def test_a_corpus_tenant_without_a_uuid_is_refused_first() -> None:
    conn = StubConn({ALPHA, BETA})
    with pytest.raises(ingest.IngestRefused) as refused:
        await ingest.ingest(conn, GOVERNED, {"alpha": ALPHA})  # type: ignore[arg-type]
    assert refused.value.problems == ("beta: no tenant UUID for this corpus tenant",) and conn.events == []


@pytest.mark.asyncio
async def test_a_store_that_moves_between_the_phases_names_the_tenants_already_written() -> None:
    """Beta's second read (phase 2) finds a changed hash its first read did not: alpha is already committed."""
    moved = rows("beta", content_sha256="0" * 64)
    conn = StubConn({ALPHA, BETA}, {BETA: [[], moved]})
    with pytest.raises(ingest.IngestRefused) as refused:
        await ingest.ingest(conn, GOVERNED, TENANTS)  # type: ignore[arg-type]
    assert refused.value.written == ("alpha",)
    assert all(p.startswith("beta ") for p in refused.value.problems)
    assert [e for e in conn.events if e[0] in ("commit", "rollback")][-2:] == [("commit", ""), ("rollback", "")]
    assert any(kind == "insert" for kind, _ in conn.events)  # alpha's rows were written ...
    assert conn.events[-1] == ("rollback", "")  # ... and beta's unit ended without a write


@pytest.mark.asyncio
async def test_a_store_failure_carries_the_tenants_already_written() -> None:
    class Failing(StubConn):
        async def execute(self, sql: str, params: Any = None) -> Cursor:
            if sql.startswith("INSERT INTO app.corpus_ingestions") and self.tenant == BETA:
                raise psycopg.errors.InsufficientPrivilege("denied")
            return await super().execute(sql, params)

    with pytest.raises(psycopg.Error) as failed:
        await ingest.ingest(Failing({ALPHA, BETA}), GOVERNED, TENANTS)  # type: ignore[arg-type]
    assert getattr(failed.value, "written", None) == ("alpha",)


@pytest.mark.asyncio
async def test_a_missing_relation_is_a_persistence_error_before_anything_else() -> None:
    class Missing(StubConn):
        async def execute(self, sql: str, params: Any = None) -> Cursor:
            if "to_regclass" in sql:
                return Cursor([{"missing": True}])
            return await super().execute(sql, params)

    conn = Missing({ALPHA, BETA})
    with pytest.raises(persistence.PersistenceError, match="is missing"):
        await ingest.ingest(conn, GOVERNED, TENANTS)  # type: ignore[arg-type]
    assert conn.events == []


def test_the_command_reports_a_store_failure_with_its_class_only(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(skeleton, "load_dotenv", lambda path: {})
    monkeypatch.setattr(skeleton, "export_environment", lambda dotenv: None)
    monkeypatch.setattr(skeleton.settings, "app_postgres", lambda role: role)

    async def missing(pg: Any, governed: corpus.Corpus) -> list[ingest.Report]:
        raise persistence.PersistenceError("app.chunks is missing; run scripts/skeleton.py migrate for this profile")

    monkeypatch.setattr(skeleton, "_ingest", missing)
    assert skeleton.ingest() == 1
    assert capsys.readouterr().out.splitlines() == ["INGEST: failed (PersistenceError)"]

    async def broken(pg: Any, governed: corpus.Corpus) -> list[ingest.Report]:
        error = psycopg.OperationalError("connection to server at 'db.internal' failed")
        error.written = ("alpha",)  # type: ignore[attr-defined]
        raise error

    monkeypatch.setattr(skeleton, "_ingest", broken)
    assert skeleton.ingest() == 1
    assert capsys.readouterr().out.splitlines() == ["INGEST: failed (OperationalError) after writing alpha"]

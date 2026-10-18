"""Idempotent ingestion of the governed corpus as role `worker` (T17; AM-20.2 "ins, sel (ingestion)", BS:411-413,
R032; Plan L rulings 5-7).

The identity of a document version is (tenant, document_id, version) and its content hash is the file's SHA-256. A
run first plans every tenant against what is stored, each in a read-only unit under its tenant setting, and writes
nothing if any tenant's plan is refused (ruling 6: the whole catalog is validated before anything is written); then
it writes each tenant in one transaction, re-planning inside it so that what it writes is what it checked:

- a version not stored yet: its document row, one chunk per section and its first state row;
- the same version with the same hash and the same immutable attributes (path, sections, asset family, label,
  supersedes, conflicts_with): nothing, unless its lifecycle (status, effective interval) changed, which appends one
  state row (AM-20.2 grants no UPDATE, so the history is the rows). The allowed changes are draft to any status,
  approved to superseded or revoked, superseded to revoked, and a new `effective_to`. Refused: any change of a
  revoked version; a superseded version approved again; a version that has left `draft` returning to it or changing
  its `effective_from` (round 2, I1: either of those two would un-retire its predecessors, which the search retires
  by the latest state of every later version);
- the same version with another hash or another immutable attribute: refused (BS:413), as is a stored version the
  catalog no longer lists (a version is revoked, never removed).

A tenant whose plan changes nothing and whose latest ingestion already names this corpus version and lock gets no
row at all, so a repeated run writes nothing (the choice ruling 6 leaves to the writer). Otherwise one
`corpus_ingestions` row records the version, the lock's SHA-256 and the counts; the newest row (highest `seq`) is the
corpus version the tool reports for the tenant. The clock is never consulted here: "effective" is decided at query
time (ruling 8). A second ingestion running at the same moment is not supported (one operator, one command); its
inserts would collide on the primary keys and roll back that tenant's transaction.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

import psycopg

from ops_core import persistence
from ops_core.corpus import Corpus, Document

RELATIONS = ("app.corpus_ingestions", "app.documents", "app.document_states", "app.chunks")


class IngestRefused(Exception):
    """The run was refused; `problems` names each document version and the rule, never its text. `written` names
    the tenants an earlier phase-2 transaction already committed (empty for every refusal of phase 1, which writes
    nothing; non-empty only when the store moved between the two phases)."""

    def __init__(self, problems: list[str], written: tuple[str, ...] = ()) -> None:
        self.problems = tuple(problems)
        self.written = written
        super().__init__("\n".join(self.problems))


@dataclass(frozen=True)
class Stored:
    """What the store holds for one document version: its immutable attributes and its latest state."""

    content_sha256: str
    attributes: tuple[Any, ...]
    lifecycle: tuple[str, datetime, datetime | None]
    seq: int


@dataclass(frozen=True)
class Plan:
    """One tenant's writes: new versions, versions whose lifecycle changed, and whether an ingestion row is due."""

    tenant: str
    tenant_id: UUID
    new: tuple[Document, ...] = ()
    restated: tuple[tuple[Document, int], ...] = ()  # (document, the seq its new state row takes)
    unchanged: int = 0
    record: bool = False
    next_seq: int = 1
    problems: tuple[str, ...] = field(default=())


@dataclass(frozen=True)
class Report:
    """What one tenant's ingestion wrote."""

    tenant: str
    corpus_version: str
    documents_added: int
    states_added: int
    unchanged: int
    recorded: bool


def attributes(doc: Document) -> tuple[Any, ...]:
    """The immutable attributes of a version, in the order `Stored.attributes` keeps them."""
    return (
        doc.path,
        tuple(s.name for s in doc.sections),
        doc.asset_family,
        doc.label,
        doc.supersedes,
        doc.conflicts_with,
    )


def lifecycle(doc: Document) -> tuple[str, datetime, datetime | None]:
    """The mutable part: status and effective interval (ruling 7)."""
    return (doc.status, doc.effective_from, doc.effective_to)


def plan(
    corpus: Corpus,
    tenant: str,
    tenant_id: UUID,
    stored: Mapping[tuple[str, str], Stored],
    latest: tuple[int, str, str] | None,
) -> Plan:
    """Compare a tenant's catalog with what is stored, without a database (ruling 6).

    Args:
        stored: (document_id, version) -> the stored version.
        latest: the tenant's newest ingestion as (seq, corpus_version, lock_sha256), or None before the first.
    """
    problems: list[str] = []
    new: list[Document] = []
    restated: list[tuple[Document, int]] = []
    unchanged = 0
    listed = {(d.document_id, d.version): d for d in corpus.documents if d.tenant == tenant}
    for key in sorted(set(stored) - set(listed)):
        problems.append(f"{tenant} {key[0]} v{key[1]}: stored but missing from the catalog (revoke it instead)")
    for key, doc in sorted(listed.items(), key=lambda item: (item[0][0], int(item[0][1]))):
        held = stored.get(key)
        if held is None:
            new.append(doc)
        elif held.content_sha256 != doc.content_sha256:
            problems.append(f"{tenant} {key[0]} v{key[1]}: the content changed under the same version")
        elif held.attributes != attributes(doc):
            problems.append(f"{tenant} {key[0]} v{key[1]}: an immutable attribute changed under the same version")
        elif held.lifecycle == lifecycle(doc):
            unchanged += 1
        elif held.lifecycle[0] == "revoked":
            problems.append(f"{tenant} {key[0]} v{key[1]}: a revoked version cannot change again")
        elif held.lifecycle[0] == "superseded" and doc.status == "approved":
            problems.append(
                f"{tenant} {key[0]} v{key[1]}: a superseded version cannot be approved again; "
                "publish a new version instead"
            )
        elif held.lifecycle[0] != "draft" and doc.status == "draft":
            problems.append(f"{tenant} {key[0]} v{key[1]}: a version that has left draft cannot return to it")
        elif held.lifecycle[0] != "draft" and held.lifecycle[1] != doc.effective_from:
            problems.append(
                f"{tenant} {key[0]} v{key[1]}: a version that has left draft keeps its effective_from "
                "(publish a new version instead)"
            )
        else:
            restated.append((doc, held.seq + 1))
    if problems:
        return Plan(tenant, tenant_id, problems=tuple(problems))
    current = latest is not None and latest[1:] == (corpus.corpus_version, corpus.lock_sha256)
    return Plan(
        tenant,
        tenant_id,
        new=tuple(new),
        restated=tuple(restated),
        unchanged=unchanged,
        record=bool(new or restated) or not current,
        next_seq=1 if latest is None else latest[0] + 1,
    )


async def read_store(conn: persistence.Conn) -> tuple[dict[tuple[str, str], Stored], tuple[int, str, str] | None]:
    """The stored versions and the newest ingestion of the tenant the caller's unit set (RLS admits nothing else)."""
    cur = await conn.execute(
        "SELECT d.document_id, d.version, d.path, d.content_sha256, d.asset_family, d.label, d.supersedes,"
        " d.conflicts_with, s.seq, s.status, s.effective_from, s.effective_to,"
        " (SELECT array_agg(c.section ORDER BY c.ordinal) FROM app.chunks c WHERE c.tenant_id = d.tenant_id"
        "  AND c.document_id = d.document_id AND c.version = d.version) AS sections"
        " FROM app.documents d JOIN LATERAL (SELECT * FROM app.document_states x WHERE x.tenant_id = d.tenant_id"
        "  AND x.document_id = d.document_id AND x.version = d.version ORDER BY x.seq DESC LIMIT 1) s ON true"
    )
    stored = {
        (str(row["document_id"]), str(row["version"])): Stored(
            content_sha256=str(row["content_sha256"]),
            attributes=(
                row["path"],
                tuple(row["sections"] or ()),
                row["asset_family"],
                row["label"],
                row["supersedes"],
                row["conflicts_with"],
            ),
            lifecycle=(str(row["status"]), row["effective_from"], row["effective_to"]),
            seq=int(row["seq"]),
        )
        for row in await cur.fetchall()
    }
    cur = await conn.execute(
        "SELECT seq, corpus_version, lock_sha256 FROM app.corpus_ingestions ORDER BY seq DESC LIMIT 1"
    )
    row = await cur.fetchone()
    latest = None if row is None else (int(row["seq"]), str(row["corpus_version"]), str(row["lock_sha256"]))
    return stored, latest


async def _planned(conn: persistence.Conn, corpus: Corpus, tenant: str, tenant_id: UUID) -> Plan:
    """Set the tenant for the caller's open unit, read the store and plan."""
    await persistence.set_tenant(conn, tenant_id)
    stored, latest = await read_store(conn)
    return plan(corpus, tenant, tenant_id, stored, latest)


async def _write(conn: persistence.Conn, corpus: Corpus, step: Plan) -> None:
    """The plan's rows, in key order: the ingestion row first (every other row references it)."""
    seq = step.next_seq
    await conn.execute(
        "INSERT INTO app.corpus_ingestions (tenant_id, seq, corpus_version, lock_sha256, documents_added,"
        " states_added) VALUES (%s, %s, %s, %s, %s, %s)",
        (step.tenant_id, seq, corpus.corpus_version, corpus.lock_sha256, len(step.new), len(step.restated)),
    )
    for doc in step.new:  # catalog order within a document is by version, so a predecessor exists first
        await conn.execute(
            "INSERT INTO app.documents (tenant_id, document_id, version, path, content_sha256, asset_family, label,"
            " supersedes, conflicts_with, ingestion_seq) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                step.tenant_id,
                doc.document_id,
                doc.version,
                doc.path,
                doc.content_sha256,
                doc.asset_family,
                doc.label,
                doc.supersedes,
                doc.conflicts_with,
                seq,
            ),
        )
        for ordinal, section in enumerate(doc.sections, start=1):
            await conn.execute(
                "INSERT INTO app.chunks (tenant_id, document_id, version, ordinal, section, evidence_id, body,"
                " content_sha256, start_offset, end_offset, word_count)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    step.tenant_id,
                    doc.document_id,
                    doc.version,
                    ordinal,
                    section.name,
                    doc.evidence_id(section),
                    section.body,
                    section.sha256,
                    section.start,
                    section.end,
                    section.words,
                ),
            )
    states = [(doc, 1) for doc in step.new] + list(step.restated)
    for doc, state_seq in states:
        await conn.execute(
            "INSERT INTO app.document_states (tenant_id, document_id, version, seq, status, effective_from,"
            " effective_to, ingestion_seq) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (step.tenant_id, doc.document_id, doc.version, state_seq, *lifecycle(doc), seq),
        )


async def ingest(conn: persistence.Conn, corpus: Corpus, tenants: Mapping[str, UUID]) -> list[Report]:
    """Ingest a validated corpus for each named tenant on a `worker` connection; return what each tenant got.

    Args:
        conn: an autocommit connection as role `worker` (AM-20.2's ingestion cells).
        corpus: `ops_core.corpus.load`'s result (the whole directory already validated).
        tenants: tenant slug -> tenant UUID; every tenant the corpus names must be here.

    Raises:
        IngestRefused: a tenant row is missing or a document version conflicts with what is stored; nothing was
            written, unless `written` names tenants committed before a concurrent change was found.
        PersistenceError: revision 0011 is missing (`persistence.assert_relation`).
    """
    for relation in RELATIONS:
        await persistence.assert_relation(conn, relation)
    missing = sorted(corpus.tenants - set(tenants))
    if missing:
        raise IngestRefused([f"{slug}: no tenant UUID for this corpus tenant" for slug in missing])
    order = sorted(tenants.items())
    problems: list[str] = []
    for tenant, tenant_id in order:  # phase 1: plan every tenant, write nothing
        # The ingestion row's foreign key would refuse an unknown tenant only in phase 2, after an earlier tenant
        # committed (round 1, M1); `tenants` has no RLS and the worker may read it.
        cur = await conn.execute("SELECT 1 FROM app.tenants WHERE tenant_id = %s", (tenant_id,))
        if await cur.fetchone() is None:
            problems.append(f"{tenant}: no such tenant in app.tenants")
            continue
        async with conn.transaction():
            problems.extend((await _planned(conn, corpus, tenant, tenant_id)).problems)
    if problems:
        raise IngestRefused(problems)
    reports: list[Report] = []
    for tenant, tenant_id in order:  # phase 2: one transaction per tenant, re-planned under its own setting
        try:
            async with conn.transaction():
                step = await _planned(conn, corpus, tenant, tenant_id)
                if step.problems:  # the store moved since phase 1: this tenant rolls back, earlier ones stay written
                    raise IngestRefused(list(step.problems), written=tuple(r.tenant for r in reports if r.recorded))
                if step.record:
                    await _write(conn, corpus, step)
        except (psycopg.Error, persistence.PersistenceError) as error:
            # The failing tenant rolled back; tell the command which earlier ones stayed (it prints the class only).
            error.written = tuple(r.tenant for r in reports if r.recorded)  # type: ignore[union-attr]
            raise
        reports.append(
            Report(tenant, corpus.corpus_version, len(step.new), len(step.restated), step.unchanged, step.record)
        )
    return reports

"""Lexical procedure search over the authored fixtures (T08; debt → T17: the governed store, `search_procedures_scoped`
and `vector_exact`).

The corpus is built per tenant from `data/handoff-fixtures/catalog.json`: only that tenant's documents (the fixtures
README: "An alpha identity must not see beta evidence") and only `approved` versions, so a superseded or draft document
is never cited. Sections are sliced exactly as scripts/gen_fixture_meta.py slices them and carry the per-section hash
from meta.json, so an `evidence_ref` the proposal cites (`<DOCUMENT_ID>:v<version>:<section>`) names bytes the
destination reviewer can re-hash. Ranking is term overlap with a deterministic tie-break: the same query must cite the
same evidence on a retry (BUILD_SPEC §6: retries keep the same proposal).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

WORD = re.compile(r"[a-z0-9]+")
EXCERPT_CHARS = 500


def tokens(text: str) -> set[str]:
    return set(WORD.findall(text.lower()))


def section_bodies(markdown: str) -> dict[str, str]:
    """Body of every `## <name>` section: lines up to the next `## ` or EOF, outer newlines stripped (meta.json)."""
    bodies: dict[str, str] = {}
    name: str | None = None
    buffer: list[str] = []
    for line in markdown.split("\n"):
        if line.startswith("## "):
            if name is not None:
                bodies[name] = "\n".join(buffer).strip("\n")
            name, buffer = line[3:].strip(), []
        elif name is not None:
            buffer.append(line)
    if name is not None:
        bodies[name] = "\n".join(buffer).strip("\n")
    return bodies


@dataclass(frozen=True)
class Section:
    evidence_id: str
    document_id: str
    version: str
    section: str
    content_sha256: str
    text: str
    effective_from: str


@dataclass(frozen=True)
class Hit:
    section: Section
    score: int


@dataclass(frozen=True)
class Corpus:
    sections: tuple[Section, ...]
    corpus_version: str

    @classmethod
    def load(cls, fixtures_dir: Path, tenant_slug: str) -> Corpus:
        catalog = json.loads((fixtures_dir / "catalog.json").read_text(encoding="utf-8"))
        meta = json.loads((fixtures_dir / "meta.json").read_text(encoding="utf-8"))
        hashes = {(s["document_id"], s["version"], s["section"]): s["sha256"] for s in meta["sections"]}
        sections: list[Section] = []
        for doc in catalog["documents"]:
            if doc["tenant"] != tenant_slug or doc["approval_status"] != "approved":
                continue
            bodies = section_bodies((fixtures_dir / doc["path"]).read_text(encoding="utf-8"))
            for name in doc["sections"]:
                sections.append(
                    Section(
                        evidence_id=f"{doc['document_id']}:v{doc['version']}:{name}",
                        document_id=doc["document_id"],
                        version=doc["version"],
                        section=name,
                        content_sha256=hashes[(doc["document_id"], doc["version"], name)],
                        text=bodies[name],
                        effective_from=doc["effective_from"],
                    )
                )
        return cls(tuple(sections), corpus_version=catalog["fixture_version"])

    def search(self, query: str, limit: int) -> list[Hit]:
        wanted = tokens(query)
        hits = [Hit(s, len(wanted & tokens(s.text))) for s in self.sections]
        hits = [h for h in hits if h.score > 0]
        hits.sort(key=lambda h: (-h.score, h.section.evidence_id))
        return hits[:limit]


def load_corpora(fixtures_dir: Path) -> dict[UUID, Corpus]:
    """One corpus per tenant, keyed by the tenant UUID a resolved handle carries."""
    meta = json.loads((fixtures_dir / "meta.json").read_text(encoding="utf-8"))
    return {UUID(tenant_id): Corpus.load(fixtures_dir, slug) for slug, tenant_id in meta["tenants"].items()}

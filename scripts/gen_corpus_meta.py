"""Generate data/corpus/meta.json and, on request, the lock data/corpus/corpus.sha256 (T17; AM-50, AM-80 fixtures row;
Plan L rulings 12 and 17).

meta.json is derived, never edited: tenant UUIDs from data/seed-ids.json, each asset's tenant UUID and type, alert
UUIDs (uuid5 of `alert/<id>` under the seed namespace, as scripts/gen_fixture_meta.py derives the fixtures' alerts)
with the revisions assets.json gives, and every section's evidence ID, SHA-256, offsets and word count, all from the
files themselves. `tests/plan_l/test_corpus_files.py` and `scripts/verify_handoff.py` regenerate it and compare.

The lock is written only with `--lock`, after an intended change to the corpus; it prints the lock's SHA-256, which
then becomes a new `RELEASES` entry in core/src/ops_core/corpus.py together with a new `corpus_version` in the
catalog (a released version's lock never changes). Paths come from the repository root, never the working directory.

Usage: uv run python -m scripts.gen_corpus_meta [--lock]
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import uuid
from pathlib import Path
from types import ModuleType
from typing import Any

from scripts.gen_seed_ids import NS

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "data/corpus"
SEED_IDS = ROOT / "data/seed-ids.json"
CORPUS_MODULE = ROOT / "core/src/ops_core/corpus.py"


def corpus_module() -> ModuleType:
    """ops_core/corpus.py loaded by path: it is standard-library only, so the checker's default run needs no
    installed package. Registered in sys.modules first, because its dataclasses resolve their module there."""
    name = "ops_core_corpus_by_path"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, CORPUS_MODULE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"{CORPUS_MODULE} is missing")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def generate(root: Path = CORPUS) -> dict[str, Any]:
    """The meta.json document for the corpus directory `root` (tenants always come from SEED_IDS). The lock must match
    the files; whether it is a released one is the checker's question, not the generator's."""
    corpus = corpus_module()
    loaded = corpus.load(root, released=None)
    seeds = json.loads(SEED_IDS.read_text(encoding="utf-8"))["tenants"]
    assets = json.loads((root / corpus.ASSETS).read_text(encoding="utf-8"))
    return {
        "corpus_version": loaded.corpus_version,
        "lock_sha256": loaded.lock_sha256,
        "meta_version": 1,
        "tenants": {slug: seeds[slug] for slug in sorted(loaded.tenants)},
        "assets": [
            {
                "asset_id": a["asset_id"],
                "tenant": a["tenant"],
                "tenant_id": seeds[a["tenant"]],
                "asset_type": a["asset_type"],
            }
            for a in assets["assets"]
        ],
        "alerts": [
            {
                "id": a["id"],
                "asset_id": a["asset_id"],
                "alert_id": str(uuid.uuid5(NS, f"alert/{a['id']}")),
                "revision": a["revision"],
            }
            for a in assets["alerts"]
        ],
        "sections": [
            {
                "evidence_id": doc.evidence_id(section),
                "document_id": doc.document_id,
                "version": doc.version,
                "section": section.name,
                "sha256": section.sha256,
                "start": section.start,
                "end": section.end,
                "words": section.words,
            }
            for doc in loaded.documents
            for section in doc.sections
        ],
    }


def write_lock(root: Path = CORPUS) -> str:
    """Write `root/corpus.sha256` for the files the catalog names and return the lock's SHA-256. A path that is not
    a plain name of an existing file is left out: `load` refuses that entry anyway, and the lock must not follow it
    outside the directory."""
    corpus = corpus_module()
    catalog = json.loads((root / corpus.CATALOG).read_text(encoding="utf-8"))
    paths = [d["path"] for d in catalog["documents"]]
    named = [p for p in paths if isinstance(p, str) and corpus.PATH.fullmatch(p) and (root / p).is_file()]
    text = corpus.lock_text(root, catalog["corpus_version"], named)
    (root / corpus.LOCK).write_text(text, encoding="utf-8", newline="\n")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_meta(root: Path = CORPUS) -> Path:
    """Write `root/meta.json` with LF line endings and no BOM; return its path."""
    path = root / "meta.json"
    path.write_text(json.dumps(generate(root), indent=2) + "\n", encoding="utf-8", newline="\n")
    return path


if __name__ == "__main__":
    if sys.argv[1:] == ["--lock"]:
        print(f"lock sha256 {write_lock()} (add it to RELEASES with a new corpus_version)")
    print(write_meta().relative_to(ROOT).as_posix())

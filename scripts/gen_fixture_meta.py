"""Generate data/handoff-fixtures/meta.json (AM-80 fixtures row): tenant UUIDs, alert UUIDs + revisions, section hashes.

The delivered fixtures identify tenants by slug and alerts by a readable id; the target contracts need UUIDs
(tool-result alerts carry `alert_id` uuid + `revision`, evidence rows carry per-section hashes). Everything here is
derived — from data/seed-ids.json, from the seed namespace, and from the markdown bytes — so the file can always be
regenerated and a test guards it against hand edits. The markdown and catalog.json are not touched: catalog hashes
stay valid. Paths are resolved from the repository root, never the working directory, because the checker imports
`generate` from a tampered copy of the repository whose root is not the current directory.

Usage: uv run python -m scripts.gen_fixture_meta
(`-m` from the repository root, because the module imports `scripts.gen_seed_ids`; running it by path would put
`scripts/` rather than the root on sys.path.)
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from pathlib import Path

from scripts.gen_seed_ids import NS

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "data/handoff-fixtures"
SEED_IDS = ROOT / "data/seed-ids.json"
_HEADING = re.compile(r"^## (?P<name>\S.*?)\s*$")


def section_hashes(path: Path) -> list[tuple[str, str]]:
    """(section, sha256) for each `## ` heading: body = lines until the next `## ` heading, stripped of blank edges."""
    lines = path.read_text(encoding="utf-8").splitlines()
    out: list[tuple[str, str]] = []
    name: str | None = None
    body: list[str] = []

    def flush() -> None:
        if name is not None:
            out.append((name, hashlib.sha256("\n".join(body).strip("\n").encode("utf-8")).hexdigest()))

    for line in lines:
        m = _HEADING.match(line)
        if m:
            flush()
            name, body = m.group("name"), []
        elif name is not None:
            body.append(line)
    flush()
    return out


def generate(root: Path = FIXTURES) -> dict[str, object]:
    """Build the meta.json document for the fixture directory `root` (tenants always come from SEED_IDS)."""
    seeds = json.loads(SEED_IDS.read_text(encoding="utf-8"))
    catalog = json.loads((root / "catalog.json").read_text(encoding="utf-8"))
    observations = json.loads((root / "observations.json").read_text(encoding="utf-8"))
    sections = [
        {"document_id": d["document_id"], "version": d["version"], "section": name, "sha256": digest}
        for d in catalog["documents"]
        for name, digest in section_hashes(root / d["path"])
    ]
    alerts = [
        # uuid5 under the seed namespace keeps alert UUIDs stable across regenerations and machines.
        {"id": a["id"], "alert_id": str(uuid.uuid5(NS, f"alert/{a['id']}")), "revision": 1}
        for a in observations["alerts"]
    ]
    return {
        "fixture_version": catalog["fixture_version"],
        "meta_version": 1,
        "tenants": dict(seeds["tenants"]),
        "alerts": alerts,
        "sections": sections,
    }


def write_meta(root: Path = FIXTURES) -> Path:
    """Write `root/meta.json` with LF line endings and no BOM; return its path."""
    path = root / "meta.json"
    path.write_text(json.dumps(generate(root), indent=2) + "\n", encoding="utf-8", newline="\n")
    return path


if __name__ == "__main__":
    print(write_meta().relative_to(ROOT).as_posix())

"""Write provenance/reference-tree.json: every delivered file under reference/ (stdlib only).

Lists `git ls-files reference` minus the repository-owned reference/README.md, and refuses
to write unless every listed file is byte-identical to zip member operations-copilot/<path>
in provenance/handoff-1.0.zip.
"""

from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ZIP = ROOT / "provenance/handoff-1.0.zip"
OUT = ROOT / "provenance/reference-tree.json"
ZIP_PREFIX = "operations-copilot/"
REPO_OWNED = {"README.md"}


def build() -> dict[str, object]:
    out = subprocess.run(
        ["git", "ls-files", "-z", "reference"], cwd=ROOT, capture_output=True, check=True
    ).stdout.decode("utf-8")
    tracked = sorted(p[len("reference/") :] for p in out.split("\0") if p)
    files = [p for p in tracked if p not in REPO_OWNED]
    bad = []
    with zipfile.ZipFile(ZIP) as z:
        for rel in files:
            try:
                expected = z.read(ZIP_PREFIX + rel)
            except KeyError:
                bad.append(f"not in zip: {rel}")
                continue
            if (ROOT / "reference" / rel).read_bytes() != expected:
                bad.append(f"differs from zip: {rel}")
    if bad:
        raise SystemExit("refusing to write reference-tree.json:\n  " + "\n  ".join(bad))
    return {
        "description": (
            "Every delivered file under reference/ (paths relative to reference/). Each must be "
            "byte-identical to zip member <zip_prefix><path> in provenance/handoff-1.0.zip; "
            "reference/README.md is the only repository-owned file allowed besides these."
        ),
        "zip_prefix": ZIP_PREFIX,
        "files": files,
    }


if __name__ == "__main__":
    data = build()
    OUT.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(ROOT).as_posix()} ({len(data['files'])} files)", file=sys.stderr)

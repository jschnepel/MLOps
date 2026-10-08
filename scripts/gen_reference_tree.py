"""Write provenance/reference-tree.json: every delivered file under reference/ (stdlib only).

Lists `git ls-files reference` minus the repository-owned reference/README.md, and refuses
to write unless every listed file is byte-identical to zip member operations-copilot/<path>
in provenance/handoff-1.0.zip.

scripts/verify_handoff.py reads the result to enforce the whole reference/ tree (final review F1), not only the
files that have an individual hash. Run it after any deliberate change to what is delivered under reference/.
"""

from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# The delivered 1.0 package is the authority; the working tree is only what we are checking against it.
ZIP = ROOT / "provenance/handoff-1.0.zip"
OUT = ROOT / "provenance/reference-tree.json"
ZIP_PREFIX = "operations-copilot/"
# Files under reference/ that this repository wrote itself, so they have no zip counterpart.
REPO_OWNED = {"README.md"}


def build() -> dict[str, object]:
    """Return the reference-tree document, exiting without a result if any tracked file differs from the zip."""
    # `git ls-files` (NUL-separated, safe for any file name) lists only tracked files, so untracked caches and
    # build output under reference/ never enter the list.
    out = subprocess.run(
        ["git", "ls-files", "-z", "reference"], cwd=ROOT, capture_output=True, check=True
    ).stdout.decode("utf-8")
    tracked = sorted(p[len("reference/") :] for p in out.split("\0") if p)
    files = [p for p in tracked if p not in REPO_OWNED]
    bad = []
    # Compare bytes, not hashes, so a failure can say exactly which file differs.
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

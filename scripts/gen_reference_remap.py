"""Map original reference-code paths to their new locations under reference/ (same sha256). Stdlib only.

T42 moved the inherited code under reference/. provenance/reference-code-hashes.json still lists the original
paths, so this script writes provenance/reference-code-hashes.remap.json (old path -> new path), which
scripts/verify_handoff.py uses to keep checking the original hashes. Run it once after the move; it refuses to
write if any moved file no longer has its original sha256.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

# The three top-level directories of the original kit that T42 relocated; anything else is a mistake.
PREFIXES = [("src/", "reference/src/"), ("tests/", "reference/tests/"), ("integrations/", "reference/integrations/")]


def remap_path(old: str) -> str:
    """Return the path under reference/ for an original kit path; raise ValueError if no rule covers it."""
    for a, b in PREFIXES:
        if old.startswith(a):
            return b + old[len(a) :]
    raise ValueError(f"no remap rule for {old}")


def build() -> dict[str, str]:
    """Return {old path: new path}, exiting if any moved file's sha256 differs from the recorded one."""
    entries = json.loads(Path("provenance/reference-code-hashes.json").read_text(encoding="utf-8"))["files"]
    out: dict[str, str] = {}
    for e in entries:
        new = remap_path(e["path"])
        actual = hashlib.sha256(Path(new).read_bytes()).hexdigest()
        # A mismatch means the move (or a line-ending conversion) changed the file; the remap must never
        # paper over that.
        if actual != e["sha256"]:
            raise SystemExit(f"hash mismatch after move: {e['path']} -> {new}")
        out[e["path"]] = new
    return out


if __name__ == "__main__":
    Path("provenance/reference-code-hashes.remap.json").write_text(
        json.dumps(build(), indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print("wrote provenance/reference-code-hashes.remap.json", file=sys.stderr)

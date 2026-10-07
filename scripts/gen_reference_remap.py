"""Map original reference-code paths to their new locations under reference/ (same sha256). Stdlib only."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

PREFIXES = [("src/", "reference/src/"), ("tests/", "reference/tests/"), ("integrations/", "reference/integrations/")]


def remap_path(old: str) -> str:
    for a, b in PREFIXES:
        if old.startswith(a):
            return b + old[len(a):]
    raise ValueError(f"no remap rule for {old}")


def build() -> dict[str, str]:
    entries = json.loads(Path("provenance/reference-code-hashes.json").read_text(encoding="utf-8"))["files"]
    out: dict[str, str] = {}
    for e in entries:
        new = remap_path(e["path"])
        actual = hashlib.sha256(Path(new).read_bytes()).hexdigest()
        if actual != e["sha256"]:
            raise SystemExit(f"hash mismatch after move: {e['path']} -> {new}")
        out[e["path"]] = new
    return out


if __name__ == "__main__":
    Path("provenance/reference-code-hashes.remap.json").write_text(json.dumps(build(), indent=2) + "\n", encoding="utf-8", newline="\n")
    print("wrote provenance/reference-code-hashes.remap.json", file=sys.stderr)

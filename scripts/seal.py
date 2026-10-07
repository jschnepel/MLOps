"""Print `<sha256>  <name>` lines for files, over their exact bytes. Stdlib only.

Usage: python -I scripts/seal.py <file> [<file> ...]
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def seal_lines(paths: list[Path]) -> list[str]:
    return [f"{sha256_of(p)}  {p.name}" for p in paths]


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    for line in seal_lines([Path(a) for a in argv]):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

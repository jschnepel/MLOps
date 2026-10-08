"""Print `<sha256>  <name>` lines for files, over their exact bytes. Stdlib only.

T03 uses it to seal the holdout: the owner runs it over the holdout cases and the two prompts and commits the
three lines as evals/holdout.sha256 (AM-50), so any later edit to either is detectable. Output matches the
`sha256sum` text format, so `sha256sum -c` can verify it from the same directory.

Usage: python -I scripts/seal.py <file> [<file> ...]
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path


def sha256_of(path: Path) -> str:
    """Hex sha256 of the file's exact bytes; no newline translation, so a CRLF conversion changes the digest."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def seal_lines(paths: list[Path]) -> list[str]:
    """One `<sha256>  <file name>` line per path; only the name is printed so the seal does not depend on location."""
    return [f"{sha256_of(p)}  {p.name}" for p in paths]


def main(argv: list[str]) -> int:
    if not argv:
        # Exit 2 (usage error) so a script that forgets its arguments cannot be mistaken for a successful seal.
        print(__doc__, file=sys.stderr)
        return 2
    for line in seal_lines([Path(a) for a in argv]):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

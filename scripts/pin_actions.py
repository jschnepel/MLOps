"""Resolve GitHub Action tags to full commit SHAs with `git ls-remote`. Stdlib only. Prints `owner/repo@sha # tag`.

Handles lightweight tags (two tokens) and annotated tags (four tokens; the peeled `^{}` line is the commit).
Usage: python -I scripts/pin_actions.py actions/checkout@v5 astral-sh/setup-uv@v6
"""

from __future__ import annotations

import subprocess
import sys


def resolve(spec: str) -> str:
    repo, tag = spec.split("@", 1)
    out = subprocess.run(
        ["git", "ls-remote", f"https://github.com/{repo}.git", f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    if not out:
        raise SystemExit(f"tag not found: {spec}")
    sha = out[-2] if len(out) >= 4 else out[0]
    return f"{repo}@{sha} # {tag}"


if __name__ == "__main__":
    for s in sys.argv[1:]:
        print(resolve(s))

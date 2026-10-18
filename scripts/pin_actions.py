"""Resolve GitHub Action tags to full commit SHAs with `git ls-remote`. Stdlib only. Prints `owner/repo@sha # tag`.

Handles lightweight tags (two tokens) and annotated tags (four tokens; the peeled `^{}` line is the commit).
Usage: python -I scripts/pin_actions.py actions/checkout@v5 astral-sh/setup-uv@v6

A tag can be moved to different code after we review it, so .github/workflows/ci.yml pins each action to the
commit SHA (T06) and keeps the tag only as a trailing comment. The owner runs this by hand, with network access,
when deliberately bumping an action; CI never runs it.
"""

from __future__ import annotations

import subprocess
import sys


def resolve(spec: str) -> str:
    """Turn `owner/repo@tag` into `owner/repo@<commit sha> # tag`, ready to paste into a workflow."""
    repo, tag = spec.split("@", 1)
    # Ask for both the tag and its peeled form (`^{}`): for an annotated tag only the peeled line names the commit.
    out = subprocess.run(
        ["git", "ls-remote", f"https://github.com/{repo}.git", f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    if not out:
        raise SystemExit(f"tag not found: {spec}")
    # ls-remote prints `<sha> <ref>` pairs: two tokens for a lightweight tag, four for an annotated one, whose
    # second pair is the peeled commit.
    sha = out[-2] if len(out) >= 4 else out[0]
    return f"{repo}@{sha} # {tag}"


if __name__ == "__main__":
    for s in sys.argv[1:]:
        print(resolve(s))

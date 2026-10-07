"""The one command: ruff, mypy, pytest. Exit 0 only if all pass.

Usage (a fresh clone needs nothing else; `uv run` syncs the root, which depends on every member):
    uv sync --locked
    uv run python scripts/check.py
"""

from __future__ import annotations

import subprocess
import sys

MEMBER_SRC = ["core/src", "api/src", "worker/src", "mcp-read/src", "mcp-write/src", "asset-sim/src", "incident-sim/src"]


def run(cmd: list[str]) -> int:
    print("$", " ".join(cmd), flush=True)
    return subprocess.run(cmd, check=False).returncode


def members_importable() -> bool:
    try:
        import ops_core  # noqa: F401
    except ImportError as exc:
        print(f"CHECK: RED: workspace members are not installed ({exc}); run: uv sync --locked", flush=True)
        return False
    return True


def main() -> int:
    if not members_importable():
        return 1
    steps = [
        [sys.executable, "-m", "ruff", "check", "."],
        [sys.executable, "-m", "ruff", "format", "--check", "."],
        [sys.executable, "-m", "mypy", *MEMBER_SRC],
        [sys.executable, "-m", "pytest", "-q"],
    ]
    rc = 0
    for cmd in steps:
        rc = run(cmd) or rc
    print("CHECK:", "GREEN" if rc == 0 else "RED")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())

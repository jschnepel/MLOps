"""The one command: ruff, mypy, pytest. Exit 0 only if all pass.

Usage (a fresh clone needs nothing else; `uv run` syncs the root, which depends on every member):
    uv sync --locked
    uv run python scripts/check.py

CI runs exactly this command, so "green locally" and "green in CI" mean the same thing.
"""

from __future__ import annotations

import subprocess
import sys

# mypy runs on the member source trees only; reference/ is hash-pinned inherited code and must not be type-checked
# (or changed) here.
MEMBER_SRC = ["core/src", "api/src", "worker/src", "mcp-read/src", "mcp-write/src", "asset-sim/src", "incident-sim/src"]


def run(cmd: list[str]) -> int:
    """Echo a command, run it and return its exit code."""
    print("$", " ".join(cmd), flush=True)
    return subprocess.run(cmd, check=False).returncode


def members_importable() -> bool:
    """Return True when the workspace members are installed, else print how to fix it.

    Without this guard a bare `python scripts/check.py` on a fresh clone fails deep inside mypy and pytest with
    import errors that hide the real cause (final review F2).
    """
    try:
        # Imported only to prove the workspace is synced; ops_core is a representative member, hence the noqa.
        import ops_core  # noqa: F401
    except ImportError as exc:
        print(f"CHECK: RED: workspace members are not installed ({exc}); run: uv sync --locked", flush=True)
        return False
    return True


def main() -> int:
    if not members_importable():
        return 1
    # sys.executable keeps every tool inside the interpreter (and virtual environment) that launched this script.
    steps = [
        [sys.executable, "-m", "ruff", "check", "."],
        [sys.executable, "-m", "ruff", "format", "--check", "."],
        [sys.executable, "-m", "mypy", *MEMBER_SRC],
        [sys.executable, "-m", "pytest", "-q"],
    ]
    rc = 0
    # Run every step even after a failure so one invocation reports lint, format, type and test problems together;
    # `or rc` keeps the first non-zero code rather than letting a later success overwrite it.
    for cmd in steps:
        rc = run(cmd) or rc
    print("CHECK:", "GREEN" if rc == 0 else "RED")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())

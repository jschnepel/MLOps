"""The one command: ruff, mypy, pytest. Exit 0 only if all pass.

Usage (a fresh clone needs nothing else; `uv run` syncs the root, which depends on every member):
    uv sync --locked
    uv run python scripts/check.py
    uv run python scripts/check.py --profile test    # also runs the live suite; needs the dev stack up

CI runs exactly this command, so "green locally" and "green in CI" mean the same thing.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    # Imported for the annotations only: the runtime import is lazy so members_importable() can still print its
    # friendly message on an unsynced clone instead of failing here.
    from ops_core.settings import Profile

# mypy runs on the member source trees only; reference/ is hash-pinned inherited code and must not be type-checked
# (or changed) here.
MEMBER_SRC = ["core/src", "api/src", "worker/src", "mcp-read/src", "mcp-write/src", "asset-sim/src", "incident-sim/src"]


def run(cmd: list[str], env: dict[str, str] | None = None) -> int:
    """Echo a command, run it (with the given environment, default inherited) and return its exit code."""
    print("$", " ".join(cmd), flush=True)
    return subprocess.run(cmd, check=False, env=env).returncode


def check_profile(argv: list[str]) -> Profile:
    """`--profile dev` (default, database-free) or `--profile test` (the live suite against the test databases)."""
    from ops_core.settings import Profile

    parser = argparse.ArgumentParser(description="ruff, ruff format, mypy, pytest")
    choices = [p.value for p in Profile if p is not Profile.DEMO]
    parser.add_argument("--profile", choices=choices, default=Profile.DEV.value)
    return Profile(parser.parse_args(argv).profile)


def environment_for(profile: Profile, base: Mapping[str, str]) -> dict[str, str]:
    """The child environment: the test profile switches the live gate on and names itself (SA:529)."""
    from ops_core.settings import Profile

    env = dict(base)
    if profile is Profile.TEST:
        env["OPS_LIVE"] = "1"
        env["PROFILE"] = profile.value
    return env


def members_importable() -> bool:
    """Return True when the workspace members are installed, else print how to fix it.

    Without this guard a bare `python scripts/check.py` on a fresh clone fails deep inside mypy and pytest with
    import errors that hide the real cause (final review I2, fix F2).
    """
    try:
        # Imported only to prove the workspace is synced; ops_core is a representative member, hence the noqa.
        import ops_core  # noqa: F401
    except ImportError as exc:
        print(f"CHECK: RED: workspace members are not installed ({exc}); run: uv sync --locked", flush=True)
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    """Run ruff, ruff format, mypy and pytest; return 0 only if all pass, 1 if the workspace is not installed."""
    # Guard first: resolving the profile imports ops_core, which must not be what fails on an unsynced clone.
    if not members_importable():
        return 1
    env = environment_for(check_profile(sys.argv[1:] if argv is None else argv), os.environ)
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
        rc = run(cmd, env) or rc
    print("CHECK:", "GREEN" if rc == 0 else "RED")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())

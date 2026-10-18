"""Capture the baseline environment as JSON. Stdlib only.

T01 records which OS and tool versions the reference baseline was reproduced with, so a later failure can be
told apart from an environment change. The owner runs it once per baseline refresh; the result is committed as
reports/baseline/environment.json. A tool that is not installed is recorded as null, never as a guess.

Usage: python -I scripts/baseline_env.py <path-to-venv-python>
"""

from __future__ import annotations

import json
import platform
import subprocess
import sys
from pathlib import Path


def tool_version(cmd: list[str]) -> str | None:
    """Return the first line of the version a command prints, or None when it is missing, fails or hangs."""
    try:
        # The 20 s cap stops a wedged tool (a daemon that never answers `--version`) from hanging the capture.
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    # Some tools write their version banner to stderr rather than stdout, so fall back to it.
    text = out.stdout.strip() or out.stderr.strip()
    return text.splitlines()[0] if text else None


def capture(venv_python: str) -> dict:
    """Collect the host OS and the version of every tool the baseline depends on."""
    return {
        "os": platform.platform(),
        # The interpreter running this script; the project's own interpreter is the venv_python entry below.
        "python_host": sys.version.split()[0],
        "venv_python": tool_version([venv_python, "--version"]),
        "uv": tool_version(["uv", "--version"]),
        "docker": tool_version(["docker", "--version"]),
        "ollama": tool_version(["ollama", "--version"]),
        "pytest": tool_version([venv_python, "-m", "pytest", "--version"]),
    }


def main() -> int:
    """Write the capture to reports/baseline/environment.json and return 0 (exit code for the shell)."""
    venv_python = sys.argv[1]
    out = Path("reports/baseline/environment.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    # newline="\n" because text mode on Windows would write CRLF, and the committed capture must be LF
    # (commit b80f94f, 'T01: normalize baseline captures to UTF-8/LF'); the same applies to every file these
    # scripts write.
    out.write_text(json.dumps(capture(venv_python), indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

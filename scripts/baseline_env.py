"""Capture the baseline environment as JSON. Stdlib only.

Usage: python -I scripts/baseline_env.py <path-to-venv-python>
"""
from __future__ import annotations

import json
import platform
import subprocess
import sys
from pathlib import Path


def tool_version(cmd: list[str]) -> str | None:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    text = out.stdout.strip() or out.stderr.strip()
    return text.splitlines()[0] if text else None


def capture(venv_python: str) -> dict:
    return {
        "os": platform.platform(),
        "python_host": sys.version.split()[0],
        "venv_python": tool_version([venv_python, "--version"]),
        "uv": tool_version(["uv", "--version"]),
        "docker": tool_version(["docker", "--version"]),
        "ollama": tool_version(["ollama", "--version"]),
        "pytest": tool_version([venv_python, "-m", "pytest", "--version"]),
    }


def main() -> int:
    venv_python = sys.argv[1]
    out = Path("reports/baseline/environment.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(capture(venv_python), indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

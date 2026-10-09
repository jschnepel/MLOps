"""Live fixtures: only with OPS_LIVE=1 and a running dev profile. Secrets are read from files, never printed."""

import json
import os
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def live() -> None:
    # Live tests need Docker and a running stack, so they are opt-in and `scripts/check.py` skips them.
    if os.environ.get("OPS_LIVE") != "1":
        pytest.skip("live dev-profile tests run only with OPS_LIVE=1")


@pytest.fixture(scope="session")
def env(live: None) -> dict[str, str]:
    text = Path(".env").read_text(encoding="utf-8")
    pairs = (line.split("=", 1) for line in text.splitlines() if line and not line.startswith("#"))
    return {k: v for k, v in pairs}


@pytest.fixture(scope="session")
def secret(env: dict[str, str]) -> Callable[[str], str]:
    def read(name: str) -> str:
        return (Path(env["OPS_SECRETS_DIR"]) / name).read_text(encoding="utf-8")

    return read


@pytest.fixture(scope="session")
def compose_ps(live: None) -> list[dict]:
    # `ps --format json` prints one JSON object per line (not one array), hence the line-by-line parse.
    out = subprocess.run(
        ["docker", "compose", "--profile", "dev", "ps", "--format", "json"], capture_output=True, text=True, check=True
    ).stdout
    rows = [json.loads(line) for line in out.splitlines() if line.strip()]
    return rows

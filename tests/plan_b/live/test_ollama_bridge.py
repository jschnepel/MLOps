"""T44 DoD (agent half): a container reaches the host's Ollama; host callers use 127.0.0.1.

Catches a wrong `OLLAMA_BASE_URL_CONTAINER` (or a loopback-only listener Docker cannot reach): both routes must
answer the same Ollama version. No system setting is changed; the test only reads `/api/version`.
"""

import json
import subprocess
import urllib.request
from pathlib import Path

# Pinned by digest like every other image in the dev stack; it only runs a one-off urllib call.
HELPER_IMAGE = "python:3.13-slim@sha256:bf44cdfcb76cd3b41e879bc058fc37ec5872002ccfde7fcb765e218cde0cd79c"
EVIDENCE = Path("reports/bootstrap/ollama-bridge.txt")


def test_host_and_container_reach_ollama(env: dict[str, str]) -> None:
    with urllib.request.urlopen(f"{env['OLLAMA_BASE_URL_HOST']}/api/version", timeout=10) as r:
        host_version = json.loads(r.read())["version"]
    container_url = f"{env['OLLAMA_BASE_URL_CONTAINER']}/api/version"
    script = (
        "import json,urllib.request;"
        f"print(json.loads(urllib.request.urlopen('{container_url}',timeout=10).read())['version'])"
    )
    container_version = subprocess.run(
        ["docker", "run", "--rm", HELPER_IMAGE, "python", "-c", script],
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    ).stdout.strip()
    assert container_version == host_version
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(
        f"host {env['OLLAMA_BASE_URL_HOST']}/api/version -> {host_version}\n"
        f"container {env['OLLAMA_BASE_URL_CONTAINER']}/api/version -> {container_version}\n",
        encoding="utf-8",
        newline="\n",
    )

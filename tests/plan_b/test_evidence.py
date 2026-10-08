"""Nothing under reports/bootstrap/ may contain a token, a password or a client secret.

Locally the generated secret values are read from the secrets directory (`.env`'s OPS_SECRETS_DIR, else the default)
and must not appear in any evidence file; in CI no secrets exist, so only the JWT-shape check applies.
"""

import re
from pathlib import Path

from scripts.bootstrap_dev import secrets_dir

JWT = re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")


def local_secrets_dir() -> Path:
    """The secrets directory this machine's stack uses: `.env` wins so a relocated directory is still scanned."""
    env_file = Path(".env")
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("OPS_SECRETS_DIR="):
                return Path(line.split("=", 1)[1])
    return secrets_dir()


def test_evidence_has_no_token_shapes():
    root = Path("reports/bootstrap")
    if not root.exists():
        return
    directory = local_secrets_dir()
    values = [p.read_text(encoding="utf-8") for p in directory.glob("*")] if directory.exists() else []
    for path in root.rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            assert not JWT.search(text), path
            for v in values:
                assert v not in text, path

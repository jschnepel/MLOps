"""Nothing under reports/bootstrap/ or reports/skeleton/ may contain a token, a password or a client secret.

Locally the generated secret values are read from the secrets directory (`.env`'s OPS_SECRETS_DIR, else the default)
and must not appear in any evidence file; in CI no secrets exist, so only the JWT-shape check applies.
`reports/auth` (T11's session and revocation evidence) and `reports/ci` (T06's CI run record) are scanned the
same way.
"""

import re
import sys
from pathlib import Path

import pytest

from scripts.bootstrap_dev import secrets_dir

EVIDENCE_ROOTS = (Path("reports/bootstrap"), Path("reports/skeleton"), Path("reports/auth"), Path("reports/ci"))
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
    directory = local_secrets_dir()
    files = [p for p in directory.glob("*") if p.is_file()] if directory.exists() else []
    # Empty values are skipped: "" is a substring of every text and would fail every file.
    values = [v for v in (p.read_text(encoding="utf-8").strip() for p in files) if v]
    # Pytest's assertion rewriting prints the operands of a failed `assert`, even with a custom message, so asserting
    # `v not in text` would print the secret and the whole evidence file. Collect (file name, index of the secret)
    # pairs instead and assert on that list only; neither a value nor any file text reaches the message.
    token_files = []
    leaked = []
    for root in EVIDENCE_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file():
                text = path.read_text(encoding="utf-8")
                if JWT.search(text):
                    token_files.append(path.name)
                leaked.extend((path.name, i) for i, v in enumerate(values) if v in text)
    assert not token_files, f"evidence files containing a JWT-shaped token: {token_files}"
    assert not leaked, f"evidence files containing a generated secret, as (file, secret index): {leaked}"


def test_evidence_failure_message_never_prints_the_literal(tmp_path, monkeypatch):
    # Proof for the redaction claim, with a fake secrets directory and a tampered evidence directory. Under the old
    # `assert v not in text, path` form pytest printed both the secret and the file text and this test failed.
    literal = "LITERAL-SECRET-DO-NOT-PRINT-7f3a"
    fake_secrets = tmp_path / "secrets"
    fake_secrets.mkdir()
    (fake_secrets / "kc_fake").write_text(literal + "\n", encoding="utf-8")
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "run.txt").write_text(f"admin password is {literal} oops\n", encoding="utf-8")
    module = sys.modules[__name__]
    monkeypatch.setattr(module, "local_secrets_dir", lambda: fake_secrets)
    monkeypatch.setattr(module, "EVIDENCE_ROOTS", (evidence,))
    with pytest.raises(AssertionError) as excinfo:
        test_evidence_has_no_token_shapes()
    assert literal not in str(excinfo.value)
    assert "run.txt" in str(excinfo.value)

"""Protect scripts/seal.py and the sealed holdout record evals/holdout.sha256 (T03, AM-50).

These tests catch a seal that hashes anything other than the exact bytes (for example after newline translation),
a changed output format, and a seal file whose prompt hashes no longer match the prompts the probe is allowed to run.
"""

import hashlib
import re
from pathlib import Path

import pytest

from scripts.seal import seal_lines, sha256_of


def test_sha256_of_exact_bytes(tmp_path: Path):
    p = tmp_path / "a.txt"
    p.write_bytes(b"hello\n")  # write_bytes so the test controls the exact bytes on every platform
    assert sha256_of(p) == hashlib.sha256(b"hello\n").hexdigest()


def test_seal_lines_format(tmp_path: Path):
    p = tmp_path / "cases.jsonl"
    p.write_bytes(b"{}\n")
    expected_digest = hashlib.sha256(b"{}\n").hexdigest()
    assert seal_lines([p]) == [f"{expected_digest}  cases.jsonl"]


@pytest.mark.skipif(
    not Path("evals/holdout.sha256").exists(),
    reason="owner has not sealed the holdout yet (T03 step 9)",
)
def test_holdout_seal_file_has_three_lines_and_prompt_hashes():
    lines = Path("evals/holdout.sha256").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    for line in lines:
        assert re.fullmatch(r"[0-9a-f]{64}  [A-Za-z0-9._-]+", line), line
    # Lines 2 and 3 are the two sealed prompts; these digests are the same ones pinned in scripts/probe.py.
    assert lines[1].startswith("e3c26da349dcb0a9bfafb6c786a06f15fece389c21fa63b1b64fef7659b6a942  ")
    assert lines[2].startswith("8b6658eb0f08136699b78e7ab1d76972f88f4399db720e92e5be5335b0c7c343  ")

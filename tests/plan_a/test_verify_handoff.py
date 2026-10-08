"""Protect scripts/verify_handoff.py, the integrity gate for the delivered handoff and reference/.

It serves T42 and final review I1 (fix F1).

The checker is the only thing stopping hash-pinned inherited code from drifting unnoticed. These tests run it as a
subprocess against the real repository and against tampered copies, and catch a checker that passes when it should
fail: a modified, deleted or added file under reference/, a remap target outside reference/, or a corrupted zip.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

# -I matches how CI runs the checker: no environment variables or working-directory modules can alter it.
CHECKER = [sys.executable, "-I", "scripts/verify_handoff.py"]


def test_remap_file_covers_every_original_entry_with_identical_hash():
    original = {
        e["path"]: e["sha256"]
        for e in json.loads(Path("provenance/reference-code-hashes.json").read_text(encoding="utf-8"))["files"]
    }
    remap = json.loads(Path("provenance/reference-code-hashes.remap.json").read_text(encoding="utf-8"))
    assert set(remap) == set(original)
    for old, new in remap.items():
        assert hashlib.sha256(Path(new).read_bytes()).hexdigest() == original[old], (old, new)


def test_reference_code_check_passes():
    out = subprocess.run(CHECKER + ["--reference-code"], capture_output=True, text=True, check=False)
    assert out.returncode == 0, out.stdout + out.stderr
    # 19 and the counts below are the size of the delivered package; they change only if the reference set does.
    assert "PASS: 19 inherited" in out.stdout


def test_manifest_check_passes_against_zip():
    out = subprocess.run(CHECKER + ["--manifest"], capture_output=True, text=True, check=False)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "PASS: 161 delivered 1.0 snapshot checksums" in out.stdout


def test_manifest_check_fails_on_corrupted_zip(tmp_path: Path):
    bad = tmp_path / "handoff-1.0.zip"
    with zipfile.ZipFile("provenance/handoff-1.0.zip") as src, zipfile.ZipFile(bad, "w") as dst:
        for info in src.infolist():
            data = src.read(info)
            if info.filename.endswith("README.md"):
                data = data + b"\n# tampered\n"
            dst.writestr(info, data)
    out = subprocess.run(CHECKER + ["--manifest", "--zip", str(bad)], capture_output=True, text=True, check=False)
    assert out.returncode != 0
    assert "mismatch" in (out.stdout + out.stderr).lower()


def test_checker_skips_venv_dirs():
    # A local environment can hold files that are not valid package content; the repository-wide syntax check
    # must ignore directories starting with ".venv" rather than fail on them.
    junk = Path(".venv-probe-junk")
    junk.mkdir(exist_ok=True)
    try:
        (junk / "bad.py").write_text("this is not python (", encoding="utf-8")
        out = subprocess.run(CHECKER, capture_output=True, text=True, check=False)
        assert out.returncode == 0, out.stdout + out.stderr
    finally:
        shutil.rmtree(junk)


def _tracked_copy(tmp_path: Path) -> Path:
    """Copy every git-tracked file (the repository as a fresh clone sees it) to a temporary root.

    Tampering tests must never touch the real working tree, and using tracked files only keeps local caches and
    environments out of the copy so the untouched baseline behaves like CI.
    """
    root = tmp_path / "repo"
    listed = subprocess.run(["git", "ls-files", "-z"], capture_output=True, check=True).stdout.decode("utf-8")
    for rel in filter(None, listed.split("\0")):
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(rel, dst)
    return root


def _run_tree(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", str(root / "scripts/verify_handoff.py"), "--reference-code"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


def test_reference_tree_passes_on_untouched_copy(tmp_path: Path):
    out = _run_tree(_tracked_copy(tmp_path))
    assert out.returncode == 0, out.stdout + out.stderr
    assert "PASS: 26 delivered reference/ files" in out.stdout


def test_reference_tree_fails_on_modified_unhashed_file(tmp_path: Path):
    root = _tracked_copy(tmp_path)
    # Makefile has no individual hash entry, so only the whole-tree check (F1) can notice this edit.
    with (root / "reference/Makefile").open("ab") as f:
        f.write(b"\n# tampered\n")
    out = _run_tree(root)
    assert out.returncode != 0
    assert "FAIL: modified: reference/Makefile" in out.stdout


def test_reference_tree_fails_on_deleted_file(tmp_path: Path):
    root = _tracked_copy(tmp_path)
    (root / "reference/Dockerfile").unlink()
    out = _run_tree(root)
    assert out.returncode != 0
    assert "FAIL: missing: reference/Dockerfile" in out.stdout


def test_reference_tree_fails_on_added_file(tmp_path: Path):
    root = _tracked_copy(tmp_path)
    (root / "reference/src/operations_copilot/evil.py").write_text("import os\n", encoding="utf-8")
    out = _run_tree(root)
    assert out.returncode != 0
    assert "FAIL: unexpected file: reference/src/operations_copilot/evil.py" in out.stdout


def test_reference_tree_fails_on_remap_outside_reference(tmp_path: Path):
    root = _tracked_copy(tmp_path)
    remap_path = root / "provenance/reference-code-hashes.remap.json"
    remap = json.loads(remap_path.read_text(encoding="utf-8"))
    # Point a remap entry at a byte-identical copy outside reference/: the hash would still match, so only the
    # explicit "under reference/" rule can reject it.
    remap["tests/conftest.py"] = "scripts/conftest.py"
    shutil.copyfile(root / "reference/tests/conftest.py", root / "scripts/conftest.py")
    remap_path.write_text(json.dumps(remap, indent=2) + "\n", encoding="utf-8", newline="\n")
    out = _run_tree(root)
    assert out.returncode != 0
    assert "FAIL: remap target outside reference/: tests/conftest.py -> scripts/conftest.py" in out.stdout


def _run_contracts(copy: Path) -> subprocess.CompletedProcess[str]:
    """Run `--contracts` on a copy; the checker prints PASS lines to stdout and its FAIL line to stderr."""
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    return subprocess.run(
        [sys.executable, "-I", "scripts/verify_handoff.py", "--contracts"],
        cwd=copy,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_contracts_pass_on_the_committed_tree(tmp_path: Path):
    r = _run_contracts(_tracked_copy(tmp_path))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "negative examples failed for their stated reason" in r.stdout


def test_contracts_fail_when_a_negative_example_validates(tmp_path: Path):
    copy = _tracked_copy(tmp_path)
    p = copy / "schemas/examples/message-invalid-kind-question.json"
    # newline="\n": on Windows the default would write CRLF, and the CR check would then fire first.
    p.write_text(p.read_text(encoding="utf-8").replace('"question"', '"ask"'), encoding="utf-8", newline="\n")
    r = _run_contracts(copy)
    out = r.stdout + r.stderr
    assert r.returncode == 1 and "message-invalid-kind-question.json" in out and "validated" in out


def test_contracts_fail_when_a_negative_fails_for_the_wrong_reason(tmp_path: Path):
    copy = _tracked_copy(tmp_path)
    p = copy / "schemas/examples/message-invalid-kind-question.json"
    doc = json.loads(p.read_text(encoding="utf-8"))
    doc["kind"] = "ask"
    doc["tenant_id"] = "x"  # now invalid for an unrelated reason
    p.write_text(json.dumps(doc), encoding="utf-8", newline="\n")
    r = _run_contracts(copy)
    assert r.returncode == 1 and "stated reason" in r.stdout + r.stderr


def test_contracts_reject_a_carriage_return_in_a_governed_file(tmp_path: Path):
    copy = _tracked_copy(tmp_path)
    p = copy / "schemas/examples/message-valid.json"
    p.write_bytes(p.read_bytes().replace(b"\n", b"\r\n", 1))
    r = _run_contracts(copy)
    assert r.returncode == 1 and "carriage return" in r.stdout + r.stderr


def test_contracts_require_index_version(tmp_path: Path):
    copy = _tracked_copy(tmp_path)
    p = copy / "schemas/examples/index.json"
    doc = json.loads(p.read_text(encoding="utf-8"))
    doc["version"] = "1.0"
    p.write_text(json.dumps(doc), encoding="utf-8", newline="\n")
    r = _run_contracts(copy)
    assert r.returncode == 1 and "index.json version" in r.stdout + r.stderr

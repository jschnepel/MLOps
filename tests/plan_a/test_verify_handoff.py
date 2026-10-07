import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

CHECKER = [sys.executable, "-I", "scripts/verify_handoff.py"]


def test_remap_file_covers_every_original_entry_with_identical_hash():
    original = {e["path"]: e["sha256"] for e in json.loads(Path("provenance/reference-code-hashes.json").read_text(encoding="utf-8"))["files"]}
    remap = json.loads(Path("provenance/reference-code-hashes.remap.json").read_text(encoding="utf-8"))
    assert set(remap) == set(original)
    for old, new in remap.items():
        assert hashlib.sha256(Path(new).read_bytes()).hexdigest() == original[old], (old, new)


def test_reference_code_check_passes():
    out = subprocess.run(CHECKER + ["--reference-code"], capture_output=True, text=True, check=False)
    assert out.returncode == 0, out.stdout + out.stderr
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
    junk = Path(".venv-probe-junk")
    junk.mkdir(exist_ok=True)
    try:
        (junk / "bad.py").write_text("this is not python (", encoding="utf-8")
        out = subprocess.run(CHECKER, capture_output=True, text=True, check=False)
        assert out.returncode == 0, out.stdout + out.stderr
    finally:
        shutil.rmtree(junk)

"""No tracked text file may contain a carriage return or a UTF-8 byte-order mark.

Windows PowerShell 5.1 writes a BOM and CRLF by default (`>`, `Out-File`, `Set-Content`), and a raw CR inside a shell
command survives copy-paste as nothing at all (`tr -d '<CR>'` becomes `tr -d ''`). `.gitattributes` (`* text=auto
eol=lf`) normalises line endings only for files git considers text, and it cannot repair a CR in the middle of a
line, so this scan is the guard. `reference/` holds hash-pinned files and is exempt; binary formats are skipped.
"""

import subprocess
from pathlib import Path

BINARY = {".png", ".jpg", ".zip", ".ico", ".pdf"}


def tracked_text_files() -> list[str]:
    """Tracked paths outside `reference/` whose extension is not a known binary one."""
    out = subprocess.run(["git", "ls-files", "-z"], capture_output=True, check=True).stdout
    paths = [p.decode("utf-8") for p in out.split(b"\0") if p]
    return [p for p in paths if not p.startswith("reference/") and Path(p).suffix.lower() not in BINARY]


def test_no_carriage_return_or_bom_in_tracked_text():
    bad = []
    for path in tracked_text_files():
        raw = Path(path).read_bytes()
        if b"\r" in raw or raw.startswith(b"\xef\xbb\xbf"):
            bad.append(path)
    assert not bad, f"files with a CR byte or a BOM: {bad}"

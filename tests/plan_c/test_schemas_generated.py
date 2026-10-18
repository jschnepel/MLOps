"""The committed contract set under schemas/ is exactly what scripts/build_schemas.py generates (T45, AM-80).

Catches: a hand edit of a schema, an example or index.json (the generator is the one source of truth, so the edit
would be lost or, worse, silently disagree with the code's enums), a JSON file under schemas/ that the generator does
not own, and a generator change that was never rerun.
"""

from pathlib import Path

from scripts import build_schemas


def _json_files(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in (root / "schemas").rglob("*.json")}


def test_every_json_file_under_schemas_is_generated(tmp_path: Path):
    build_schemas.write(tmp_path)
    assert _json_files(build_schemas.ROOT) == _json_files(tmp_path)


def test_committed_files_match_the_generator_byte_for_byte(tmp_path: Path):
    build_schemas.write(tmp_path)
    stale = [
        rel
        for rel in sorted(_json_files(tmp_path))
        if (build_schemas.ROOT / rel).read_bytes() != (tmp_path / rel).read_bytes()
    ]
    assert not stale, f"regenerate with `uv run python -m scripts.build_schemas`: {stale}"

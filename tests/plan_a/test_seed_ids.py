import json
import uuid
from pathlib import Path

from scripts.gen_seed_ids import generate, write_seed_ids

PERSONAS = {"alex": "alpha", "sam": "alpha", "lee": "alpha", "riley": "beta", "jordan": "beta"}


def test_generate_is_deterministic_and_well_formed():
    a, b = generate(), generate()
    assert a == b
    assert set(a["tenants"]) == {"alpha", "beta"}
    for tid in a["tenants"].values():
        assert uuid.UUID(tid).version == 5
    assert set(a["personas"]) == set(PERSONAS)
    for name, p in a["personas"].items():
        assert uuid.UUID(p["user_id"]).version == 5
        assert p["tenant"] == PERSONAS[name]
        assert p["roles"] in (["requester"], ["reviewer"], ["reader"])


def test_write_is_lf_without_bom(tmp_path: Path):
    out = tmp_path / "seed-ids.json"
    write_seed_ids(out)
    raw = out.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf") and b"\r" not in raw
    assert json.loads(raw.decode("utf-8")) == generate()


def test_committed_file_matches_generator():
    committed = json.loads(Path("data/seed-ids.json").read_text(encoding="utf-8"))
    assert committed == generate()  # drift guard: regenerate after any generator change


def test_golden_ids_catch_a_regenerated_namespace_or_name_change():
    """External systems (Keycloak realm T05, fixtures T45) consume these IDs; a regenerated change must fail here."""
    ids = generate()
    assert ids["tenants"]["alpha"] == "3ea79c95-914c-52cb-9d10-c4e19dda8ff7"
    assert ids["personas"]["alex"]["user_id"] == "2fc05986-c7ec-544c-b628-fdb112bbf18a"

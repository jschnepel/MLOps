"""Fixture metadata (AM-80 fixtures row): tenant UUIDs, alert UUIDs/revisions and per-section hashes are generated
deterministically from the seed namespace and the markdown, and the committed file never drifts from the generator.

Catches: a hand-edited meta.json, an alert UUID that is not the uuid5 of its id, a section hash that no longer matches
the markdown, and a tenant map that disagrees with data/seed-ids.json.
"""

import hashlib
import json
import uuid
from pathlib import Path

from scripts import gen_fixture_meta as g
from scripts.gen_seed_ids import NS

ROOT = g.FIXTURES
SEEDS = json.loads(g.SEED_IDS.read_text(encoding="utf-8"))


def test_generator_is_deterministic_and_committed_file_matches():
    assert g.generate(ROOT) == g.generate(ROOT)
    assert json.loads((ROOT / "meta.json").read_text(encoding="utf-8")) == g.generate(ROOT)
    raw = (ROOT / "meta.json").read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf") and b"\r" not in raw and raw.endswith(b"}\n")


def test_tenants_match_seed_ids():
    meta = g.generate(ROOT)
    assert meta["tenants"] == SEEDS["tenants"]


def test_alert_uuids_are_uuid5_of_their_ids_with_revision_one():
    meta = g.generate(ROOT)
    ids = {a["id"] for a in json.loads((ROOT / "observations.json").read_text(encoding="utf-8"))["alerts"]}
    assert {a["id"] for a in meta["alerts"]} == ids == {"A17-alert-001", "A17-alert-002", "A17-old-001"}
    for a in meta["alerts"]:
        assert a["alert_id"] == str(uuid.uuid5(NS, f"alert/{a['id']}")) and a["revision"] == 1


def test_section_hashes_follow_the_documented_rule(tmp_path: Path):
    p = tmp_path / "scratch.md"
    p.write_text("# Title\n\n## review\n\nline one\nline two\n\n## evidence\nx\n", encoding="utf-8", newline="\n")
    hashes = dict(g.section_hashes(p))
    assert hashes == {
        "review": hashlib.sha256(b"line one\nline two").hexdigest(),
        "evidence": hashlib.sha256(b"x").hexdigest(),
    }


def test_every_catalog_section_has_a_hash():
    catalog = json.loads((ROOT / "catalog.json").read_text(encoding="utf-8"))
    meta = g.generate(ROOT)
    have = {(s["document_id"], s["version"], s["section"]) for s in meta["sections"]}
    want = {(d["document_id"], d["version"], sec) for d in catalog["documents"] for sec in d["sections"]}
    assert want <= have

"""The governed corpus as committed (R099; AM-50 SA:640-645; Plan L rulings 4, 7, 11-15 and 17).

Catches: a corpus too small to measure retrieval (fewer than 14 authored documents, counted as catalog entries, that
is files or versions, not document IDs, 7 per tenant, 6 assets or 3 per tenant), a document outside 300-900 words
counted after its title and synthetic-fixture banner (`corpus.prose_words`) or without that banner, a tenant
missing its superseded pair, expired, revoked, draft or injected version, a corpus without its conflicting pair, a
document ID shared with the delivered fixtures, a section whose offsets do not cut out exactly the body its hash
covers, a hand-edited or stale meta.json, an alert UUID that is not uuid5 of its id, a document changed without a
new lock, a new lock under the old version, a retired version the oracle would still allow, and a catalog the
loader accepts although it breaks one of its rules (each refusal is one case below).
"""

import hashlib
import json
import shutil
import uuid
from collections import Counter
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from ops_core import corpus

from scripts import gen_corpus_meta
from scripts.gen_seed_ids import NS

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "data" / "corpus"
FIXTURES = ROOT / "data" / "handoff-fixtures"
# A fixed instant after every effective_from of corpus-1, inside no effective interval that ends: the lifecycle cases
# below are labelled against it, so they do not drift with the wall clock.
AS_OF = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)


def loaded() -> corpus.Corpus:
    return corpus.load(CORPUS)


def test_the_corpus_is_large_enough_to_measure_retrieval() -> None:
    governed = loaded()
    per_tenant = Counter(d.tenant for d in governed.documents)  # catalog entries: authored files (versions)
    assert len(governed.documents) >= 14 and min(per_tenant.values()) >= 7 and set(per_tenant) == {"alpha", "beta"}
    assets = json.loads((CORPUS / "assets.json").read_text(encoding="utf-8"))["assets"]
    assert len(assets) >= 6 and min(Counter(a["tenant"] for a in assets).values()) >= 3
    for doc in governed.documents:  # the title and the banner do not count (round 1, I3); authored with a margin
        words = corpus.prose_words((CORPUS / doc.path).read_text(encoding="utf-8"))
        assert 320 <= words <= 900, (doc.path, words)
    assert corpus.prose_words("# A title\n\nThe banner line.\nOne two three.\n") == 3


def test_each_tenant_has_every_lifecycle_case_and_the_corpus_a_conflicting_pair() -> None:
    governed = loaded()
    allowed = corpus.returnable(governed, AS_OF)
    for tenant in ("alpha", "beta"):
        docs = [d for d in governed.documents if d.tenant == tenant]
        successors = [d for d in docs if d.supersedes is not None and d.identity in allowed]
        assert successors and all((tenant, d.document_id, d.supersedes) not in allowed for d in successors)
        assert any(d.status == "approved" and d.effective_to is not None and d.effective_to <= AS_OF for d in docs)
        assert any(d.status == "revoked" for d in docs) and any(d.status == "draft" for d in docs)
        assert any(d.label == "injected" and d.identity in allowed for d in docs)
    conflicting = [d for d in governed.documents if d.label == "conflicting"]
    assert len(conflicting) == 2 and all(d.identity in allowed for d in conflicting)
    assert {d.document_id for d in conflicting} == {d.conflicts_with for d in conflicting}


def test_the_returnable_set_at_the_labelling_instant() -> None:
    """Ruling 7 on corpus-1: the derived supersession (alpha), the explicit one (beta), the expired, revoked and draft
    versions, and both halves of the conflicting pair."""
    assert corpus.returnable(loaded(), AS_OF) == {
        ("alpha", "ALPHA-ALERT-REVIEW", "1"),
        ("alpha", "ALPHA-COMPRESSOR-COOLDOWN", "1"),
        ("alpha", "ALPHA-COMPRESSOR-TRIP", "1"),
        ("alpha", "ALPHA-PUMP-SEAL", "2"),
        ("alpha", "ALPHA-VENDOR-PORTAL", "1"),
        ("beta", "BETA-COMPRESSOR-OIL", "1"),
        ("beta", "BETA-CONTRACTOR-MEMO", "1"),
        ("beta", "BETA-PUMP-ALIGN", "2"),
    }


def test_a_retired_version_never_comes_back_in_the_oracle() -> None:
    """Ruling 7 as round 1 amended it, on the shapes the round-1 review found (the loader refuses the first two in a
    catalog; the oracle must still be right about them): a later version that left draft and reached its
    effective_from retires every earlier one for good; a draft or not-yet-effective one retires nothing; versions
    compare as numbers."""
    template = next(d for d in loaded().documents if d.document_id == "ALPHA-ALERT-REVIEW")
    day = timedelta(days=1)

    def v(name: str, version: str, status: str = "approved", start: int = -30, end: int | None = None) -> Any:
        stop = None if end is None else AS_OF + end * day
        changes = {"status": status, "effective_from": AS_OF + start * day, "effective_to": stop}
        return replace(template, document_id=name, version=version, supersedes=None, **changes)

    documents = (
        *(v("NO-LINK", "1"), v("NO-LINK", "2", start=-1)),  # (a) a successor without supersedes
        *(v("WRONG-LINK", "1"), v("WRONG-LINK", "2", start=-2), v("WRONG-LINK", "3", start=-1)),  # (b)
        *(v("GAP", "1"), v("GAP", "2", "revoked", start=-2), v("GAP", "3", start=-1)),  # (c) the middle revoked
        *(v("REVOKED-NEXT", "1"), v("REVOKED-NEXT", "2", "revoked", start=-1)),  # (d) no resurrection
        *(v("EXPIRED-NEXT", "1"), v("EXPIRED-NEXT", "2", start=-10, end=-1)),  # retired for good
        *(v("DRAFT-NEXT", "1"), v("DRAFT-NEXT", "2", "draft", start=-1)),  # a draft retires nothing
        *(v("LATER-NEXT", "1"), v("LATER-NEXT", "2", start=1)),  # nor a successor not yet effective
        *(v("NUMBERS", "9"), v("NUMBERS", "10", start=-1)),  # "10" follows "9"
    )
    allowed = {(name, version) for _, name, version in corpus.returnable(replace(loaded(), documents=documents), AS_OF)}
    assert allowed == {
        ("NO-LINK", "2"),
        ("WRONG-LINK", "3"),
        ("GAP", "3"),
        ("DRAFT-NEXT", "1"),
        ("LATER-NEXT", "1"),
        ("NUMBERS", "10"),
    }


def test_document_ids_are_disjoint_from_the_delivered_fixtures() -> None:
    delivered = json.loads((FIXTURES / "catalog.json").read_text(encoding="utf-8"))["documents"]
    assert not {d.document_id for d in loaded().documents} & {d["document_id"] for d in delivered}


def test_each_section_is_cut_exactly_and_hashed_by_the_fixture_rule() -> None:
    for doc in loaded().documents:
        text = (CORPUS / doc.path).read_text(encoding="utf-8")
        for section in doc.sections:
            assert text[section.start : section.end] == section.body, doc.evidence_id(section)
            assert section.sha256 == hashlib.sha256(section.body.encode("utf-8")).hexdigest()
            assert section.words == len(corpus.WORD.findall(section.body.lower())) > 0
    sample = "# T\n\nSynthetic\n\n## review\n\nline one\nline two\n\n## evidence\nx\n"
    review, evidence = corpus.sections(sample)
    assert (review.name, review.body, evidence.body) == ("review", "line one\nline two", "x")
    assert sample[review.start : review.end] == review.body and review.words == 4


def test_meta_json_is_generated_and_its_alerts_are_uuid5() -> None:
    meta = json.loads((CORPUS / "meta.json").read_text(encoding="utf-8"))
    assert meta == gen_corpus_meta.generate(CORPUS)
    raw = (CORPUS / "meta.json").read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf") and b"\r" not in raw and raw.endswith(b"}\n")
    seeds = json.loads((ROOT / "data" / "seed-ids.json").read_text(encoding="utf-8"))["tenants"]
    assert meta["tenants"] == seeds and meta["lock_sha256"] == loaded().lock_sha256
    for alert in meta["alerts"]:
        assert alert["alert_id"] == str(uuid.uuid5(NS, f"alert/{alert['id']}")) and alert["revision"] >= 1
    assert len(meta["sections"]) == sum(len(d.sections) for d in loaded().documents)


def test_the_lock_is_the_released_one() -> None:
    governed = loaded()
    assert governed.corpus_version == "corpus-1"
    assert corpus.RELEASES["corpus-1"] == governed.lock_sha256
    assert hashlib.sha256((CORPUS / corpus.LOCK).read_bytes()).hexdigest() == governed.lock_sha256


def copy_corpus(tmp_path: Path) -> Path:
    root = tmp_path / "corpus"
    shutil.copytree(CORPUS, root)
    return root


def test_a_changed_document_without_a_new_lock_is_refused(tmp_path: Path) -> None:
    root = copy_corpus(tmp_path)
    path = root / "alpha-alert-review.md"
    path.write_text(path.read_text(encoding="utf-8") + "One more line.\n", encoding="utf-8", newline="\n")
    with pytest.raises(corpus.CorpusError, match="changed without a new lock"):
        corpus.load(root)


def test_a_new_lock_under_the_released_version_is_refused(tmp_path: Path) -> None:
    root = copy_corpus(tmp_path)
    path = root / "alpha-alert-review.md"
    path.write_text(path.read_text(encoding="utf-8") + "One more line.\n", encoding="utf-8", newline="\n")
    gen_corpus_meta.write_lock(root)
    with pytest.raises(corpus.CorpusError, match="not the released lock of corpus-1"):
        corpus.load(root)
    assert corpus.load(root, released=None).corpus_version == "corpus-1"  # the files and the lock agree


def edit_catalog(root: Path, key: str, **changes: Any) -> None:
    """Change one catalog entry (`ID` for its first version, `ID vN` for version N) and re-lock, so only the rule
    under test can refuse."""
    path = root / corpus.CATALOG
    catalog = json.loads(path.read_text(encoding="utf-8"))
    document_id, _, version = key.partition(" v")
    entry = next(d for d in catalog["documents"] if d["document_id"] == document_id and version in ("", d["version"]))
    entry.update(changes)
    path.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8", newline="\n")
    gen_corpus_meta.write_lock(root)


@pytest.mark.parametrize(
    ("key", "changes", "reason"),
    [
        ("ALPHA-ALERT-REVIEW", {"status": "retired"}, "status must be one of"),
        ("ALPHA-ALERT-REVIEW", {"effective_to": "2026-08-01T00:00:00Z"}, "effective_to must be later"),
        ("ALPHA-ALERT-REVIEW", {"effective_from": "2026-09-01"}, "effective_from must be a UTC instant"),
        ("ALPHA-ALERT-REVIEW", {"asset_family": "turbine"}, "asset_family must be null or one of"),
        ("ALPHA-ALERT-REVIEW", {"tenant": "gamma"}, "tenant must be one that assets.json names"),
        ("ALPHA-ALERT-REVIEW", {"label": "conflicting"}, "conflicts_with is set exactly when"),
        ("ALPHA-ALERT-REVIEW", {"supersedes": "3"}, "supersedes must name an earlier version"),
        ("ALPHA-ALERT-REVIEW", {"sections": ["purpose", "interval"]}, "headings differ from the catalog"),
        ("ALPHA-ALERT-REVIEW", {"path": "../alpha-alert-review.md"}, "plain lower-case .md name"),
        ("ALPHA-COMPRESSOR-TRIP", {"conflicts_with": "ALPHA-ALERT-REVIEW"}, "must name each other"),
        ("BETA-PUMP-ALIGN", {"version": "2"}, "listed twice"),
        # Round 1, I2: one linear chain per document, compared as numbers.
        ("BETA-PUMP-ALIGN v2", {"supersedes": None}, "versions must form one chain"),
        ("ALPHA-PUMP-SEAL v2", {"version": "3"}, "versions must form one chain"),
        ("ALPHA-ALERT-REVIEW", {"version": "1a"}, "version must be a positive whole number"),
    ],
)
def test_the_loader_refuses_a_broken_catalog(tmp_path: Path, key: str, changes: dict[str, Any], reason: str) -> None:
    root = copy_corpus(tmp_path)
    edit_catalog(root, key, **changes)
    with pytest.raises(corpus.CorpusError, match=reason):
        corpus.load(root, released=None)


def test_the_loader_refuses_a_stray_or_unlabelled_document(tmp_path: Path) -> None:
    root = copy_corpus(tmp_path)
    (root / "alpha-stray.md").write_text("# Stray\n", encoding="utf-8", newline="\n")
    path = root / "beta-hot-work.md"
    unlabelled = path.read_text(encoding="utf-8").replace(corpus.SYNTHETIC_LINE, "Real procedure.")
    path.write_text(unlabelled, encoding="utf-8", newline="\n")
    # Round 1, M1: a section whose body has no [a-z0-9] word is refused before anything is written.
    path = root / "alpha-alarm-bypass.md"
    text = path.read_text(encoding="utf-8")
    body = next(s.body for s in corpus.sections(text) if s.name == "expiry")
    path.write_text(text.replace(body, "* * * - - -"), encoding="utf-8", newline="\n")
    gen_corpus_meta.write_lock(root)
    with pytest.raises(corpus.CorpusError) as refused:
        corpus.load(root, released=None)
    assert "documents without a catalog entry: alpha-stray.md" in str(refused.value)
    assert "must open with a title, a blank line and the synthetic-fixture line" in str(refused.value)
    assert "section 'expiry' needs a short lower-case name and words" in str(refused.value)

"""The governed corpus as files: parse, validate and lock `data/corpus/` (T17; BUILD_SPEC §11, AM-50; Plan L rulings
4-7, 11-15 and 17).

The directory holds `catalog.json` (every document version with its tenant, lifecycle, asset family, label and
sections), `assets.json` (the assets and alerts T16's asset-sim will serve), the Markdown documents, the generated
`meta.json` and the lock `corpus.sha256`. `load` refuses the whole directory when anything is wrong, collecting every
problem first, so that ingestion validates the whole catalog before it writes anything (ruling 6). A section is one
`## ` heading's body as `scripts/gen_fixture_meta.py` defines it (the lines up to the next heading, joined with line
feeds, blank edges stripped); its offsets `[start, end)` index the file's text, so `text[start:end]` is exactly the
body the hash covers (ruling 4). The versions of one document form one chain: consecutive whole numbers from the
lowest, each later one naming the one before it in `supersedes` (round 1, I2).

The lock lists the SHA-256 of every locked file under a header naming the corpus version; `RELEASES` freezes the
digest of each released version's lock. Changing a document without a new lock fails `check_lock`, and a new lock
without a new version fails the release check (ruling 17). `corpus-1` is the version T41 labels the holdout against
(ruling 23): any change to a locked file after T41 needs a new version and re-labelling.

Standard library only and self-contained: `scripts/gen_corpus_meta.py` and `scripts/verify_handoff.py` load this file
by path, so their default checks keep needing nothing but Python.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

SYNTHETIC_LINE: Final = "Synthetic development fixture. Not an equipment-control instruction."
HEADING: Final = re.compile(r"^## (?P<name>\S.*?)\s*$")  # the fixtures' rule (scripts/gen_fixture_meta.py)
SECTION_NAME: Final = re.compile(r"[a-z][a-z0-9-]{0,39}")
DOCUMENT_ID: Final = re.compile(r"[A-Z][A-Z0-9-]{1,63}")
VERSION: Final = re.compile(r"[1-9][0-9]{0,8}")
PATH: Final = re.compile(r"[a-z0-9][a-z0-9-]{0,94}\.md")
CORPUS_VERSION: Final = re.compile(r"[a-z0-9][a-z0-9.-]{0,99}")
WORD: Final = re.compile(r"[a-z0-9]+")  # the chunk-size measure (ruling 4): lower-cased runs of letters and digits
STATUSES: Final = ("draft", "approved", "superseded", "revoked")
LABELS: Final = ("normal", "injected", "conflicting")
MAX_BYTES: Final = 65536  # BS:411's file-size limit for an authored source
EVIDENCE_CHARS: Final = 160  # schemas/tool-result.schema.json: evidence_id maxLength
CATALOG: Final = "catalog.json"
ASSETS: Final = "assets.json"
LOCK: Final = "corpus.sha256"
META: Final = "meta.json"  # derived by scripts/gen_corpus_meta.py; deliberately not in the lock
KNOWN_FILES: Final = frozenset({CATALOG, ASSETS, META, LOCK})
DOCUMENT_KEYS: Final = frozenset(
    {
        "document_id",
        "tenant",
        "version",
        "status",
        "effective_from",
        "effective_to",
        "supersedes",
        "asset_family",
        "label",
        "conflicts_with",
        "path",
        "sections",
    }
)
# Released corpus versions and the SHA-256 of their lock file, frozen (Plan L rulings 17 and 23).
RELEASES: Final[Mapping[str, str]] = {
    "corpus-1": "81f50c2b8623675f9c899033cba748f289b7f4024003385aabc8a95147b71862",
}


class CorpusError(ValueError):
    """The corpus directory is not acceptable; the message lists every problem, one per line, and never quotes a
    document's text."""

    def __init__(self, problems: Iterable[str]) -> None:
        self.problems = tuple(problems)
        super().__init__("\n".join(self.problems))


@dataclass(frozen=True)
class Section:
    """One `## ` section: its heading, the body's character offsets in the file, the body, its hash and word count."""

    name: str
    start: int
    end: int
    body: str
    sha256: str
    words: int


@dataclass(frozen=True)
class Document:
    """One catalog entry with its parsed file: the identity is (tenant, document_id, version)."""

    document_id: str
    tenant: str
    version: str
    status: str
    effective_from: datetime
    effective_to: datetime | None
    supersedes: str | None
    asset_family: str | None
    label: str
    conflicts_with: str | None
    path: str
    content_sha256: str
    sections: tuple[Section, ...]

    @property
    def identity(self) -> tuple[str, str, str]:
        """(tenant, document_id, version): the idempotency key of ingestion (BS:411)."""
        return (self.tenant, self.document_id, self.version)

    def evidence_id(self, section: Section) -> str:
        """`<DOCUMENT_ID>:v<version>:<section>`, the citation every proposal carries (Plan D ruling, unchanged)."""
        return f"{self.document_id}:v{self.version}:{section.name}"


@dataclass(frozen=True)
class Corpus:
    """A validated corpus directory: its version, its lock's digest, the documents and the asset types."""

    corpus_version: str
    lock_sha256: str
    documents: tuple[Document, ...]
    asset_types: frozenset[str]
    tenants: frozenset[str]


def prose_words(text: str) -> int:
    """A document's length as R099 counts it (round 1, I3): `[a-z0-9]+` words after the title line, the blank line
    and the synthetic-fixture banner, so neither the title nor the boilerplate counts towards 300-900."""
    return len(WORD.findall("\n".join(text.split("\n")[3:]).lower()))


def sections(text: str) -> list[Section]:
    """Every `## ` section of an LF document in file order, with the offsets of its body in `text`."""
    out: list[Section] = []
    lines = text.split("\n")
    offsets: list[int] = []
    position = 0
    for line in lines:
        offsets.append(position)
        position += len(line) + 1
    headings = [(i, m.group("name")) for i, line in enumerate(lines) if (m := HEADING.match(line))]
    for n, (index, name) in enumerate(headings):
        first = index + 1
        last = headings[n + 1][0] if n + 1 < len(headings) else len(lines)
        joined = "\n".join(lines[first:last])
        body = joined.strip("\n")
        start = (offsets[first] if first < len(lines) else len(text)) + (len(joined) - len(joined.lstrip("\n")))
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        out.append(Section(name, start, start + len(body), body, digest, len(WORD.findall(body.lower()))))
    return out


def _instant(value: Any, field: str, where: str, problems: list[str]) -> datetime | None:
    """A `YYYY-MM-DDTHH:MM:SSZ` instant, or None after recording why it is not one."""
    if not isinstance(value, str):
        problems.append(f"{where}: {field} must be a UTC instant")
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        problems.append(f"{where}: {field} must be a UTC instant")
        return None


def _read_document(root: Path, path: str, where: str, problems: list[str]) -> tuple[str, str] | None:
    """The file's text and SHA-256, or None after recording why the file is not acceptable."""
    if not PATH.fullmatch(path):
        problems.append(f"{where}: path must be a plain lower-case .md name inside the corpus directory")
        return None
    file = root / path
    if not file.is_file() or file.is_symlink():
        problems.append(f"{where}: {path} is missing")
        return None
    raw = file.read_bytes()
    if len(raw) > MAX_BYTES:
        problems.append(f"{where}: {path} is larger than {MAX_BYTES} bytes")
        return None
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw:
        problems.append(f"{where}: {path} must be LF-only UTF-8 without a byte-order mark")
        return None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        problems.append(f"{where}: {path} is not UTF-8")
        return None
    lines = text.split("\n")
    if len(lines) < 3 or not lines[0].startswith("# ") or lines[1] != "" or lines[2] != SYNTHETIC_LINE:
        problems.append(f"{where}: {path} must open with a title, a blank line and the synthetic-fixture line")
        return None
    return text, hashlib.sha256(raw).hexdigest()


def _read_json(root: Path, name: str, problems: list[str]) -> Any:
    """The JSON value of `root/name`, or None after recording that the file cannot be read as JSON. Only the error's
    type is quoted: a message could carry a piece of the file."""
    try:
        return json.loads((root / name).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:  # a missing file, bad UTF-8 and malformed JSON are all one refusal
        problems.append(f"{name}: cannot be read as JSON ({type(exc).__name__})")
        return None


def load_assets(root: Path) -> dict[str, Any]:
    """`assets.json`, checked: asset types, assets (unique ids, known types, a tenant each) and alerts (unique ids,
    known assets, a revision of at least 1).

    Raises:
        CorpusError: listing every problem, including an unreadable file or an entry that is not an object.
    """
    problems: list[str] = []
    data = _read_json(root, ASSETS, problems)
    if problems:
        raise CorpusError(problems)
    if not isinstance(data, dict):
        raise CorpusError(["assets.json: must be a JSON object"])
    types = data.get("asset_types")
    if (
        not isinstance(types, list)
        or not types
        or not all(isinstance(t, str) and SECTION_NAME.fullmatch(t) for t in types)
    ):
        problems.append("assets.json: asset_types must be a non-empty list of lower-case names")
        types = []
    assets = data.get("assets", [])
    if not isinstance(assets, list):
        problems.append("assets.json: assets must be a list")
        assets = []
    ids: list[str] = []
    for asset in assets:
        if not isinstance(asset, dict):
            problems.append("assets.json: every asset must be an object")
            continue
        asset_id = asset.get("asset_id")
        if isinstance(asset_id, str):
            ids.append(asset_id)
        if set(asset) != {"asset_id", "tenant", "asset_type", "name"}:
            problems.append(f"assets.json: {asset_id} must have asset_id, tenant, asset_type and name")
        elif (
            not isinstance(asset_id, str)
            or not re.fullmatch(r"[A-Z][A-Z0-9_-]{0,31}", asset_id)
            or asset["asset_type"] not in types
        ):
            problems.append(f"assets.json: {asset_id} has a malformed id or an unknown asset type")
        elif not isinstance(asset["tenant"], str) or not SECTION_NAME.fullmatch(asset["tenant"]):
            problems.append(f"assets.json: {asset_id} needs a short lower-case tenant name")
    if len(set(ids)) != len(ids):
        problems.append("assets.json: asset ids must be unique")
    alerts = data.get("alerts", [])
    if not isinstance(alerts, list):
        problems.append("assets.json: alerts must be a list")
        alerts = []
    alert_ids: list[str] = []
    for alert in alerts:
        if not isinstance(alert, dict):
            problems.append("assets.json: every alert must be an object")
            continue
        if isinstance(alert.get("id"), str):
            alert_ids.append(alert["id"])
        else:
            problems.append("assets.json: every alert needs a string id")
        known = alert.get("asset_id") in ids
        revision = alert.get("revision")
        if not known or not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
            problems.append(f"assets.json: alert {alert.get('id')} needs a known asset and a revision of at least 1")
    if len(set(alert_ids)) != len(alert_ids):
        problems.append("assets.json: alert ids must be unique")
    if problems:
        raise CorpusError(problems)
    return dict(data)


def lock_text(root: Path, corpus_version: str, paths: Iterable[str]) -> str:
    """The lock as it must read: a header naming the version, then `<sha256>  <name>` for the catalog, the assets file
    and every document, sorted by name, LF line ends."""
    names = sorted({CATALOG, ASSETS, *paths})
    lines = [f"# corpus_version {corpus_version}"]
    lines += [f"{hashlib.sha256((root / name).read_bytes()).hexdigest()}  {name}" for name in names]
    return "\n".join(lines) + "\n"


def check_lock(
    root: Path, corpus_version: str, paths: Iterable[str], released: Mapping[str, str] | None = RELEASES
) -> list[str]:
    """Problems with the committed lock: content changed without a new lock, or (with `released`) a lock that is not
    the frozen one of its version. An empty list means the lock holds."""
    lock = root / LOCK
    if not lock.is_file():
        return [f"{LOCK} is missing: run uv run python -m scripts.gen_corpus_meta --lock"]
    committed = lock.read_bytes()
    problems: list[str] = []
    if committed != lock_text(root, corpus_version, paths).encode("utf-8"):
        problems.append(f"{LOCK} does not match the files: a locked file changed without a new lock")
    if released is not None:
        digest = hashlib.sha256(committed).hexdigest()
        if released.get(corpus_version) != digest:
            problems.append(
                f"{LOCK} is not the released lock of {corpus_version}: a changed corpus needs a new version"
            )
    return problems


def load(root: Path, *, released: Mapping[str, str] | None = RELEASES) -> Corpus:
    """Parse and validate the whole corpus directory; refuse it with every problem at once.

    Args:
        root: the corpus directory (`data/corpus` in the repository).
        released: the frozen lock digests per version; None skips that check (tests that build a corpus of their own).

    Raises:
        CorpusError: listing every problem found.
    """
    problems: list[str] = []
    try:
        assets = load_assets(root)
    except CorpusError as exc:
        problems.extend(exc.problems)
        assets = {"asset_types": [], "assets": []}
    asset_types = frozenset(assets["asset_types"])
    tenants = frozenset(a["tenant"] for a in assets["assets"])
    catalog = _read_json(root, CATALOG, problems)
    if catalog is not None and not isinstance(catalog, dict):
        problems.append("catalog.json: must be a JSON object")
        catalog = None
    if catalog is None or not (root / ASSETS).is_file():
        # Nothing further can be checked, and the lock cannot be recomputed without both files.
        raise CorpusError(problems)
    if (
        set(catalog) != {"corpus_version", "classification", "documents"}
        or catalog.get("classification") != "synthetic"
    ):
        problems.append("catalog.json: needs exactly corpus_version, classification (synthetic) and documents")
    corpus_version = catalog.get("corpus_version")
    if not isinstance(corpus_version, str) or not CORPUS_VERSION.fullmatch(corpus_version):
        problems.append("catalog.json: corpus_version must be a short lower-case name such as corpus-1")
        corpus_version = "invalid"
    documents: list[Document] = []
    entries = catalog.get("documents", [])
    if not isinstance(entries, list):
        problems.append("catalog.json: documents must be a list")
        entries = []
    for entry in entries:
        if not isinstance(entry, dict):
            problems.append("catalog.json: every document entry must be an object")
            continue
        where = f"catalog.json: {entry.get('document_id')} v{entry.get('version')}"
        if set(entry) != DOCUMENT_KEYS:
            problems.append(f"{where}: keys must be exactly {sorted(DOCUMENT_KEYS)}")
            continue
        before = len(problems)
        if not isinstance(entry["document_id"], str) or not DOCUMENT_ID.fullmatch(entry["document_id"]):
            problems.append(f"{where}: document_id must be upper-case letters, digits and hyphens")
        if not isinstance(entry["tenant"], str) or entry["tenant"] not in tenants:
            problems.append(f"{where}: tenant must be one that assets.json names")
        # The version is validated before anything compares it: int() on a malformed or null one must not escape as
        # a ValueError or TypeError (fix round 1), so `supersedes` is compared only against a valid version.
        version_ok = isinstance(entry["version"], str) and VERSION.fullmatch(entry["version"]) is not None
        if not version_ok:
            problems.append(f"{where}: version must be a positive whole number written as a string")
        if entry["status"] not in STATUSES:
            problems.append(f"{where}: status must be one of {', '.join(STATUSES)}")
        start = _instant(entry["effective_from"], "effective_from", where, problems)
        end = (
            None if entry["effective_to"] is None else _instant(entry["effective_to"], "effective_to", where, problems)
        )
        if start is not None and end is not None and end <= start:
            problems.append(f"{where}: effective_to must be later than effective_from")
        family = entry["asset_family"]
        if family is not None and (not isinstance(family, str) or family not in asset_types):
            problems.append(f"{where}: asset_family must be null or one of assets.json's asset_types")
        if entry["label"] not in LABELS:
            problems.append(f"{where}: label must be one of {', '.join(LABELS)}")
        if (entry["label"] == "conflicting") != (entry["conflicts_with"] is not None):
            problems.append(f"{where}: conflicts_with is set exactly when the label is conflicting")
        elif entry["conflicts_with"] is not None and not isinstance(entry["conflicts_with"], str):
            problems.append(f"{where}: conflicts_with must be null or a document id")
        supersedes = entry["supersedes"]
        if supersedes is not None:
            names_a_version = isinstance(supersedes, str) and VERSION.fullmatch(supersedes) is not None
            if not names_a_version or (version_ok and int(supersedes) >= int(entry["version"])):
                problems.append(f"{where}: supersedes must name an earlier version")
        names = entry["sections"]
        if (
            not isinstance(names, list)
            or not names
            or not all(isinstance(n, str) for n in names)
            or len(set(names)) != len(names)
        ):
            problems.append(f"{where}: sections must list each heading once")
            names = []
        read = _read_document(root, str(entry["path"]), where, problems)
        if read is None or len(problems) > before:
            continue
        text, digest = read
        parsed = tuple(sections(text))
        if [s.name for s in parsed] != names:
            problems.append(f"{where}: the file's headings differ from the catalog's sections")
            continue
        for section in parsed:
            evidence = f"{entry['document_id']}:v{entry['version']}:{section.name}"
            # A body without one [a-z0-9] word would fail the chunks table's word_count CHECK only at write time,
            # after an earlier tenant committed (round 1, M1); it is refused here, before anything is written.
            if not SECTION_NAME.fullmatch(section.name) or len(evidence) > EVIDENCE_CHARS or section.words == 0:
                problems.append(f"{where}: section {section.name!r} needs a short lower-case name and words")
        documents.append(
            Document(
                document_id=entry["document_id"],
                tenant=entry["tenant"],
                version=entry["version"],
                status=entry["status"],
                effective_from=start if start is not None else datetime.min.replace(tzinfo=UTC),
                effective_to=end,
                supersedes=supersedes,
                asset_family=family,
                label=entry["label"],
                conflicts_with=entry["conflicts_with"],
                path=entry["path"],
                content_sha256=digest,
                sections=parsed,
            )
        )
    identities = [d.identity for d in documents]
    if len(set(identities)) != len(identities):
        problems.append("catalog.json: a document version is listed twice")
    paths = [d.path for d in documents]
    if len(set(paths)) != len(paths):
        problems.append("catalog.json: two versions share a file")
    known = set(identities)
    chains: dict[tuple[str, str], list[Document]] = {}
    for doc in documents:
        chains.setdefault((doc.tenant, doc.document_id), []).append(doc)
    for (tenant, document_id), versions in sorted(chains.items()):
        # One linear chain, compared as numbers ("10" follows "9"): consecutive from the lowest, each later version
        # naming the one before it, so no two versions can be current at once and no version is skipped.
        ordered = sorted(versions, key=lambda d: int(d.version))
        numbers = [int(d.version) for d in ordered]
        links = [d.supersedes for d in ordered]
        if numbers != list(range(numbers[0], numbers[0] + len(numbers))) or links != [
            None,
            *(str(n) for n in numbers[:-1]),
        ]:
            problems.append(
                f"catalog.json: {tenant} {document_id}: versions must form one chain, each superseding the one before"
            )
    for doc in documents:
        if doc.supersedes is not None and (doc.tenant, doc.document_id, doc.supersedes) not in known:
            problems.append(f"catalog.json: {doc.document_id} v{doc.version} supersedes a version the catalog lacks")
        if doc.conflicts_with is not None:
            partners = [d for d in documents if d.tenant == doc.tenant and d.document_id == doc.conflicts_with]
            if not partners or any(p.conflicts_with != doc.document_id for p in partners):
                problems.append(f"catalog.json: {doc.document_id} and its conflicts_with must name each other")
    # Every file in the directory is either a catalog entry's document or one of the known files (fix round 1): a
    # stray document or any other leftover would otherwise sit beside a locked corpus unnoticed.
    listed = {e["path"] for e in entries if isinstance(e, dict) and isinstance(e.get("path"), str)}
    present = sorted(p.name for p in root.iterdir())
    stray = [n for n in present if n.endswith(".md") and n not in listed]
    if stray:
        problems.append(f"catalog.json: documents without a catalog entry: {', '.join(stray)}")
    unknown = [n for n in present if not n.endswith(".md") and n not in KNOWN_FILES]
    if unknown:
        problems.append(f"catalog.json: files that are not part of the corpus: {', '.join(unknown)}")
    problems.extend(check_lock(root, corpus_version, paths, released))
    if problems:
        raise CorpusError(problems)
    lock_sha256 = hashlib.sha256((root / LOCK).read_bytes()).hexdigest()
    return Corpus(corpus_version, lock_sha256, tuple(documents), asset_types, tenants)


def returnable(corpus: Corpus, now: datetime) -> frozenset[tuple[str, str, str]]:
    """The identities a search may return at `now`, by ruling 7 as round 1 amended it: approved, effective, and not
    retired. A version is retired once any later version of the same document (compared as numbers) that has left
    `draft` has reached its own `effective_from`; revoking or expiring that successor never brings it back. The
    database applies the same rule in `search_procedures_scoped` and never reads this; the development queries'
    hand-written labels are the check that is independent of both."""
    effective = {
        d.identity
        for d in corpus.documents
        if d.status == "approved" and d.effective_from <= now and (d.effective_to is None or now < d.effective_to)
    }
    retired = {
        d.identity
        for d in corpus.documents
        for later in corpus.documents
        if (later.tenant, later.document_id) == (d.tenant, d.document_id)
        and int(later.version) > int(d.version)
        and later.status != "draft"
        and later.effective_from <= now
    }
    return frozenset(effective - retired)

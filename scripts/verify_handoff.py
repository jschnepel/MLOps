#!/usr/bin/env python3
"""Validate this handoff package, not the target production application.

Default checks need only Python's standard library. --contracts requires the
jsonschema package. Snapshot/reference hash checks are intended before edits.

--reference-tree (implied by --reference-code) enforces the whole reference/ tree against
provenance/reference-tree.json: every listed file must be byte-identical to its zip member in
the delivered 1.0 package (--zip), no listed file may be missing, no other file may exist under
reference/ except the repository-owned reference/README.md (caches and build output skipped),
and every reference-code-hashes.remap.json target must lie under reference/.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
# Directories the repository-wide walks ignore: environments and build output are not part of the package, and
# reference/ is inherited code verified separately by hash, not parsed or syntax-checked as ours.
SKIP_DIRS = {".venv", "node_modules", "reference", ".git", "__pycache__", ".pytest_cache", "build"}


def rglob_files(pattern: str):
    """Walk the repository, skipping virtual environments, build output and the hash-checked reference."""
    for path in sorted(ROOT.rglob(pattern)):
        parts = path.relative_to(ROOT).parts[:-1]
        # startswith(".venv") also skips variants such as .venv-probe-junk; a stray environment must not fail the
        # JSON and syntax checks (tests/plan_a/test_verify_handoff.py covers this).
        if any(part in SKIP_DIRS or part.startswith(".venv") for part in parts):
            continue
        yield path


def check_manifest(zip_path: Path) -> int:
    """Verify every file listed in provenance/MANIFEST-1.0.sha256 against its member of the delivered 1.0 zip.

    Reads the zip, not the working tree, because the working tree is allowed to change after delivery while the
    zip is the fixed record of what was handed over. Returns 0 on success, 1 after printing each failure.
    """
    manifest = (ROOT / "provenance/MANIFEST-1.0.sha256").read_text(encoding="utf-8").splitlines()
    expected = {}
    for line in manifest:
        if not line.strip():
            continue
        # sha256sum text format: digest, two spaces, name.
        digest, name = line.split("  ", 1)
        check(bool(re.fullmatch(r"[a-f0-9]{64}", digest)), "Malformed checksum")
        expected[name.strip()] = digest
    bad = []
    with zipfile.ZipFile(zip_path) as z:
        for name, digest in expected.items():
            member = "operations-copilot/" + name  # every member of the delivered zip sits under this folder
            try:
                data = z.read(member)
            except KeyError:
                bad.append(f"missing in zip: {name}")
                continue
            if hashlib.sha256(data).hexdigest() != digest:
                bad.append(f"mismatch: {name}")
    for b in bad:
        print("FAIL:", b)
    if bad:
        return 1
    print(f"PASS: {len(expected)} delivered 1.0 snapshot checksums verified against {zip_path.name}")
    return 0


def check_reference_code() -> int:
    """Check that the inherited source, test and integration files still match their original sha256.

    provenance/reference-code-hashes.json records the hashes under the original kit paths; the remap file says
    where T42 moved each file. Returns 0 on success, 1 after listing every changed or missing file.
    """
    original = load("provenance/reference-code-hashes.json")["files"]
    remap = load("provenance/reference-code-hashes.remap.json")
    bad = []
    for entry in original:
        # A path absent from the remap was never moved, so it is looked up where it always was.
        new = remap.get(entry["path"], entry["path"])
        p = within(new)
        actual = hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
        if actual != entry["sha256"]:
            bad.append(f"{entry['path']} -> {new}")
    if bad:
        print("FAIL: reference code changed:", *bad, sep="\n  ")
        return 1
    print(f"PASS: {len(original)} inherited source/test/integration files match original snapshot (remapped)")
    return 0


# Generated directories that appear under reference/ when its tests run or it is installed; they are not
# delivered files, so their presence must not fail the "no extra files" rule.
TREE_SKIP_DIRS = {"__pycache__", "build", ".pytest_cache"}
# The only file under reference/ this repository wrote, so it has no counterpart in the delivered zip.
TREE_REPO_OWNED = {"README.md"}


def reference_tree_files() -> set[str]:
    """Files under reference/, relative to it, skipping caches and build output."""
    base = ROOT / "reference"
    found = set()
    for path in base.rglob("*"):
        if not path.is_file() or path.suffix == ".pyc":
            continue
        rel = path.relative_to(base)
        if any(part in TREE_SKIP_DIRS or part.endswith(".egg-info") for part in rel.parts[:-1]):
            continue
        found.add(rel.as_posix())
    return found


def check_reference_tree(zip_path: Path) -> int:
    """Enforce the whole reference/ tree against provenance/reference-tree.json and the delivered zip (final review F1).

    The per-file hashes only cover files that have a hash entry; this also catches modified unhashed files
    (Dockerfile, Makefile ...), deleted files, files added under reference/, and remap targets that point outside it.
    Returns 0 on success, 1 after printing each failure.
    """
    spec = load("provenance/reference-tree.json")
    prefix, listed = spec["zip_prefix"], spec["files"]
    bad = []
    with zipfile.ZipFile(zip_path) as z:
        for rel in listed:
            path = within("reference/" + rel)
            if not path.is_file():
                bad.append(f"missing: reference/{rel}")
                continue
            try:
                expected = z.read(prefix + rel)
            except KeyError:
                bad.append(f"missing in zip: {prefix}{rel}")
                continue
            if path.read_bytes() != expected:
                bad.append(f"modified: reference/{rel}")
    allowed = set(listed) | TREE_REPO_OWNED
    actual = reference_tree_files()
    bad += [f"unexpected file: reference/{rel}" for rel in sorted(actual - allowed)]
    bad += [f"missing: reference/{rel}" for rel in sorted(TREE_REPO_OWNED - actual)]
    remap = load("provenance/reference-code-hashes.remap.json")
    bad += [f"remap target outside reference/: {k} -> {v}" for k, v in remap.items() if not v.startswith("reference/")]
    for b in bad:
        print("FAIL:", b)
    if bad:
        return 1
    print(
        f"PASS: {len(listed)} delivered reference/ files byte-identical to {zip_path.name}; "
        f"no extra or missing files; {len(remap)} remap targets under reference/"
    )
    return 0


def load(relative: str):
    """Parse a JSON file given as a path relative to the repository root."""
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def check(condition: bool, message: str) -> None:
    """Raise ValueError(message) when `condition` is false; main() turns that into a `FAIL:` line and exit code 1."""
    if not condition:
        raise ValueError(message)


def within(relative: str) -> Path:
    """Resolve a repository-relative path, refusing any that escapes the package (e.g. `../` or a symlink).

    Paths come from JSON files inside the package, so they are treated as untrusted input.
    """
    path = (ROOT / relative).resolve()
    check(path.is_relative_to(ROOT), f"Path escapes package: {relative}")
    return path


def main() -> int:
    """Run the requested checks; return 0 when all pass, 1 when any fails and 2 when a gate could not run."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--contracts", action="store_true", help="Run JSON Schema meta and positive/negative example checks"
    )
    parser.add_argument("--manifest", action="store_true", help="Verify delivered snapshot checksums before editing")
    parser.add_argument(
        "--reference-code",
        action="store_true",
        help="Compare inherited source/test bytes to original archive (also runs --reference-tree)",
    )
    parser.add_argument(
        "--reference-tree",
        action="store_true",
        help="Every file under reference/ byte-identical to the --zip package; no extra/missing files; remap under reference/",
    )
    parser.add_argument(
        "--zip",
        default=str(ROOT / "provenance/handoff-1.0.zip"),
        help="Delivered 1.0 package to verify --manifest against",
    )
    args = parser.parse_args()

    # Files the rest of the handoff points at; a missing one means the package is incomplete or was moved.
    required = [
        "START_HERE.md",
        "BUILD_SPEC.md",
        "AGENTS.md",
        "CLAUDE.md",
        "STATUS.md",
        "SESSION_STATE.md",
        "handoff/KICKOFF_PROMPT.md",
        "handoff/tasks.json",
        "handoff/acceptance-matrix.json",
        "schemas/examples/index.json",
        "provenance/original-implementation-kit.zip",
    ]
    for rel in required:
        check(within(rel).is_file(), f"Missing required file: {rel}")

    # Parse all delivered JSON, but never interpret fixture text as instructions.
    json_paths = sorted(rglob_files("*.json"))
    for path in json_paths:
        json.loads(path.read_text(encoding="utf-8"))

    task_data = load("handoff/tasks.json")
    req_data = load("handoff/acceptance-matrix.json")
    tasks, requirements = task_data["tasks"], req_data["requirements"]
    tids, rids = {t["id"] for t in tasks}, {r["id"] for r in requirements}
    mids = {m["id"] for m in task_data["milestones"]}
    check(len(tids) == len(tasks), "Duplicate task identifiers")
    check(len(rids) == len(requirements), "Duplicate requirement identifiers")
    check(len(mids) == len(task_data["milestones"]), "Duplicate milestone identifiers")
    covered = set()
    for task in tasks:
        check(task["milestone"] in mids, f"Unknown milestone in {task['id']}")
        check(set(task["depends_on"]) <= tids, f"Unknown dependency in {task['id']}")
        check(task["id"] not in task["depends_on"], "Task depends on itself")
        check(set(task["requirement_ids"]) <= rids, f"Unknown requirement in {task['id']}")
        covered.update(task["requirement_ids"])
    check(covered == rids, f"Requirements lack task coverage: {sorted(rids - covered)}")
    # Topological walk: each round resolves every task whose dependencies are already resolved. A round that
    # resolves nothing while tasks remain means the dependency graph has a cycle.
    resolved = set()
    while len(resolved) < len(tasks):
        ready = {t["id"] for t in tasks if set(t["depends_on"]) <= resolved}
        check(bool(ready - resolved), "Task dependency cycle")
        resolved |= ready

    examples = load("schemas/examples/index.json")["examples"]
    for item in examples:
        check(within(item["path"]).is_file(), f"Missing example {item['path']}")
        check(within(item["schema"]).is_file(), f"Missing schema {item['schema']}")
    check(len({e["path"] for e in examples}) == len(examples), "Duplicate example path")

    catalog = load("data/handoff-fixtures/catalog.json")
    for doc in catalog["documents"]:
        p = within("data/handoff-fixtures/" + doc["path"])
        actual = hashlib.sha256(p.read_bytes()).hexdigest()
        check(actual == doc["content_sha256"], f"Fixture hash mismatch: {p.name}")
    scenarios = []
    for line in (ROOT / "evals/handoff-development/scenarios.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            s = json.loads(line)
            check(s["split"] == "development", "Do not fabricate a held-out fixture in development data")
            check(set(s["requirement_ids"]) <= rids, f"Unknown scenario requirement: {s['id']}")
            scenarios.append(s)
    check(len({s["id"] for s in scenarios}) == len(scenarios), "Duplicate scenario identifiers")

    # Syntax inspection only; this deliberately does not execute optional SDKs.
    py_count = 0
    for path in sorted(rglob_files("*.py")):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        py_count += 1
    svg_paths = sorted((ROOT / "docs/diagrams/svg").glob("*.svg"))
    for path in svg_paths:
        ElementTree.parse(path)
    check(len(svg_paths) == 6, "Expected six supplied corrected stage SVGs")
    check(len(list((ROOT / "docs/diagrams/mermaid").glob("*.mmd"))) == 6, "Expected six supplied Mermaid stage sources")

    # Check the example's mathematical hash, not authorization or semantic truth.
    # The serialisation below (sorted keys, no spaces, UTF-8, NaN rejected) must match how payload_sha256 was
    # computed for the shipped examples; changing any option changes the digest.
    proposal = load("schemas/examples/proposal-valid.json")
    raw = json.dumps(
        proposal["payload"], sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()
    check(hashlib.sha256(raw).hexdigest() == proposal["payload_sha256"], "Example proposal hash mismatch")
    for name in ["decision-valid", "outcome-success-valid", "outcome-unknown-valid"]:
        check(
            load(f"schemas/examples/{name}.json")["payload_sha256"] == proposal["payload_sha256"],
            f"Example hash not linked: {name}",
        )

    print(
        f"PASS: package structure; {len(json_paths)} JSON files; {len(tasks)} acyclic tasks; {len(requirements)} covered requirements"
    )
    print(
        f"PASS: {len(catalog['documents'])} source hashes; {len(scenarios)} development scenario cards; {py_count} Python syntax checks; 6 SVG XML files"
    )
    print("PASS: synthetic proposal/decision/outcome example hashes agree")

    if args.contracts:
        try:
            from jsonschema import Draft202012Validator, FormatChecker
        except ImportError:
            # Exit 2, distinct from a failed check (1), so a missing optional dependency is never read as a pass.
            print(
                "BLOCKED: --contracts requires jsonschema in the tooling environment. This gate did not pass.",
                file=sys.stderr,
            )
            return 2
        schema_paths = sorted((ROOT / "schemas").glob("*.schema.json"))
        for path in schema_paths:
            Draft202012Validator.check_schema(json.loads(path.read_text(encoding="utf-8")))
        positive = negative = 0
        for item in examples:
            validator = Draft202012Validator(load(item["schema"]), format_checker=FormatChecker())
            errors = list(validator.iter_errors(load(item["path"])))
            check(
                (len(errors) == 0) is item["valid"],
                f"Unexpected validation for {item['path']}: {[e.message for e in errors]}",
            )
            if item["valid"]:
                positive += 1
            else:
                negative += 1
        print(
            f"PASS: {len(schema_paths)} JSON Schema documents; {positive} accepted examples; {negative} rejected negative examples"
        )

    # Combine with `|=` so every requested check runs and prints its failures; stopping at the first would hide the rest.
    rc = 0
    if args.reference_code:
        rc |= check_reference_code()
    if args.reference_code or args.reference_tree:
        rc |= check_reference_tree(Path(args.zip))
    if args.manifest:
        rc |= check_manifest(Path(args.zip))
    # Printed on every run so a green result is not mistaken for evidence the application itself works.
    print(
        "LIMIT: These are handoff/contract checks, not real model, authorization, MCP network, browser, Docker, Kubernetes or production acceptance tests."
    )
    return rc


if __name__ == "__main__":
    # Bad data in the package (missing file, malformed JSON, failed check()) is an expected outcome and becomes a
    # one-line FAIL. Any other exception is a bug in this script and keeps its traceback.
    try:
        raise SystemExit(main())
    except (ValueError, KeyError, OSError, json.JSONDecodeError, SyntaxError, ElementTree.ParseError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)

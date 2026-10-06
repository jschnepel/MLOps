#!/usr/bin/env python3
"""Validate this handoff package, not the target production application.

Default checks need only Python's standard library. --contracts requires the
jsonschema package. Snapshot/reference hash checks are intended before edits.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]


def load(relative: str):
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def check(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def within(relative: str) -> Path:
    path = (ROOT / relative).resolve()
    check(path.is_relative_to(ROOT), f"Path escapes package: {relative}")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contracts", action="store_true", help="Run JSON Schema meta and positive/negative example checks")
    parser.add_argument("--manifest", action="store_true", help="Verify delivered snapshot checksums before editing")
    parser.add_argument("--reference-code", action="store_true", help="Compare inherited source/test bytes to original archive")
    args = parser.parse_args()

    required = ["START_HERE.md", "BUILD_SPEC.md", "AGENTS.md", "CLAUDE.md", "STATUS.md",
                "SESSION_STATE.md", "handoff/KICKOFF_PROMPT.md", "handoff/tasks.json",
                "handoff/acceptance-matrix.json", "schemas/examples/index.json",
                "provenance/original-implementation-kit.zip"]
    for rel in required:
        check(within(rel).is_file(), f"Missing required file: {rel}")

    # Parse all delivered JSON, but never interpret fixture text as instructions.
    json_paths = sorted(ROOT.rglob("*.json"))
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
    check(covered == rids, f"Requirements lack task coverage: {sorted(rids-covered)}")
    resolved = set()
    while len(resolved) < len(tasks):
        ready = {t["id"] for t in tasks if set(t["depends_on"]) <= resolved}
        check(bool(ready-resolved), "Task dependency cycle")
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
    for line in (ROOT/"evals/handoff-development/scenarios.jsonl").read_text().splitlines():
        if line.strip():
            s = json.loads(line)
            check(s["split"] == "development", "Do not fabricate a held-out fixture in development data")
            check(set(s["requirement_ids"]) <= rids, f"Unknown scenario requirement: {s['id']}")
            scenarios.append(s)
    check(len({s['id'] for s in scenarios}) == len(scenarios), "Duplicate scenario identifiers")

    # Syntax inspection only; this deliberately does not execute optional SDKs.
    py_count = 0
    for path in sorted(ROOT.rglob("*.py")):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        py_count += 1
    svg_paths = sorted((ROOT/"docs/diagrams/svg").glob("*.svg"))
    for path in svg_paths:
        ElementTree.parse(path)
    check(len(svg_paths) == 6, "Expected six supplied corrected stage SVGs")
    check(len(list((ROOT/"docs/diagrams/mermaid").glob("*.mmd"))) == 6, "Expected six supplied Mermaid stage sources")

    # Check the example's mathematical hash, not authorization or semantic truth.
    proposal = load("schemas/examples/proposal-valid.json")
    raw = json.dumps(proposal["payload"], sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    check(hashlib.sha256(raw).hexdigest() == proposal["payload_sha256"], "Example proposal hash mismatch")
    for name in ["decision-valid", "outcome-success-valid", "outcome-unknown-valid"]:
        check(load(f"schemas/examples/{name}.json")["payload_sha256"] == proposal["payload_sha256"], f"Example hash not linked: {name}")

    print(f"PASS: package structure; {len(json_paths)} JSON files; {len(tasks)} acyclic tasks; {len(requirements)} covered requirements")
    print(f"PASS: {len(catalog['documents'])} source hashes; {len(scenarios)} development scenario cards; {py_count} Python syntax checks; 6 SVG XML files")
    print("PASS: synthetic proposal/decision/outcome example hashes agree")

    if args.contracts:
        try:
            from jsonschema import Draft202012Validator, FormatChecker
        except ImportError:
            print("BLOCKED: --contracts requires jsonschema in the tooling environment. This gate did not pass.", file=sys.stderr)
            return 2
        schema_paths = sorted((ROOT/"schemas").glob("*.schema.json"))
        for path in schema_paths:
            Draft202012Validator.check_schema(json.loads(path.read_text()))
        positive = negative = 0
        for item in examples:
            validator = Draft202012Validator(load(item["schema"]), format_checker=FormatChecker())
            errors = list(validator.iter_errors(load(item["path"])))
            check((len(errors) == 0) is item["valid"], f"Unexpected validation for {item['path']}: {[e.message for e in errors]}")
            if item['valid']:
                positive += 1
            else:
                negative += 1
        print(f"PASS: {len(schema_paths)} JSON Schema documents; {positive} accepted examples; {negative} rejected negative examples")

    if args.reference_code:
        original = load("provenance/reference-code-hashes.json")["files"]
        for item in original:
            check(hashlib.sha256(within(item["path"]).read_bytes()).hexdigest() == item["sha256"], f"Inherited code changed: {item['path']}")
        print(f"PASS: {len(original)} inherited source/test/integration files match original snapshot")

    if args.manifest:
        manifest = ROOT/"MANIFEST.sha256"
        check(manifest.is_file(), "No snapshot manifest")
        count = 0
        for line in manifest.read_text().splitlines():
            if not line.strip():
                continue
            expected, rel = line.split("  ", 1)
            check(bool(re.fullmatch(r"[a-f0-9]{64}", expected)), "Malformed checksum")
            p = within(rel)
            check(p.is_file(), f"Missing manifest file: {rel}")
            check(hashlib.sha256(p.read_bytes()).hexdigest() == expected, f"Snapshot changed: {rel}; intentional build changes need new release evidence")
            count += 1
        print(f"PASS: {count} delivered snapshot file checksums")

    print("LIMIT: These are handoff/contract checks, not real model, authorization, MCP network, browser, Docker, Kubernetes or production acceptance tests.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, KeyError, OSError, json.JSONDecodeError, SyntaxError, ElementTree.ParseError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)

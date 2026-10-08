"""R123: every reference test is traced to a port, a replacement with an owning task, or a justified drop.

Catches: a reference test silently forgotten when the inventory changes, a row pointing at a task that does not exist,
a 'port' row whose target test does not exist in tests/plan_c, and a drop without an AM-70 reason.
"""

import ast
import json
import re
from pathlib import Path

REF = Path("reference/tests")
DOC = Path("reference/TRACEABILITY.md")
# One table row: a backticked node id and four more cells. Cells may be empty (`| |`), so the cell patterns allow any
# run of non-pipe characters and the values are stripped after matching.
ROW = re.compile(
    r"^\|\s*`(?P<node>[^`]+)`\s*\|\s*(?P<disposition>port|replace-by|drop)\s*\|"
    r"(?P<target>[^|]*)\|(?P<task>[^|]*)\|(?P<reason>[^|]*)\|$"
)


def reference_node_ids() -> set[str]:
    """Rebuild pytest's node ids from the source: function names plus parametrize expansions (ids as pytest renders them)."""
    nodes: set[str] = set()
    for file in sorted(REF.glob("test_*.py")):
        tree = ast.parse(file.read_text(encoding="utf-8"))
        for fn in [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")]:
            params = [
                d for d in fn.decorator_list if isinstance(d, ast.Call) and getattr(d.func, "attr", "") == "parametrize"
            ]
            if not params:
                nodes.add(f"{file.name}::{fn.name}")
                continue
            for value in ast.literal_eval(params[0].args[1]):
                nodes.add(f"{file.name}::{fn.name}[{value}]")
    return nodes


def test_reference_inventory_has_58_cases():
    assert len(reference_node_ids()) == 58


def test_traceability_covers_all_58():
    matches = [ROW.match(line) for line in DOC.read_text(encoding="utf-8").splitlines()]
    rows = [{key: value.strip() for key, value in m.groupdict().items()} for m in matches if m]
    assert {r["node"] for r in rows} == reference_node_ids()
    tasks = {t["id"] for t in json.loads(Path("handoff/tasks.json").read_text(encoding="utf-8"))["tasks"]}
    local = {
        f"{f.name}::{n.name}"
        for f in Path("tests/plan_c").glob("test_*.py")
        for n in ast.parse(f.read_text(encoding="utf-8")).body
        if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")
    }
    for r in rows:
        if r["disposition"] == "port":
            assert r["target"] in local, r
        elif r["disposition"] == "replace-by":
            assert r["task"] in tasks, r
            assert r["target"], r
        else:
            assert "AM-70" in r["reason"] or "reference-only" in r["reason"], r
    counts = {d: sum(1 for r in rows if r["disposition"] == d) for d in ("port", "replace-by", "drop")}
    assert counts == {"port": 10, "replace-by": 46, "drop": 2}

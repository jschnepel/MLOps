"""Protect the monorepo layout decided in ADR-0001 (T04): one top-level directory per deployable service.

These tests catch a member that is not part of the uv workspace, a service that imports another service's
internals (coupling that would stop them deploying independently), and a service missing its trust-boundary README.
"""

import ast
import importlib
import tomllib
from pathlib import Path

# top-level directory -> importable package name; the seven members of the workspace (core is shared code).
MEMBERS = {
    "core": "ops_core",
    "api": "ops_api",
    "worker": "ops_worker",
    "mcp-read": "ops_mcp_read",
    "mcp-write": "ops_mcp_write",
    "asset-sim": "ops_asset_sim",
    "incident-sim": "ops_incident_sim",
}


def test_root_is_a_uv_workspace_excluding_reference():
    root = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    ws = root["tool"]["uv"]["workspace"]
    assert set(ws["members"]) == set(MEMBERS)
    # reference/ holds hash-pinned inherited code with its own pyproject files; uv must not treat it as a member.
    assert ws["exclude"] == ["reference"]
    assert Path(".python-version").read_text(encoding="utf-8").strip() == "3.13"


def test_each_member_imports_and_declares_only_core_as_internal_dependency():
    for directory, name in MEMBERS.items():
        mod = importlib.import_module(name)
        assert mod.__version__ == "0.0.1"
        py = tomllib.loads(Path(directory, "pyproject.toml").read_text(encoding="utf-8"))
        # Only core may be a declared internal dependency; services talk over the network, not by importing.
        internal = [d for d in py["project"].get("dependencies", []) if d.startswith("ops-")]
        assert internal in ([], ["ops-core"]), (directory, internal)
        assert py["project"]["requires-python"] == ">=3.13"


def test_no_cross_member_imports():
    """A member may import itself and ops_core; never another member's internals (AST scan, not pyproject)."""
    for directory, name in MEMBERS.items():
        for py in Path(directory, "src").rglob("*.py"):
            tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
            for node in ast.walk(tree):
                mods = []
                if isinstance(node, ast.Import):
                    mods = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    mods = [node.module]
                for m in mods:
                    top = m.split(".")[0]
                    if top.startswith("ops_"):
                        assert top in (name, "ops_core"), f"{py}: imports {m}"


def test_each_member_has_a_trust_boundary_readme():
    for directory in MEMBERS:
        text = Path(directory, "README.md").read_text(encoding="utf-8")
        assert "## Owns" in text and "## Trusts" in text and "## Never" in text, directory


def test_no_member_is_named_mcp():
    # The read and write MCP servers are separate services (mcp-read, mcp-write); a single "mcp" package would let
    # one process hold both read and write authority.
    assert "mcp" not in MEMBERS.values()

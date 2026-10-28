"""Contract test: the declared ``mcp`` range must match the API the server imports (#537).

The lockfile protects plugin installs, but ``pip install pyeye-mcp`` resolves
from the ``pyproject.toml`` ranges alone. pyeye-mcp 1.1.2 declared
``mcp[cli]>=1.13.0`` with no upper bound; mcp 2.x removed
``mcp.server.fastmcp`` (FastMCP became ``mcp.server.mcpserver.MCPServer``), so
a fresh pip install resolved mcp 2.x and the server failed on import.

The server also never imported the standalone ``fastmcp`` package — it uses the
FastMCP bundled in ``mcp`` — so declaring it only added an unused dependency
tree (and its security alerts).

When the server migrates to mcp 2.x (#538), update the import check and the
expected major together.
"""

from __future__ import annotations

import ast
from pathlib import Path

from packaging.requirements import Requirement

try:
    import tomllib
except ImportError:
    import tomli as tomllib

_ROOT = Path(__file__).resolve().parents[1]
_SERVER = _ROOT / "src" / "pyeye" / "mcp" / "server.py"


def _dependencies() -> dict[str, Requirement]:
    data = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    reqs = (Requirement(spec) for spec in data["project"]["dependencies"])
    return {req.name.lower(): req for req in reqs}


def _imported_modules(path: Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    return modules


def test_server_still_uses_mcp_v1_fastmcp():
    """Guard the premise: the server imports the mcp 1.x FastMCP location."""
    assert "mcp.server.fastmcp" in _imported_modules(_SERVER), (
        "server.py no longer imports mcp.server.fastmcp — if it migrated to mcp 2.x "
        "(#538), update this contract test and the mcp range together"
    )


def test_mcp_range_excludes_v2():
    """``mcp.server.fastmcp`` raises ModuleNotFoundError on mcp 2.x (#537)."""
    spec = _dependencies()["mcp"].specifier
    assert spec.contains("1.30.0"), f"mcp range {spec} must allow the locked 1.x line"
    assert not spec.contains("2.0.0"), (
        f"mcp range {spec} admits mcp 2.x, where mcp.server.fastmcp no longer "
        "exists; a fresh `pip install pyeye-mcp` would fail to import the server"
    )


def test_standalone_fastmcp_not_declared():
    """pyeye uses the FastMCP bundled in ``mcp``, not the ``fastmcp`` package."""
    assert (
        "fastmcp" not in _dependencies()
    ), "`fastmcp` is declared but never imported (the server uses mcp.server.fastmcp)"

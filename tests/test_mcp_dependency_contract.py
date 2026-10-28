"""Contract test: the declared ``mcp`` range must match the API the server imports.

The lockfile protects plugin installs, but ``pip install pyeye-mcp`` resolves
from the ``pyproject.toml`` ranges alone. pyeye-mcp 1.1.2 declared
``mcp[cli]>=1.13.0`` with no upper bound; mcp 2.x removed
``mcp.server.fastmcp``, so a fresh pip install resolved mcp 2.x and the server
failed on import (#537). The server now targets mcp 2.x's ``MCPServer`` (#538),
so the range must exclude 1.x (no ``mcp.server.mcpserver``) and the next major.

The server never imported the standalone ``fastmcp`` package, so declaring it
only added an unused dependency tree (and its security alerts).

When the server moves to another mcp major, update the import check and the
expected range together.
"""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

from packaging.requirements import Requirement

_ROOT = Path(__file__).resolve().parents[1]
_SERVER = _ROOT / "src" / "pyeye" / "mcp" / "server.py"


def _dependencies() -> dict[str, Requirement]:
    data = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    reqs = (Requirement(spec) for spec in data["project"]["dependencies"])
    return {req.name.lower(): req for req in reqs}


def _tree() -> ast.Module:
    return ast.parse(_SERVER.read_text(encoding="utf-8"))


def _imported_modules() -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(_tree()):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    return modules


def test_server_uses_mcp_v2_mcpserver():
    """Guard the premise: the server imports mcp 2.x's ``MCPServer`` (#538)."""
    modules = _imported_modules()
    assert "mcp.server.mcpserver" in modules, (
        "server.py no longer imports mcp.server.mcpserver — if it moved to another "
        "mcp major, update this contract test and the mcp range together"
    )
    assert "mcp.server.fastmcp" not in modules, "mcp.server.fastmcp raises on mcp 2.x"


def test_mcp_range_targets_v2():
    """The range admits the tested 2.x line and nothing that lacks ``MCPServer``."""
    spec = _dependencies()["mcp"].specifier
    assert spec.contains("2.3.0"), f"mcp range {spec} must allow the tested 2.x line"
    assert not spec.contains("1.30.0"), (
        f"mcp range {spec} admits mcp 1.x, which has no mcp.server.mcpserver; "
        "a fresh `pip install pyeye-mcp` could fail to import the server"
    )
    assert not spec.contains("3.0.0"), f"mcp range {spec} admits an untested major (3.x)"


def test_instructions_passed_by_keyword():
    """``MCPServer``'s second positional is ``title``, not ``instructions`` (#538).

    A positional ``instructions`` would silently become the server title and
    clients would receive no instructions. Only ``name`` may be positional.
    """
    calls = [
        node
        for node in ast.walk(_tree())
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "MCPServer"
    ]
    assert len(calls) == 1, f"expected one MCPServer(...) construction, found {len(calls)}"
    (call,) = calls
    assert len(call.args) <= 1, "pass everything after `name` by keyword"
    assert "instructions" in {kw.arg for kw in call.keywords}
    assert "version" in {
        kw.arg for kw in call.keywords
    }, "pass version=: mcp 2.x reports an empty server version otherwise"


def test_standalone_fastmcp_not_declared():
    """pyeye uses the server bundled in ``mcp``, not the ``fastmcp`` package."""
    assert "fastmcp" not in _dependencies(), "`fastmcp` is declared but never imported"

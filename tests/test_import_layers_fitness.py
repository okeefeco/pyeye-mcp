"""Import-layer fitness test (#623, epic #629).

The canonical-resolver design (#623) layers the code as::

    project_layout (#625)  →  kinds / scope / canonicalization  →  resolver
                           →  mcp operations and edges

The lower layers must never reach up into ``pyeye.mcp``. If they did, the
operations would again have to copy logic instead of sharing it, which is how
the drift in #629 started (audit mechanism M1). ``project_layout`` is pure path
logic and must not import ``jedi`` either.

Each rule is checked two ways:

* **statically:** every ``import`` statement in the module's source, including
  function-level and ``TYPE_CHECKING`` ones;
* **dynamically:** importing the module in a fresh interpreter must not load
  the banned package, so transitive imports are caught as well.

``resolver.py`` (#623 slice 2) and ``project_layout.py`` (#625 slice 1) don't
exist yet. The test covers whichever layer modules exist, so each one is
enforced from the moment it lands, with no edit here. Today's violations sit on
an exact allow-list (empty at the time of writing) keyed by
``(module, banned package)`` and the issue that removes them.
"""

from __future__ import annotations

import ast
import subprocess  # nosec B404 - runs this repo's own interpreter on a fixed snippet
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PKG_ROOT = REPO_ROOT / "src" / "pyeye"

#: Lower-layer modules → packages each must never import.
LAYER_RULES: dict[str, frozenset[str]] = {
    "resolver": frozenset({"pyeye.mcp"}),
    "canonicalization": frozenset({"pyeye.mcp"}),
    "scope": frozenset({"pyeye.mcp"}),
    "kinds": frozenset({"pyeye.mcp"}),
    "project_layout": frozenset({"pyeye.mcp", "jedi"}),
    "_module_scope": frozenset({"pyeye.mcp", "jedi"}),
    # #624: the one goto-disambiguation policy; it receives Jedi objects but
    # needs neither jedi nor pyeye.mcp itself.
    "_goto": frozenset({"pyeye.mcp", "jedi"}),
}

#: Modules that exist today; guards against a path bug quietly emptying the sweep.
ALWAYS_PRESENT = frozenset({"canonicalization", "scope", "kinds", "_module_scope", "_goto"})

#: ``(module, banned package)`` → the issue that removes the violation.
LAYER_ALLOWLIST: dict[tuple[str, str], str] = {}

_EPIC_CHILDREN = frozenset({"#623", "#624", "#625", "#626", "#628", "#630"})


def _present_modules() -> list[str]:
    return sorted(name for name in LAYER_RULES if (PKG_ROOT / f"{name}.py").is_file())


def _matches(module: str, banned: str) -> bool:
    return module == banned or module.startswith(banned + ".")


def _static_imports(source: str, module_name: str) -> set[str]:
    """Absolute dotted names imported anywhere in *source* (relative ones resolved)."""
    package_parts = ["pyeye"]  # every layer module sits directly in ``pyeye``
    names: set[str] = set()
    for node in ast.walk(ast.parse(source, filename=f"{module_name}.py")):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base_parts = package_parts[: len(package_parts) - (node.level - 1)]
                base = ".".join(base_parts + ([node.module] if node.module else []))
            else:
                base = node.module or ""
            names.add(base)
            # ``from pyeye import mcp`` imports the subpackage itself.
            names.update(f"{base}.{alias.name}" for alias in node.names)
    return names


def _static_violations(name: str) -> set[tuple[str, str]]:
    source = (PKG_ROOT / f"{name}.py").read_text(encoding="utf-8")
    imported = _static_imports(source, name)
    return {
        (name, banned)
        for banned in LAYER_RULES[name]
        if any(_matches(module, banned) for module in imported)
    }


def _dynamic_violations(name: str) -> set[tuple[str, str]]:
    banned = sorted(LAYER_RULES[name])
    snippet = (
        "import importlib, sys\n"
        f"importlib.import_module('pyeye.{name}')\n"
        f"banned = {banned!r}\n"
        "hits = sorted({b for b in banned for m in sys.modules"
        " if m == b or m.startswith(b + '.')})\n"
        "print('\\n'.join(hits))\n"
    )
    result = subprocess.run(  # nosec B603 - fixed argv, no shell
        [sys.executable, "-c", snippet],
        capture_output=True,
        text=True,
        check=True,
        cwd=REPO_ROOT,
    )
    return {(name, hit) for hit in result.stdout.split() if hit}


def _assert_layer(found: set[tuple[str, str]], name: str, how: str) -> None:
    expected = {key for key in LAYER_ALLOWLIST if key[0] == name}
    new = sorted(found - expected)
    fixed = sorted(expected - found)
    assert not new, (
        f"Layer violation ({how}): {new}. pyeye.{name} sits below pyeye.mcp in the "
        "#623 layering; move the shared logic down instead of importing up."
    )
    assert (
        not fixed
    ), f"Allow-listed layer violations no longer found ({how}): {fixed}; delete them."


def test_always_present_layer_modules_exist() -> None:
    assert set(_present_modules()) >= ALWAYS_PRESENT


@pytest.mark.parametrize("name", _present_modules())
def test_layer_module_static_imports(name: str) -> None:
    _assert_layer(_static_violations(name), name, "static import")


@pytest.mark.parametrize("name", _present_modules())
def test_layer_module_dynamic_imports(name: str) -> None:
    _assert_layer(_dynamic_violations(name), name, "loaded at import time")


def test_layer_allowlist_entries_are_owned() -> None:
    unowned = {k: v for k, v in LAYER_ALLOWLIST.items() if v not in _EPIC_CHILDREN}
    assert not unowned, f"Layer allow-list entries without a #629 child issue: {unowned}"
    unknown = {
        k for k in LAYER_ALLOWLIST if k[0] not in LAYER_RULES or k[1] not in LAYER_RULES[k[0]]
    }
    assert not unknown, f"Allow-list entries for rules that don't exist: {unknown}"


# ---------------------------------------------------------------------------
# Detector self-tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("import pyeye.mcp.operations.edges", {"pyeye.mcp.operations.edges"}),
        ("from pyeye.mcp import server", {"pyeye.mcp", "pyeye.mcp.server"}),
        ("from pyeye import mcp", {"pyeye", "pyeye.mcp"}),
        (
            "from .mcp.operations import edges",
            {"pyeye.mcp.operations", "pyeye.mcp.operations.edges"},
        ),
        ("from . import mcp", {"pyeye", "pyeye.mcp"}),
        (
            "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    import jedi\n",
            {"typing", "typing.TYPE_CHECKING", "jedi"},
        ),
        ("def f():\n    import jedi.api\n", {"jedi.api"}),
    ],
)
def test_static_import_detector(source: str, expected: set[str]) -> None:
    assert _static_imports(source, "demo") == expected


def test_banned_prefix_matching() -> None:
    assert _matches("pyeye.mcp", "pyeye.mcp")
    assert _matches("pyeye.mcp.operations", "pyeye.mcp")
    assert not _matches("pyeye.mcpx", "pyeye.mcp")
    assert _matches("jedi.api.classes", "jedi")
    assert not _matches("jedi_compat", "jedi")

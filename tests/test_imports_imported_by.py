"""``imports`` and ``imported_by`` agree in one direction only, on purpose (#619).

* ``imports`` reports the names a module BINDS at module scope (the #360 walk,
  guarded imports included, function- and class-body imports excluded).
* ``imported_by`` reports every project module that statically imports the
  target, wherever the import sits, because it answers "who depends on X" and a
  lazy import inside a function is still a dependency.

So the edges are not exact inverses. What must hold is the forward direction:
if module ``M``'s ``imports`` shows project module ``B``, then ``M`` is in
``imported_by(B)``. The reverse fails by design for function- and class-body
imports, and that asymmetry is pinned here so it can't change by accident.

Only MODULE stubs are checked. A symbol stub (``from pkg import Thing``) is
reported at its canonical definition site, so a re-exported name points at a
module ``M`` never imported directly; that is canonicalization, not scope.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.expand import expand
from tests.test_cross_tool_invariants import _SWEEP_CORPORA, _module_seeds, _sweep


def _handles(result: dict[str, Any]) -> list[str]:
    return [stub["handle"] for stub in result.get("stubs") or []]


def _project_module_stubs(result: dict[str, Any]) -> list[str]:
    return [
        stub["handle"]
        for stub in result.get("stubs") or []
        if stub.get("scope") == "project" and stub.get("kind") == "module"
    ]


# ---------------------------------------------------------------------------
# The forward property over the shared fixture corpora
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("corpus", sorted(_SWEEP_CORPORA))
async def test_imports_implies_imported_by_over_fixtures(corpus: str) -> None:
    sweep = await _sweep(corpus)
    missing = []
    for module in _module_seeds(_SWEEP_CORPORA[corpus]):
        for target in _project_module_stubs(sweep.expanded[module]["imports"]):
            importers = _handles(sweep.expanded.get(target, {}).get("imported_by") or {})
            if module not in importers:
                missing.append(f"{module} -> {target}: imported_by={importers}")
    assert not missing, "\n".join(missing)


# ---------------------------------------------------------------------------
# A project that exercises every import form
# ---------------------------------------------------------------------------

_FILES = {
    "app/__init__.py": "",
    "app/core.py": "class Thing:\n    pass\n",
    "app/util.py": "VALUE = 1\n",
    "app/sub/__init__.py": "",
    "app/sub/leaf.py": "X = 1\n",
    "app/plain.py": "import app.core\n",
    "app/aliased.py": "import app.util as u\n",
    "app/from_pkg.py": "from app import util\n",
    "app/from_sub.py": "from app.sub import leaf\n",
    "app/relative.py": "from . import core\n",
    "app/guarded.py": (
        "from typing import TYPE_CHECKING\n\nif TYPE_CHECKING:\n    from app import core\n"
    ),
    "app/shim.py": "try:\n    from app import util\nexcept ImportError:\n    util = None\n",
    # Lazy imports: dependencies, but they bind no module-scope name.
    "app/lazy.py": "def load():\n    from app import util\n\n    return util\n",
    "app/class_body.py": "class Holder:\n    from app import core\n",
}


@pytest.fixture
def forms_project(tmp_path: Path) -> Path:
    for rel, text in _FILES.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return tmp_path


def _modules() -> list[str]:
    names = []
    for rel in _FILES:
        parts = list(Path(rel).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        names.append(".".join(parts))
    return names


async def test_imports_implies_imported_by_for_every_import_form(forms_project: Path) -> None:
    analyzer = JediAnalyzer(str(forms_project))
    pairs = []
    missing = []
    for module in _modules():
        for target in _project_module_stubs(await expand(module, "imports", analyzer)):
            pairs.append((module, target))
            importers = _handles(await expand(target, "imported_by", analyzer))
            if module not in importers:
                missing.append(f"{module} -> {target}: imported_by={importers}")
    assert not missing, "\n".join(missing)
    # Non-vacuous: the module-binding forms all produced a module stub.
    sources = {module for module, _ in pairs}
    assert {
        "app.from_pkg",
        "app.from_sub",
        "app.relative",
        "app.guarded",
        "app.shim",
    } <= sources


@pytest.mark.parametrize(
    ("importer", "target"),
    [("app.lazy", "app.util"), ("app.class_body", "app.core")],
)
async def test_imported_by_counts_imports_that_imports_does_not(
    forms_project: Path, importer: str, target: str
) -> None:
    """The deliberate asymmetry: a function- or class-body import.

    ``imported_by`` reports the importer (it depends on the target), while the
    importer's ``imports`` doesn't show the target (no module-scope binding).
    """
    analyzer = JediAnalyzer(str(forms_project))
    assert importer in _handles(await expand(target, "imported_by", analyzer))
    assert target not in _handles(await expand(importer, "imports", analyzer))

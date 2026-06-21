"""Regression tests for #454 — definition-site/scope consistency across primitives.

When a symbol's canonical handle names a **project** module (e.g. a sibling repo
registered via a namespace ``.pyeye.json``) but the same package is *also*
importable from an external location that wins Jedi's import precedence (the
real-world case: the package is pip-installed in the environment), the
forward-goto edges (``imports`` / ``callees``) resolved the import to the
**external** copy and labelled the stub ``scope:"external"`` — while ``resolve`` /
``inspect`` resolved the same handle to the **project** copy (``scope:"project"``).

Same canonical handle, two definition sites, two scopes: a canonical-handle
invariant violation.

Why this is tested at the ``build_stub`` seam
---------------------------------------------
The *cause* (Jedi ``goto``/``follow_imports`` preferring an installed copy on the
environment ``sys.path`` over the namespace ``added_sys_path``) can only be
reproduced by actually installing a second copy into the environment — not
something a deterministic CI test should do.  The *fix* lives in ``build_stub``,
which must reconcile an externally-resolved edge target back to the project
definition site when the canonical handle names a project module.  We test that
reconciliation directly: a Jedi name whose ``module_path`` is external, paired
with a handle that ``find_module_file`` resolves to a project module, must yield
``scope:"project"`` pointing at the project file.  The full end-to-end path stays
covered by the live ``namespace-jaraco`` dogfooding scenario (see the
``pyeye-verify`` skill).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations import stubs as stubs_mod
from pyeye.mcp.operations.stubs import build_stub

_HANDLE = "extpkg.mod.Thing"


class _FakeName:
    """Minimal Jedi-``Name`` stand-in carrying just a ``module_path`` + ``line``.

    The kind / signature / end-line helpers are monkeypatched in the test, so
    this only needs the two attributes ``build_stub`` reads directly.
    """

    def __init__(self, module_path: Path) -> None:
        self.module_path = module_path
        self.line = 1


@pytest.fixture
def project_with_sibling(tmp_path: Path) -> tuple[JediAnalyzer, Path, Path]:
    """Analyzer whose ``additional_paths`` make ``extpkg.mod`` a project module.

    Returns ``(analyzer, sibling_file, external_file)`` where ``sibling_file`` is
    the project copy and ``external_file`` is an installed-style copy outside any
    project root.
    """
    project = tmp_path / "project"
    project.mkdir()

    sibling = tmp_path / "sibling"
    (sibling / "extpkg").mkdir(parents=True)
    (sibling / "extpkg" / "__init__.py").write_text("")
    sibling_file = sibling / "extpkg" / "mod.py"
    sibling_file.write_text("class Thing:\n    pass\n")

    external = tmp_path / "env" / "site-packages"
    (external / "extpkg").mkdir(parents=True)
    (external / "extpkg" / "__init__.py").write_text("")
    external_file = external / "extpkg" / "mod.py"
    external_file.write_text("class Thing:\n    pass\n")

    analyzer = JediAnalyzer(str(project))
    analyzer.set_additional_paths([sibling])
    return analyzer, sibling_file, external_file


@pytest.fixture(autouse=True)
def _stub_jedi_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neutralise the kind/signature/span helpers so the test isolates scope."""
    monkeypatch.setattr(stubs_mod, "_normalise_kind_from_name", lambda _name: "class")
    monkeypatch.setattr(stubs_mod, "get_end_line", lambda _name: 3)
    monkeypatch.setattr(stubs_mod, "_build_signature", lambda _name: None)


def test_external_edge_target_reconciles_to_project_definition_site(
    project_with_sibling: tuple[JediAnalyzer, Path, Path],
) -> None:
    """build_stub must report scope='project' when the handle names a project
    module, even though the Jedi name's module_path is an external copy (#454)."""
    analyzer, _sibling_file, external_file = project_with_sibling

    stub = build_stub(_FakeName(external_file), _HANDLE, analyzer)

    assert stub["scope"] == "project", (
        f"edge target for project handle {_HANDLE!r} mislabelled as "
        f"{stub['scope']!r}; should reconcile to the project definition site"
    )


def test_genuinely_external_target_stays_external(
    project_with_sibling: tuple[JediAnalyzer, Path, Path],
) -> None:
    """A handle with no project module (e.g. stdlib) must NOT be reconciled —
    reconciliation only rescues handles that map to a project module."""
    analyzer, _sibling_file, external_file = project_with_sibling

    stub = build_stub(_FakeName(external_file), "os.path.join", analyzer)

    assert stub["scope"] == "external", (
        "a handle that does not map to a project module must remain external; "
        f"got {stub['scope']!r}"
    )

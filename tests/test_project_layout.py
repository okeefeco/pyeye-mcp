"""One project-roots policy and one file↔module mapper pair (#625).

Two layers:

* **Library.** ``project_layout.project_roots`` builds each named roots subset,
  and ``module_name_for_file`` / ``file_for_module`` are inverses on every
  supported layout (flat, src, root-package, additional package, namespace).
* **Regressions at the swapped call sites.** These are the behaviour changes
  the consolidation makes, each a bug while the copies disagreed:

  - a project whose root *is* a package: ``imported_by``, ``resolve(<file>)``
    and ``find_module_file`` used the prefix-free mapper and gave ``b``/None
    instead of ``rootpkg.b`` (#619 bullet 1);
  - an importer in a configured additional package mapped to ``None`` and was
    silently dropped from ``imported_by`` (#619 bullet 2);
  - ``_scan_package_for_handle`` derived module names from source_roots +
    project only, so re-exports inside an additional package were dropped.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.canonicalization import _scan_package_for_handle, find_module_file
from pyeye.mcp.operations.expand import expand
from pyeye.mcp.operations.resolve import resolve
from pyeye.project_layout import (
    RootsBoundary,
    file_for_module,
    module_name_for_file,
    project_roots,
)


def _write(path: Path, text: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _layout(project: Path, **attrs: object) -> SimpleNamespace:
    base: dict[str, object] = {
        "project_path": project,
        "source_roots": [],
        "added_sys_path": [],
        "additional_paths": [],
        "namespace_paths": {},
    }
    base.update(attrs)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------------------
# Roots policy
# ---------------------------------------------------------------------------


class TestProjectRoots:
    @pytest.fixture
    def layout(self, tmp_path: Path) -> SimpleNamespace:
        project = tmp_path / "proj"
        src = project / "src"
        ns_repo = tmp_path / "ns-repo"
        shared = tmp_path / "shared"
        for d in (src, ns_repo, shared):
            d.mkdir(parents=True)
        return _layout(
            project,
            source_roots=[src],
            added_sys_path=[src, ns_repo],
            additional_paths=[shared],
        )

    def _names(self, roots: list[Path]) -> list[str]:
        return [r.name for r in roots]

    def test_each_boundary_names_its_subset_in_order(self, layout: SimpleNamespace) -> None:
        assert self._names(project_roots(layout, RootsBoundary.SCOPE)) == [
            "proj",
            "src",
            "shared",
        ]
        assert self._names(project_roots(layout, RootsBoundary.TOP_LEVEL_PACKAGE)) == [
            "proj",
            "src",
        ]
        assert self._names(project_roots(layout, RootsBoundary.MODULE_LOOKUP)) == [
            "src",
            "proj",
            "shared",
        ]
        # added_sys_path repeats src: deduped, first occurrence kept.
        assert self._names(project_roots(layout, RootsBoundary.NAMESPACE_PORTIONS)) == [
            "src",
            "proj",
            "ns-repo",
            "shared",
        ]

    def test_resolved_flag(self, tmp_path: Path) -> None:
        (tmp_path / "proj").mkdir()
        layout = _layout(tmp_path / "proj" / ".." / "proj")
        raw = project_roots(layout, RootsBoundary.SCOPE)
        assert raw == [tmp_path / "proj" / ".." / "proj"]
        resolved = project_roots(layout, RootsBoundary.SCOPE, resolved=True)
        assert resolved == [(tmp_path / "proj").resolve()]

    def test_missing_optional_attrs(self, tmp_path: Path) -> None:
        bare = SimpleNamespace(project_path=tmp_path)
        for boundary in RootsBoundary:
            assert project_roots(bare, boundary) == [tmp_path]


# ---------------------------------------------------------------------------
# Mapper pair
# ---------------------------------------------------------------------------


def _flat(tmp_path: Path) -> tuple[SimpleNamespace, dict[str, Path]]:
    project = tmp_path / "flat"
    files = {
        "pkg": _write(project / "pkg" / "__init__.py"),
        "pkg.mod": _write(project / "pkg" / "mod.py"),
        "top": _write(project / "top.py"),
    }
    return _layout(project), files


def _src(tmp_path: Path) -> tuple[SimpleNamespace, dict[str, Path]]:
    project = tmp_path / "srclayout"
    src = project / "src"
    files = {
        "spkg": _write(src / "spkg" / "__init__.py"),
        "spkg.sub.leaf": _write(src / "spkg" / "sub" / "leaf.py"),
    }
    _write(src / "spkg" / "sub" / "__init__.py")
    return _layout(project, source_roots=[src], added_sys_path=[src]), files


def _root_package(tmp_path: Path) -> tuple[SimpleNamespace, dict[str, Path]]:
    project = tmp_path / "rootpkg"
    files = {
        "rootpkg": _write(project / "__init__.py"),
        "rootpkg.a": _write(project / "a.py"),
        "rootpkg.inner": _write(project / "inner" / "__init__.py"),
        "rootpkg.inner.deep": _write(project / "inner" / "deep.py"),
    }
    return _layout(project, _jedi_root_is_parent=True), files


def _additional(tmp_path: Path) -> tuple[SimpleNamespace, dict[str, Path]]:
    project = tmp_path / "main"
    shared = tmp_path / "shared_lib"
    _write(project / "app.py")
    files = {
        "utils": _write(shared / "utils.py"),
        "helpers": _write(shared / "helpers" / "__init__.py"),
    }
    return _layout(project, additional_paths=[shared]), files


def _namespace(tmp_path: Path) -> tuple[SimpleNamespace, dict[str, Path]]:
    project = tmp_path / "nsmain"
    _write(project / "main.py")
    repo = tmp_path / "company-auth"  # repo root: path already spells `company/`
    direct = tmp_path / "direct" / "company"  # points straight at the namespace dir
    files = {
        "company.auth.models": _write(repo / "company" / "auth" / "models.py"),
        "company.billing": _write(direct / "billing" / "__init__.py"),
    }
    _write(repo / "company" / "auth" / "__init__.py")
    return _layout(project, namespace_paths={"company": [repo, direct]}), files


_LAYOUTS = [_flat, _src, _root_package, _additional, _namespace]


@pytest.mark.parametrize("make", _LAYOUTS, ids=lambda f: f.__name__.lstrip("_"))
def test_module_name_for_file(make, tmp_path: Path) -> None:
    layout, files = make(tmp_path)
    for name, file in files.items():
        assert module_name_for_file(layout, file) == name


@pytest.mark.parametrize(
    "make", [_flat, _src, _root_package, _additional], ids=lambda f: f.__name__.lstrip("_")
)
def test_round_trip(make, tmp_path: Path) -> None:
    """file → module → file and module → file → module are both identities.

    Namespace packages are left out on purpose: their modules are found by
    directory (``find_namespace_package_dirs``), not by ``file_for_module``.
    """
    layout, files = make(tmp_path)
    for name, file in files.items():
        assert file_for_module(layout, name) == file, name
        assert module_name_for_file(layout, file_for_module(layout, name)) == name


def test_file_outside_every_root_has_no_name(tmp_path: Path) -> None:
    layout, _ = _flat(tmp_path)
    assert module_name_for_file(layout, _write(tmp_path / "elsewhere" / "x.py")) is None


def test_non_python_file_has_no_name(tmp_path: Path) -> None:
    layout, _ = _flat(tmp_path)
    assert module_name_for_file(layout, _write(layout.project_path / "data.txt")) is None


def test_init_directly_at_a_root_has_no_name(tmp_path: Path) -> None:
    layout, _ = _src(tmp_path)
    assert module_name_for_file(layout, _write(layout.source_roots[0] / "__init__.py")) is None
    ns_layout, _ = _namespace(tmp_path)
    repo = ns_layout.namespace_paths["company"][0]
    assert module_name_for_file(ns_layout, _write(repo / "__init__.py")) is None


def test_unknown_module_has_no_file(tmp_path: Path) -> None:
    layout, _ = _flat(tmp_path)
    assert file_for_module(layout, "pkg.missing") is None
    assert file_for_module(layout, "") is None


def test_package_init_preferred_over_same_named_module(tmp_path: Path) -> None:
    project = tmp_path / "p"
    init = _write(project / "dup" / "__init__.py")
    _write(project / "dup.py")
    assert file_for_module(_layout(project), "dup") == init


def test_source_root_takes_precedence_over_project(tmp_path: Path) -> None:
    layout, files = _src(tmp_path)
    # Named from src/, never as `src.spkg...`.
    assert module_name_for_file(layout, files["spkg.sub.leaf"]) == "spkg.sub.leaf"


def test_root_package_flag_inferred_without_analyzer_attr(tmp_path: Path) -> None:
    layout, files = _root_package(tmp_path)
    del layout._jedi_root_is_parent
    assert module_name_for_file(layout, files["rootpkg.a"]) == "rootpkg.a"


# ---------------------------------------------------------------------------
# Regressions at the swapped call sites
# ---------------------------------------------------------------------------


@pytest.fixture
def root_package_project(tmp_path: Path) -> Path:
    project = tmp_path / "rootpkg"
    _write(project / "__init__.py")
    _write(project / "a.py", "class A:\n    pass\n")
    _write(project / "b.py", "from rootpkg.a import A\n\n\nclass B(A):\n    pass\n")
    return project


async def test_imported_by_names_root_package_importer(root_package_project: Path) -> None:
    analyzer = JediAnalyzer(str(root_package_project))
    result = await expand("rootpkg.a", "imported_by", analyzer)
    assert [s["handle"] for s in result["stubs"]] == ["rootpkg.b"]


async def test_resolve_file_in_root_package(root_package_project: Path) -> None:
    analyzer = JediAnalyzer(str(root_package_project))
    result = await resolve((root_package_project / "b.py").as_posix(), analyzer)
    assert result["found"] is True
    assert result["handle"] == "rootpkg.b"


def test_find_module_file_in_root_package(root_package_project: Path) -> None:
    analyzer = JediAnalyzer(str(root_package_project))
    assert find_module_file("rootpkg.a", analyzer) == root_package_project / "a.py"
    assert find_module_file("rootpkg", analyzer) == root_package_project / "__init__.py"


def test_find_init_file_in_root_package(root_package_project: Path) -> None:
    analyzer = JediAnalyzer(str(root_package_project))
    assert analyzer._find_init_file("rootpkg") == root_package_project / "__init__.py"


@pytest.fixture
def additional_package_project(tmp_path: Path) -> tuple[Path, Path]:
    project = tmp_path / "main"
    shared = tmp_path / "shared"
    _write(project / "core.py", "def target():\n    return 1\n")
    _write(shared / "consumer.py", "import core\n\n\ndef use():\n    return core.target()\n")
    _write(shared / "relib" / "__init__.py", "from relib.impl import Thing\n")
    _write(shared / "relib" / "impl.py", "class Thing:\n    pass\n")
    return project, shared


async def test_imported_by_reports_additional_package_importer(
    additional_package_project: tuple[Path, Path],
) -> None:
    project, shared = additional_package_project
    analyzer = JediAnalyzer(str(project))
    analyzer.set_additional_paths([shared])
    result = await expand("core", "imported_by", analyzer)
    assert "consumer" in [s["handle"] for s in result["stubs"]]


async def test_reexport_scan_keeps_additional_package_reexports(
    additional_package_project: tuple[Path, Path],
) -> None:
    project, shared = additional_package_project
    analyzer = JediAnalyzer(str(project))
    analyzer.set_additional_paths([shared])
    found = await _scan_package_for_handle("relib.impl.Thing", shared / "relib", analyzer)
    assert "relib.Thing" in found


# ---------------------------------------------------------------------------
# The mapper never invents a name (#668)
# ---------------------------------------------------------------------------


def test_unnormalised_namespace_root_beside_a_root_package(tmp_path: Path) -> None:
    """A root given as ``app/../repo`` maps by its module, not its path (#668).

    ``tmp/app/../corp-web/x.py`` is lexically "under" ``tmp/app``, so a
    root-package project used to claim it and name it
    ``app....corp-web.corp.web.views``.
    """
    project = tmp_path / "app"
    _write(project / "__init__.py")
    repo = tmp_path / "corp-web"
    views = _write(repo / "corp" / "web" / "views.py")
    unnormalised = project / ".." / "corp-web"
    layout = _layout(project, _jedi_root_is_parent=True, namespace_paths={"corp": [unnormalised]})
    assert module_name_for_file(layout, unnormalised / "corp" / "web" / "views.py") == (
        "corp.web.views"
    )
    assert module_name_for_file(layout, views) is None  # not under any root as spelled


@pytest.mark.parametrize(
    "rel",
    [
        "my-pkg/mod.py",  # hyphen: not importable
        "pkg/2fast.py",  # leading digit
        "pkg.v2/mod.py",  # a dot inside a directory name
        "pkg/mod.v2.py",  # a dot inside a module stem
    ],
)
def test_non_identifier_paths_have_no_module_name(tmp_path: Path, rel: str) -> None:
    project = tmp_path / "proj"
    file = _write(project / rel)
    assert module_name_for_file(_layout(project), file) is None

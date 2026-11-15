"""``imported_by`` reads a cached reverse import graph (#397 slice 2).

``find_importers`` (behind ``expand(handle, "imported_by")`` and every
``imported_by`` hop of ``trace``) used to re-scan every project file per target.
It now looks the target up in ``project_graph.get_import_graph``, built once per
project, layout, scope and generation, with the class graph's lifecycle (#397
slice 1). Pinned here:

- the graph answers exactly what the old per-target scan answered (a copy of it
  is the reference below), over fixtures and the pyeye repo itself;
- #668: an importer with no module name is still listed (``unresolved_importers``),
  warm or cold, never silently dropped;
- #619: ``imported_by`` counts function- and class-body imports that ``imports``
  doesn't, warm or cold;
- built once per generation, dropped by ``invalidate``, compact (no AST objects).
"""

from __future__ import annotations

import ast
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from pyeye import file_artifact_cache
from pyeye.analyzers import project_graph
from pyeye.analyzers.jedi_analyzer import Importers, JediAnalyzer
from pyeye.mcp.operations.expand import expand
from tests.test_imports_imported_by import _FILES as FORMS_FILES
from tests.utils.performance import PerformanceThresholds, assert_performance_threshold

REPO = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def _fresh_store() -> Any:
    project_graph.invalidate()
    yield
    project_graph.invalidate()


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


@pytest.fixture
def forms(tmp_path: Path) -> Path:
    """#619's corpus: every import form, plus function- and class-body imports."""
    for rel, text in FORMS_FILES.items():
        _write(tmp_path / rel, text)
    return tmp_path


@pytest.fixture
def unnamed(tmp_path: Path) -> dict[str, Path]:
    """#668's corpus: importers whose files have no module name."""
    root = tmp_path / "proj"
    _write(root / "pkg" / "__init__.py", "")
    target = _write(root / "pkg" / "target.py", "def f():\n    return 1\n")
    _write(root / "pkg" / "named.py", "import pkg.target\n")
    return {
        "root": root,
        "target": target,
        "script": _write(root / "my-script.py", "import pkg.target\n"),
        "tool": _write(root / "tools-dir" / "use_target.py", "from pkg import target\n"),
        "relative": _write(root / "tools-dir" / "rel.py", "from . import target\n"),
    }


def _reference_scan(
    analyzer: JediAnalyzer, module_path: str, target_file: Path, py_files: list[Path]
) -> Importers:
    """The pre-#397 per-target scan, verbatim in logic (text pre-filter, then AST)."""
    target_root = module_path.split(".")[0]
    importers: dict[str, Path] = {}
    unnamed: list[Path] = []

    def record(importer: str | None, py_file: Path) -> None:
        if importer is None:
            unnamed.append(py_file)
        elif importer not in importers:
            importers[importer] = py_file

    for py_file in py_files:
        if py_file == target_file:
            continue
        try:
            importer_module = analyzer._get_import_path_for_file(py_file)
            source = py_file.read_text(encoding="utf-8")
            shares_package = bool(importer_module and importer_module.split(".")[0] == target_root)
            parent_pkg = module_path.rsplit(".", 1)[0] if "." in module_path else None
            if not (
                module_path in source
                or module_path.replace(".", "/") in source
                or shares_package
                or (parent_pkg is not None and parent_pkg in source)
            ):
                continue
            importer_is_package = py_file.name == "__init__.py"
            tree = file_artifact_cache.get_ast(py_file)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    if any(
                        a.name == module_path or a.name.startswith(module_path + ".")
                        for a in node.names
                    ):
                        record(importer_module, py_file)
                        break
                elif isinstance(node, ast.ImportFrom):
                    if node.level and importer_module is None:
                        continue
                    resolved = analyzer._resolve_relative_import(
                        node.level, node.module, importer_module or "", importer_is_package
                    )
                    if resolved and (
                        resolved == module_path
                        or resolved.startswith(module_path + ".")
                        or any(
                            f"{resolved}.{a.name}" == module_path
                            for a in node.names
                            if a.name != "*"
                        )
                    ):
                        record(importer_module, py_file)
                        break
        except Exception:
            continue
    return Importers(
        named=[(m, importers[m]) for m in sorted(importers)],
        unnamed=unnamed,
    )


async def _assert_matches_reference(analyzer: JediAnalyzer, modules: list[str]) -> int:
    """Every module's graph answer equals the old scan's; returns importer pairs seen."""
    py_files = sorted(await analyzer.get_project_files("*.py", "all"), key=Path.as_posix)
    by_module = {analyzer._get_import_path_for_file(f): f for f in py_files}
    seen = 0
    for module in modules:
        target_file = by_module.get(module, Path("<none>"))
        got = await analyzer.find_importers(module, target_file, scope="all")
        want = _reference_scan(analyzer, module, target_file, py_files)
        assert got == want, module
        seen += len(got.named) + len(got.unnamed)
    return seen


class TestSameAnswerAsTheOldScan:
    async def test_every_form_in_the_619_corpus(self, forms: Path) -> None:
        analyzer = JediAnalyzer(str(forms))
        modules = sorted(
            m for m in (analyzer._get_import_path_for_file(forms / rel) for rel in FORMS_FILES) if m
        )
        assert await _assert_matches_reference(analyzer, modules) > 0

    async def test_unnamed_importers_corpus(self, unnamed: dict[str, Path]) -> None:
        analyzer = JediAnalyzer(str(unnamed["root"]))
        assert await _assert_matches_reference(analyzer, ["pkg", "pkg.target", "pkg.named"]) > 0

    async def test_the_pyeye_repo(self) -> None:
        """A real 470-file tree: a sample of its modules, including the busiest."""
        analyzer = JediAnalyzer(str(REPO))
        modules = [
            "pyeye",
            "pyeye.handle",
            "pyeye.resolver",
            "pyeye.file_artifact_cache",
            "pyeye.analyzers.project_graph",
            "pyeye.analyzers.jedi_analyzer",
            "pyeye.mcp.operations.edges",
            "pyeye.mcp.operations.expand",
            "pyeye.plugins.base",
            "pyeye.path_utils",
            "pyeye.settings",
            "tests.utils.performance",
            "tests.test_cross_tool_invariants",
        ]
        assert await _assert_matches_reference(analyzer, modules) > 50


class TestPinnedContracts:
    async def test_668_unnamed_importers_are_listed_warm_and_cold(
        self, unnamed: dict[str, Path]
    ) -> None:
        analyzer = JediAnalyzer(str(unnamed["root"]))
        expected = sorted(p.as_posix() for p in (unnamed["script"], unnamed["tool"]))

        cold = await expand("pkg.target", "imported_by", analyzer)
        warm = await expand("pkg.target", "imported_by", analyzer)

        for result in (cold, warm):
            assert [s["handle"] for s in result["stubs"]] == ["pkg.named"]
            assert result["unresolved_importers"] == expected  # never silently dropped

    @pytest.mark.parametrize(
        ("importer", "target"),
        [("app.lazy", "app.util"), ("app.class_body", "app.core")],
    )
    async def test_619_body_imports_count_for_imported_by_only(
        self, forms: Path, importer: str, target: str
    ) -> None:
        analyzer = JediAnalyzer(str(forms))
        for _ in ("cold", "warm"):
            importers = [
                s["handle"] for s in (await expand(target, "imported_by", analyzer))["stubs"]
            ]
            imported = [s["handle"] for s in (await expand(importer, "imports", analyzer))["stubs"]]
            assert importer in importers
            assert target not in imported


class TestLifecycle:
    async def test_built_once_per_generation(self, unnamed: dict[str, Path]) -> None:
        analyzer = JediAnalyzer(str(unnamed["root"]))
        with patch.object(
            analyzer, "_build_import_graph", wraps=analyzer._build_import_graph
        ) as build:
            for module in ("pkg.target", "pkg.named", "pkg", "pkg.target"):
                await analyzer.find_importers(module, Path("<none>"))

        assert build.call_count == 1

    async def test_an_added_importer_is_seen_after_invalidation(
        self, unnamed: dict[str, Path]
    ) -> None:
        root = unnamed["root"]
        analyzer = JediAnalyzer(str(root))
        before = await analyzer.find_importers("pkg.target", unnamed["target"])
        _write(root / "pkg" / "late.py", "def g():\n    from pkg import target\n")

        assert await analyzer.find_importers("pkg.target", unnamed["target"]) == before

        project_graph.invalidate(str(root))
        analyzer.scoped_cache.invalidate_all()
        after = await analyzer.find_importers("pkg.target", unnamed["target"])

        assert [m for m, _ in after.named] == ["pkg.late", "pkg.named"]
        assert after.unnamed == before.unnamed

    async def test_a_module_never_reports_itself(self, tmp_path: Path) -> None:
        _write(tmp_path / "pkg" / "__init__.py", "")
        own = _write(tmp_path / "pkg" / "selfish.py", "import pkg.selfish\n")
        analyzer = JediAnalyzer(str(tmp_path))

        assert await analyzer.find_importers("pkg.selfish", own) == Importers([], [])

    def test_class_and_import_graphs_are_separate_entries(self, tmp_path: Path) -> None:
        root = str(tmp_path)
        imports = project_graph.get_import_graph(
            root, lambda: project_graph.ImportGraph(importers={"a": ()})
        )
        classes = project_graph.get_class_graph(
            root,
            lambda: project_graph.ClassGraph(
                classes={}, children_by_key={}, import_tables={}, module_defines={}, star_sources={}
            ),
        )
        assert (
            project_graph.get_import_graph(root, lambda: project_graph.ImportGraph({})) is imports
        )
        assert classes is not imports

        project_graph.invalidate(root)
        assert (
            project_graph.get_import_graph(root, lambda: project_graph.ImportGraph({}))
            is not imports
        )

    async def test_graph_holds_no_ast_objects(self, forms: Path) -> None:
        analyzer = JediAnalyzer(str(forms))
        files = sorted(await analyzer.get_project_files("*.py", "all"), key=Path.as_posix)
        graph = analyzer._build_import_graph(files)

        assert graph.importers
        for target, entries in graph.importers.items():
            assert isinstance(target, str)
            for module, path in entries:
                assert module is None or isinstance(module, str)
                assert isinstance(path, Path)


# A warm lookup is a dict read; the bound only has to separate it from a rescan.
WARM_LOOKUP = PerformanceThresholds(base=50.0, linux_ci=100.0, macos_ci=200.0, windows_ci=200.0)


async def test_warm_lookups_skip_the_scan() -> None:
    """Report cold vs warm on the pyeye repo, and bound the warm lookup."""
    analyzer = JediAnalyzer(str(REPO))
    targets = ["pyeye.handle", "pyeye.resolver", "pyeye.settings", "pyeye.path_utils"]

    start = time.perf_counter()
    cold = await analyzer.find_importers(targets[0], Path("<none>"))
    cold_ms = (time.perf_counter() - start) * 1000

    warm_ms = []
    for target in targets:
        start = time.perf_counter()
        warm = await analyzer.find_importers(target, Path("<none>"))
        warm_ms.append((time.perf_counter() - start) * 1000)
        assert warm.named, target

    assert cold.named
    print(f"\n#397 import graph: cold {cold_ms:.1f} ms, warm {max(warm_ms):.1f} ms (max of 4)")
    assert_performance_threshold(max(warm_ms), WARM_LOOKUP, "Warm find_importers (#397)")

"""``imported_by`` reads a cached reverse import graph (#397 slice 2).

``find_importers`` (behind ``expand(handle, "imported_by")`` and every
``imported_by`` hop of ``trace``) used to re-scan every project file per target.
It now looks the target up in ``project_graph.get_import_graph``, built once per
project, layout, scope and generation, with the class graph's lifecycle (#397
slice 1). Pinned here:

- the graph answers exactly what the old per-target scan answered (a copy of it
  is the reference below), over fixtures and the pyeye repo itself, plus the
  files it couldn't parse (#729), which the old scan skipped without a word;
- #668: an importer with no module name is still listed (``unresolved_importers``),
  warm or cold, never silently dropped;
- #619: ``imported_by`` counts function- and class-body imports that ``imports``
  doesn't, warm or cold;
- built once per generation, dropped by ``invalidate``, compact (no AST objects).
"""

from __future__ import annotations

import ast
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from pyeye import file_artifact_cache
from pyeye.analyzers import project_graph
from pyeye.analyzers.jedi_analyzer import Importers, JediAnalyzer
from pyeye.mcp.operations.expand import expand
from pyeye.path_utils import path_to_key
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
    """The pre-#397 per-target scan, verbatim in logic (text pre-filter, then AST).

    Plus #729's disclosure, which predates nothing here but the old scan never
    had: every file in scope that raises ``SyntaxError`` is listed, for every
    target, whether or not the text pre-filter would have read it. Without it
    the oracle disagreed with the graph on any tree holding such a file (#810:
    a django clone under ``.scenario-repos/`` failed ``test_the_pyeye_repo``).
    """
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
    unparseable: list[str] = []
    for py_file in py_files:
        try:
            file_artifact_cache.get_ast(py_file)
        except SyntaxError:  # only a parse failure is "unparseable" (#704, #729)
            unparseable.append(path_to_key(py_file))
        except Exception:
            continue
    return Importers(
        named=[(m, importers[m]) for m in sorted(importers)],
        unnamed=unnamed,
        unparseable=tuple(sorted(unparseable)),
    )


_RAISED = object()  # a file whose module name or text couldn't be read


@dataclass
class _ScanMemo:
    """Per-file work :func:`_reference_scan` repeats for every target (#893).

    Its own dicts, built from the same calls the verbatim scan makes, so the
    oracle stays independent of the graph it checks.
    """

    head: dict[Path, Any] = field(default_factory=dict)  # (importer module, source) | _RAISED
    imports: dict[Path, Any] = field(default_factory=dict)  # import nodes in walk order | _RAISED
    unparseable: tuple[str, ...] | None = None


def _reference_scan_memo(
    analyzer: JediAnalyzer,
    module_path: str,
    target_file: Path,
    py_files: list[Path],
    memo: _ScanMemo,
) -> Importers:
    """:func:`_reference_scan`, with each file's per-target work done once.

    The text pre-filter and the import tests are the verbatim scan's, line for
    line. What is memoised is what doesn't depend on the target: a file's module
    name and source, its ``Import``/``ImportFrom`` nodes in ``ast.walk`` order
    (the loop below only looks at those and stops at the first match, so the
    order is the one the full walk would have seen), and the unparseable list. A
    file is parsed only when the pre-filter first lets it through, as before.
    ``TestTheMemoisedOracleIsTheVerbatimOne`` pins it to the verbatim scan.
    """
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
            if py_file not in memo.head:
                try:
                    memo.head[py_file] = (
                        analyzer._get_import_path_for_file(py_file),
                        py_file.read_text(encoding="utf-8"),
                    )
                except Exception:
                    memo.head[py_file] = _RAISED
            head = memo.head[py_file]
            if head is _RAISED:
                continue
            importer_module, source = head
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
            if py_file not in memo.imports:
                try:
                    tree = file_artifact_cache.get_ast(py_file)
                    memo.imports[py_file] = [
                        n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
                    ]
                except Exception:
                    memo.imports[py_file] = _RAISED
            nodes = memo.imports[py_file]
            if nodes is _RAISED:
                continue
            for node in nodes:
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
    if memo.unparseable is None:
        unparseable: list[str] = []
        for py_file in py_files:
            try:
                file_artifact_cache.get_ast(py_file)
            except SyntaxError:  # only a parse failure is "unparseable" (#704, #729)
                unparseable.append(path_to_key(py_file))
            except Exception:
                continue
        memo.unparseable = tuple(sorted(unparseable))
    return Importers(
        named=[(m, importers[m]) for m in sorted(importers)],
        unnamed=unnamed,
        unparseable=memo.unparseable,
    )


async def _assert_matches_reference(analyzer: JediAnalyzer, modules: list[str]) -> int:
    """Every module's graph answer equals the old scan's; returns importer pairs seen."""
    py_files = sorted(await analyzer.get_project_files("*.py", "all"), key=Path.as_posix)
    by_module = {analyzer._get_import_path_for_file(f): f for f in py_files}
    memo = _ScanMemo()  # per comparison: one file list, one set of reads (#893)
    seen = 0
    for module in modules:
        target_file = by_module.get(module, Path("<none>"))
        got = await analyzer.find_importers(module, target_file, scope="all")
        want = _reference_scan_memo(analyzer, module, target_file, py_files, memo)
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

    async def test_a_tree_with_an_unparseable_file(self, tmp_path: Path) -> None:
        """#810: a syntax-error file is disclosed for every target, by both sides."""
        _write(tmp_path / "pkg" / "__init__.py", "")
        _write(tmp_path / "pkg" / "target.py", "def f():\n    return 1\n")
        _write(tmp_path / "pkg" / "user.py", "from pkg import target\n")
        broken = _write(tmp_path / "vendor" / "tests_syntax_error.py", "def (:\n")
        analyzer = JediAnalyzer(str(tmp_path))

        assert await _assert_matches_reference(analyzer, ["pkg", "pkg.target", "pkg.user"]) > 0
        got = await analyzer.find_importers("pkg", tmp_path / "pkg" / "__init__.py", scope="all")
        assert got.unparseable == (path_to_key(broken),)

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


class TestTheMemoisedOracleIsTheVerbatimOne:
    """``_reference_scan_memo`` answers exactly what ``_reference_scan`` does (#893).

    The memo only stops re-reading and re-walking each file per target; the
    pyeye-repo comparison above uses it. These pin it to the verbatim oracle on
    every corpus here (not on the repo: its verbatim scan is the cost being cut).
    """

    @staticmethod
    async def _both_agree(analyzer: JediAnalyzer, modules: list[str]) -> int:
        py_files = sorted(await analyzer.get_project_files("*.py", "all"), key=Path.as_posix)
        by_module = {analyzer._get_import_path_for_file(f): f for f in py_files}
        memo = _ScanMemo()
        checked = 0
        for module in modules:
            target_file = by_module.get(module, Path("<none>"))
            verbatim = _reference_scan(analyzer, module, target_file, py_files)
            assert (
                _reference_scan_memo(analyzer, module, target_file, py_files, memo) == verbatim
            ), module
            checked += 1
        return checked

    async def test_the_619_forms_corpus(self, forms: Path) -> None:
        analyzer = JediAnalyzer(str(forms))
        modules = sorted(
            m for m in (analyzer._get_import_path_for_file(forms / rel) for rel in FORMS_FILES) if m
        )
        assert await self._both_agree(analyzer, modules) == len(modules) > 0

    async def test_the_unnamed_importers_corpus(self, unnamed: dict[str, Path]) -> None:
        analyzer = JediAnalyzer(str(unnamed["root"]))
        assert await self._both_agree(analyzer, ["pkg", "pkg.target", "pkg.named"]) == 3

    async def test_a_tree_with_an_unparseable_file(self, tmp_path: Path) -> None:
        _write(tmp_path / "pkg" / "__init__.py", "")
        _write(tmp_path / "pkg" / "target.py", "def f():\n    return 1\n")
        _write(tmp_path / "pkg" / "user.py", "from pkg import target\nimport os\n")
        _write(tmp_path / "vendor" / "tests_syntax_error.py", "def (:\n")
        _write(tmp_path / "vendor" / "latin1.py", b"x = '\xe9'\n".decode("latin-1"))
        (tmp_path / "vendor" / "bad_bytes.py").write_bytes(b"x = '\xff\xfe'\n")
        analyzer = JediAnalyzer(str(tmp_path))
        assert await self._both_agree(analyzer, ["pkg", "pkg.target", "pkg.user", "os"]) == 4


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

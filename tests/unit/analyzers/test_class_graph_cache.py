"""The resolved class graph is cached per project, layout, scope and generation (#397).

``find_subclasses`` (behind ``expand(handle, "subclasses")`` and every hop of
``trace(follow=["subclasses"])``) used to build the project's resolved class
graph, with Jedi ``goto`` fallbacks, and throw it away on every call. It now
lives in ``project_graph`` beside the name index, with the same lifecycle:

- built once per generation, with an identical answer to a fresh build;
- dropped by ``project_graph.invalidate`` (watcher, eviction, configure_packages),
  after which it is rebuilt, never reported empty;
- a build that raced an invalidation is returned but not cached (#617);
- separate per layout (#618) and per scope;
- strings and ints only: no AST, Jedi or parso objects are retained (#713).
"""

from __future__ import annotations

import ast
import dataclasses
import shutil
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from pyeye.analyzers import project_graph
from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.analyzers.project_graph import ClassFact, ClassGraph
from pyeye.mcp.operations.edges import resolve_subclasses
from tests.utils.performance import PerformanceThresholds, assert_performance_threshold

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"

ANIMALS = """\
class Animal:
    pass


class Dog(Animal):
    pass


class Cat(Animal):
    pass


class Puppy(Dog):
    pass
"""


@pytest.fixture(autouse=True)
def _fresh_store() -> Any:
    project_graph.invalidate()
    yield
    project_graph.invalidate()


def _project(tmp_path: Path) -> JediAnalyzer:
    (tmp_path / "animals.py").write_text(ANIMALS)
    return JediAnalyzer(str(tmp_path))


def _names(result: dict[str, Any]) -> list[str]:
    return sorted(r["full_name"] for r in result["subclasses"])


def _graph(name: str = "x") -> ClassGraph:
    return ClassGraph(
        classes={name: ClassFact(name, Path("x.py"), 1, 1, 0)},
        children_by_key={},
        import_tables={},
        module_defines={},
        star_sources={},
    )


class TestBuiltOncePerGeneration:
    async def test_second_query_reuses_the_graph(self, tmp_path: Path) -> None:
        analyzer = _project(tmp_path)
        with patch.object(
            analyzer, "_build_class_graph", wraps=analyzer._build_class_graph
        ) as build:
            first = await analyzer.find_subclasses("animals.Animal")
            second = await analyzer.find_subclasses("animals.Dog")
            third = await analyzer.find_subclasses("animals.Animal")

        assert build.call_count == 1
        assert _names(first) == ["animals.Cat", "animals.Dog"]
        assert _names(second) == ["animals.Puppy"]
        assert third == first

    async def test_cached_answer_equals_a_fresh_build(self, tmp_path: Path) -> None:
        analyzer = _project(tmp_path)
        warm_first = await analyzer.find_subclasses("animals.Animal")
        warm = await analyzer.find_subclasses("animals.Animal")
        project_graph.invalidate()
        fresh = await analyzer.find_subclasses("animals.Animal")

        assert warm == warm_first
        assert _names(warm) == _names(fresh)
        assert sorted(warm["subclasses"], key=lambda r: r["full_name"]) == sorted(
            fresh["subclasses"], key=lambda r: r["full_name"]
        )

    @pytest.mark.parametrize(
        "fixture",
        [
            "subclasses_edge",
            "issue_335_subclasses",
            "subclasses_resolution",
            "determinism_subclasses",
        ],
    )
    async def test_edge_answers_match_a_fresh_build_on_every_fixture_class(
        self, fixture: str, tmp_path: Path
    ) -> None:
        """Same stubs, same order, warm or cold, for every class in the fixture."""
        root = tmp_path / fixture
        shutil.copytree(FIXTURES / fixture, root)
        analyzer = JediAnalyzer(str(root))
        graph_classes = await self._all_classes(analyzer)
        assert graph_classes, "fixture has classes"

        warm = {fqn: await self._edge(fqn, analyzer) for fqn in graph_classes}
        assert any(warm.values()), "some fixture class has subclasses"
        for fqn in graph_classes:
            project_graph.invalidate()
            assert await self._edge(fqn, analyzer) == warm[fqn], fqn

    @staticmethod
    async def _all_classes(analyzer: JediAnalyzer) -> list[str]:
        files = await analyzer.get_project_files("*.py", None)
        graph = analyzer._build_class_graph(files)
        # Keyed by definition site (#1006): the edge's inputs are the named classes.
        return sorted(f.full_name for f in graph.classes.values() if f.full_name is not None)

    @staticmethod
    async def _edge(fqn: str, analyzer: JediAnalyzer) -> list[tuple[str, int, int]]:
        class _Name:
            full_name = fqn

        result = await resolve_subclasses(_Name(), analyzer)
        return [(str(h), n.line, n.end_line) for h, n in result.adjacents]


class TestInvalidation:
    async def test_an_edit_is_seen_after_invalidation(self, tmp_path: Path) -> None:
        analyzer = _project(tmp_path)
        before = await analyzer.find_subclasses("animals.Animal")
        (tmp_path / "birds.py").write_text(
            "from animals import Animal\n\nclass Bird(Animal):\n    pass\n"
        )

        # Without invalidation the generation's graph (and file list) stands:
        # freshness comes from the watcher, as for the name index.
        assert await analyzer.find_subclasses("animals.Animal") == before

        project_graph.invalidate(str(tmp_path))
        analyzer.scoped_cache.invalidate_all()
        after = await analyzer.find_subclasses("animals.Animal")

        assert _names(after) == ["animals.Cat", "animals.Dog", "birds.Bird"]

    async def test_invalidating_another_project_keeps_this_graph(self, tmp_path: Path) -> None:
        analyzer = _project(tmp_path)
        with patch.object(
            analyzer, "_build_class_graph", wraps=analyzer._build_class_graph
        ) as build:
            await analyzer.find_subclasses("animals.Animal")
            project_graph.invalidate(str(tmp_path / "elsewhere"))
            await analyzer.find_subclasses("animals.Animal")

        assert build.call_count == 1

    def test_invalidate_drops_class_graphs(self, tmp_path: Path) -> None:
        built: list[int] = []

        def build() -> ClassGraph:
            built.append(1)
            return _graph()

        project_graph.get_class_graph(str(tmp_path), build)
        project_graph.invalidate(str(tmp_path))
        project_graph.get_class_graph(str(tmp_path), build)
        project_graph.invalidate()
        project_graph.get_class_graph(str(tmp_path), build)

        assert len(built) == 3

    def test_a_build_that_raced_an_invalidation_is_not_cached(self, tmp_path: Path) -> None:
        root = str(tmp_path)
        generation = project_graph.generation(root)

        def racing_build() -> ClassGraph:
            project_graph.invalidate(root)  # a watcher event lands mid-build
            return _graph("stale")

        stale = project_graph.get_class_graph(root, racing_build, generation)
        fresh = project_graph.get_class_graph(
            root, lambda: _graph("fresh"), project_graph.generation(root)
        )

        assert "stale" in stale.classes  # returned to its caller...
        assert "fresh" in fresh.classes  # ...but never served from the cache


class TestKeying:
    def test_layouts_and_scopes_get_separate_graphs(self, tmp_path: Path) -> None:
        root = str(tmp_path)
        graphs = {
            (layout, scope): project_graph.get_class_graph(
                root, lambda n=f"{layout}/{scope}": _graph(n), layout_key=layout, scope_key=scope
            )
            for layout in ("bare", "managed")
            for scope in ("main", "all")
        }

        assert len({id(g) for g in graphs.values()}) == 4
        for (layout, scope), graph in graphs.items():
            assert f"{layout}/{scope}" in graph.classes
            # And each is served from the cache on the next call.
            assert (
                project_graph.get_class_graph(
                    root, lambda: _graph("rebuilt"), layout_key=layout, scope_key=scope
                )
                is graph
            )

    def test_root_spellings_share_one_graph(self, tmp_path: Path) -> None:
        first = project_graph.get_class_graph(str(tmp_path), lambda: _graph("a"))
        second = project_graph.get_class_graph(str(tmp_path / "." / ""), lambda: _graph("b"))

        assert second is first


class TestCompactness:
    async def test_graph_holds_no_ast_or_jedi_objects(self, tmp_path: Path) -> None:
        analyzer = _project(tmp_path)
        files = await analyzer.get_project_files("*.py", None)
        graph = analyzer._build_class_graph(files)

        # None: ClassFact's optional full_name / unnamed_reason (#1006). Pins nothing.
        allowed = (str, int, Path, ClassFact, frozenset, list, dict, tuple, type(None))
        stack: list[Any] = [getattr(graph, f.name) for f in dataclasses.fields(graph)]
        while stack:
            value = stack.pop()
            assert not isinstance(value, ast.AST), value
            assert isinstance(value, allowed), type(value)
            if isinstance(value, dict):
                stack.extend(value.keys())
                stack.extend(value.values())
            elif isinstance(value, (list, tuple, frozenset)):
                stack.extend(value)
            elif isinstance(value, ClassFact):
                stack.extend(getattr(value, f.name) for f in dataclasses.fields(value))


# Warm lookups are dict reads; the bound only has to separate them from a rebuild.
WARM_QUERY = PerformanceThresholds(base=50.0, linux_ci=100.0, macos_ci=200.0, windows_ci=200.0)


async def test_warm_queries_skip_the_build(tmp_path: Path) -> None:
    """Report cold vs warm, and bound the warm query (PerformanceThresholds)."""
    for i in range(60):
        body = "".join(
            f"\nclass C{i}_{j}({'Base' if j == 0 else f'C{i}_{j - 1}'}):\n    pass\n"
            for j in range(8)
        )
        (tmp_path / f"m{i}.py").write_text("from base import Base\n" + body)
    (tmp_path / "base.py").write_text("class Base:\n    pass\n")
    analyzer = JediAnalyzer(str(tmp_path))

    start = time.perf_counter()
    cold = await analyzer.find_subclasses("base.Base")
    cold_ms = (time.perf_counter() - start) * 1000

    warm_ms = []
    for target in ("base.Base", "m0.C0_0", "m59.C59_3"):
        start = time.perf_counter()
        warm = await analyzer.find_subclasses(target)
        warm_ms.append((time.perf_counter() - start) * 1000)
        assert warm["subclasses"], target

    assert len(cold["subclasses"]) == 60
    print(f"\n#397 class graph: cold {cold_ms:.1f} ms, warm {max(warm_ms):.1f} ms (max of 3)")
    assert_performance_threshold(max(warm_ms), WARM_QUERY, "Warm find_subclasses (#397)")

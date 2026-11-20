"""One rule for ``from x import *`` across resolve, the class graph and ``re_exports`` (#1010).

#1007 taught ``resolve`` to follow a star re-export: the source's static
``__all__`` when it has one, else every name not starting with ``_``
(:mod:`pyeye.star_exports`). Two other consumers read stars differently:

- the re-export binding index behind ``inspect``'s ``re_exports`` and
  ``expand(re_exports)`` didn't follow stars at all, so
  ``inspect("django.forms.forms.Form").re_exports`` was ``[]`` although
  ``django.forms`` re-exports ``Form`` through ``from django.forms.forms import *``;
- the class graph's base resolution followed every star without checking
  ``__all__`` or the underscore rule.

Both now use the shared rule.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from pyeye import resolver
from pyeye.analyzers.base_resolution import resolve_base
from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.canonicalization import collect_re_exports
from pyeye.handle import Handle
from pyeye.import_analyzer import resolve_relative_import
from pyeye.mcp.operations.expand import expand
from pyeye.mcp.operations.inspect import inspect
from pyeye.mcp.operations.resolve import resolve
from pyeye.star_exports import bound_names, build_star_sources, star_exported_from, static_all


def _write(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


_FILES = {
    "pkg/__init__.py": (
        "from .forms import *\nfrom .fields import *\nfrom .dyn import *\n"
        "from .explicit import Shadow\n"
    ),
    "pkg/forms.py": (
        '__all__ = ("BaseForm", "Form", "Shadow")\n\n\n'
        "class BaseForm:\n    pass\n\n\n"
        "class Form(BaseForm):\n    pass\n\n\n"
        "class Hidden:\n    pass\n\n\n"
        "class Shadow:\n    pass\n"
    ),
    "pkg/fields.py": (
        "from .widgets import *\n\n\nclass CharField:\n    pass\n\n\nclass _Private:\n    pass\n"
    ),
    "pkg/widgets.py": "class TextInput:\n    pass\n",
    "pkg/explicit.py": "class Shadow:\n    pass\n",
    "pkg/dyn.py": (
        "__all__ = [n for n in ('Dyn',)]\n\n\nclass Dyn:\n    pass\n\n\nclass _Quiet:\n    pass\n"
    ),
    # A public plain module star-importing a private one re-exports (#712 rule 3).
    "pkg/api.py": "from ._impl import *\n",
    "pkg/_impl.py": "class Thing:\n    pass\n",
    "cyc/__init__.py": "from .a import *\n",
    "cyc/a.py": "from .b import *\n\n\nclass A:\n    pass\n",
    "cyc/b.py": "from .a import *\n",
}


@pytest.fixture
def analyzer(tmp_path: Path) -> JediAnalyzer:
    return JediAnalyzer(str(_write(tmp_path / "proj", _FILES)))


async def _re_exports(analyzer: JediAnalyzer, handle: str) -> list[str]:
    return [str(h) for h in await collect_re_exports(Handle(handle), analyzer)]


class TestReExportsListStars:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("handle", "expected"),
        [
            ("pkg.forms.Form", ["pkg.Form"]),  # listed in a static __all__
            ("pkg.forms.Hidden", []),  # defined, but not in forms' __all__
            ("pkg.fields.CharField", ["pkg.CharField"]),  # no __all__: a public name
            ("pkg.fields._Private", []),  # no __all__: an underscore name isn't exported
            ("pkg.widgets.TextInput", ["pkg.TextInput"]),  # a star of a star
            ("pkg.dyn.Dyn", ["pkg.Dyn"]),  # a dynamic __all__ falls back to the public rule
            ("pkg.dyn._Quiet", []),
            ("pkg._impl.Thing", ["pkg.api.Thing"]),  # public module, private source
            ("pkg.explicit.Shadow", ["pkg.Shadow"]),
            ("pkg.forms.Shadow", []),  # pkg binds Shadow explicitly; that beats the star
        ],
    )
    async def test_a_star_re_export_is_listed_by_the_shared_rule(
        self, analyzer: JediAnalyzer, handle: str, expected: list[str]
    ) -> None:
        assert await _re_exports(analyzer, handle) == expected

    @pytest.mark.asyncio
    async def test_a_star_cycle_ends(self, analyzer: JediAnalyzer) -> None:
        assert await _re_exports(analyzer, "cyc.a.A") == ["cyc.A"]

    @pytest.mark.asyncio
    async def test_inspect_and_the_edge_report_it(self, analyzer: JediAnalyzer) -> None:
        node = await inspect("pkg.forms.Form", analyzer)
        edge = await expand("pkg.forms.Form", "re_exports", analyzer)

        assert node["re_exports"] == ["pkg.Form"]
        assert [b for s in edge["stubs"] for b in s["bindings"]] == ["pkg.Form"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "handle",
        ["pkg.forms.Form", "pkg.widgets.TextInput", "pkg.dyn.Dyn", "pkg._impl.Thing"],
    )
    async def test_every_listed_spelling_resolves_back(
        self, analyzer: JediAnalyzer, handle: str
    ) -> None:
        """The index and ``resolve`` agree: each star spelling names the definition."""
        for spelling in await _re_exports(analyzer, handle):
            result = await resolve(spelling, analyzer)
            assert result.get("handle") == handle, (spelling, result)


class TestClassGraphHonoursTheRule:
    """``base_resolution`` follows a star only for a name the source star-exports."""

    _TABLES = {"app": {"Thing": "pkg.Thing", "_Thing": "pkg._Thing"}}
    _DEFINES = {"pkg": {}, "pkg.impl": {"Thing": "class", "_Thing": "class"}}
    _STARS = {"pkg": ["pkg.impl"]}

    def test_a_name_outside_a_static_all_is_not_followed(self) -> None:
        alls = {"pkg.impl": frozenset({"Other"})}

        assert resolve_base("app", "Thing", self._TABLES, self._DEFINES, self._STARS, alls) is None

    def test_a_name_in_a_static_all_is_followed(self) -> None:
        alls = {"pkg.impl": frozenset({"Thing", "_Thing"})}

        assert (
            resolve_base("app", "Thing", self._TABLES, self._DEFINES, self._STARS, alls)
            == "pkg.impl.Thing"
        )
        assert (
            resolve_base("app", "_Thing", self._TABLES, self._DEFINES, self._STARS, alls)
            == "pkg.impl._Thing"
        )

    def test_without_all_an_underscore_name_is_not_followed(self) -> None:
        assert resolve_base("app", "_Thing", self._TABLES, self._DEFINES, self._STARS) is None
        assert (
            resolve_base("app", "Thing", self._TABLES, self._DEFINES, self._STARS)
            == "pkg.impl.Thing"
        )

    def test_the_graph_carries_each_modules_static_all(self, analyzer: JediAnalyzer) -> None:
        files = sorted(Path(analyzer.project_path).rglob("*.py"))
        graph = analyzer._build_class_graph(files)

        assert graph.star_alls["pkg.forms"] == frozenset({"BaseForm", "Form", "Shadow"})
        assert "pkg.fields" not in graph.star_alls  # no __all__
        assert "pkg.dyn" not in graph.star_alls  # a dynamic one can't be read

    @pytest.mark.asyncio
    async def test_a_subclass_through_a_star_honours_all(self, tmp_path: Path) -> None:
        """``Sub``'s base is star-exported; ``Odd``'s is not, so the AST doesn't commit to it."""
        root = _write(
            tmp_path / "graph",
            {
                "lib/__init__.py": "from .core import *\n",
                "lib/core.py": (
                    '__all__ = ["Base"]\n\n\nclass Base:\n    pass\n\n\nclass Unlisted:\n    pass\n'
                ),
                "app.py": "import lib\n\n\nclass Sub(lib.Base):\n    pass\n",
            },
        )
        a = JediAnalyzer(str(root))
        graph = a._build_class_graph(sorted(root.rglob("*.py")))

        children = graph.children_by_key.get("lib.core.Base", frozenset())
        # Children are class sites since #1006; name them by their facts.
        assert {graph.classes[site].full_name for site in children} == {"app.Sub"}
        tables, defines, stars, alls = (
            graph.import_tables,
            graph.module_defines,
            graph.star_sources,
            graph.star_alls,
        )
        assert resolve_base("app", "lib.Unlisted", tables, defines, stars, alls) is None


class TestTheSharedHelpers:
    def test_star_exported_from_a_precomputed_all(self) -> None:
        assert star_exported_from(frozenset({"a", "_b"}), "_b")
        assert not star_exported_from(frozenset({"a"}), "c")
        assert star_exported_from(None, "c") and not star_exported_from(None, "_c")

    def test_an_all_with_a_non_string_element_is_dynamic(self) -> None:
        """``__all__ = ["a", NAME]`` can't be read without running the module."""
        assert static_all(ast.parse('__all__ = ["a", NAME]\n')) is None

    def test_build_star_sources_lives_with_the_rule(self) -> None:
        tree = ast.parse("from .a import *\nfrom x.y import *\nfrom z import q\n")

        assert build_star_sources(tree, "pkg", resolve_relative_import, True) == [
            "pkg.a",
            "x.y",
        ]

    def test_bound_names_are_module_scope_bindings(self) -> None:
        tree = ast.parse(
            "import os.path\nimport json as j\nfrom m import a, b as c\nfrom n import *\n"
            "x = y = 1\n(p, [q, *r]) = 1, (2, 3)\nz: int = 3\nw: int\nk += 1\n"
            "class C:\n    inner = 1\n"
            "def f():\n    local = 1\n"
            "async def g():\n    pass\n"
            "if True:\n    from o import guarded\n"
        )

        assert bound_names(tree) == {
            "os", "j", "a", "c", "x", "y", "p", "q", "r", "z", "k", "C", "f", "g", "guarded",
        }  # fmt: skip


class TestResolveStarDefences:
    """``resolver._follow_star``'s defensive branches (#1007's uncovered lines)."""

    def test_the_hop_limit_stops_the_star_walk(self, analyzer: JediAnalyzer) -> None:
        init = Path(analyzer.project_path) / "pkg" / "__init__.py"

        assert (
            resolver._follow_star("pkg", init, ["Form"], analyzer, resolver._MAX_ALIAS_HOPS) is None
        )

    def test_an_unparseable_module_has_no_stars(
        self, analyzer: JediAnalyzer, tmp_path: Path
    ) -> None:
        bad = tmp_path / "bad.py"
        bad.write_text("def (:\n", encoding="utf-8")

        assert resolver._follow_star("bad", bad, ["X"], analyzer, 0) is None

    def test_an_external_or_unparseable_source_is_skipped(self, tmp_path: Path) -> None:
        root = _write(
            tmp_path / "skip",
            {
                "pkg/__init__.py": (
                    "from os.path import *\nfrom .broken import *\nfrom .good import *\n"
                ),
                "pkg/broken.py": "def (:\n",
                "pkg/good.py": "class X:\n    pass\n",
            },
        )
        a = JediAnalyzer(str(root))
        init = root / "pkg" / "__init__.py"

        found = resolver._follow_star("pkg", init, ["X"], a, 0)
        assert found is not None and found[0] == "pkg.good.X"
        assert resolver._follow_star("pkg", init, ["join"], a, 0) is None

"""TypeRef cache keying, bounding and invalidation (#620).

The cache used to be keyed on ``(file, mtime, raw annotation text)``. Head
resolution depends on where the annotation sits, so the first build of a given
text in a file decided the answer for every other site with the same text:

* ``def f(x: Foo)`` at module scope and ``Outer.g(self, x: Foo)`` beside a
  nested ``Outer.Foo`` shared one entry, so ``f``'s parameter type depended on
  which of the two was inspected first;
* the forward ref ``h(x: "Foo")`` has the same unquoted raw text, so it shared
  that entry too.

These tests pin that results are independent of call order, that the project
participates in the key, and that the cache is bounded and invalidatable.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations import typeref
from pyeye.mcp.operations.typeref import (
    _cache_key,
    _typeref_cache,
    build_typeref,
    invalidate_all,
    invalidate_project,
)

_CORE = """\
class Foo:
    pass


def f(x: Foo) -> None: ...


class Outer:
    class Foo:
        pass

    def g(self, x: Foo) -> None: ...


def h(x: "Foo") -> None: ...
"""


@pytest.fixture(autouse=True)
def _clear_cache() -> Iterator[None]:
    _typeref_cache.clear()
    yield
    _typeref_cache.clear()


@pytest.fixture
def project(tmp_path: Path) -> Path:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "core.py").write_text(_CORE)
    return tmp_path


def _functions(tree: ast.Module) -> dict[str, ast.FunctionDef]:
    return {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name in {"f", "g", "h"}
    }


def _param_annotation(fn: ast.FunctionDef) -> ast.expr:
    """The annotation of *fn*'s ``x`` parameter."""
    arg = next(a for a in fn.args.args if a.arg == "x")
    assert arg.annotation is not None
    return arg.annotation


async def _build(project: Path, name: str, analyzer: JediAnalyzer) -> dict[str, Any]:
    core = project / "pkg" / "core.py"
    fn = _functions(ast.parse(core.read_text()))[name]
    return await build_typeref(_param_annotation(fn), core, analyzer)


async def _fresh(project: Path, name: str) -> dict[str, Any]:
    """The TypeRef *name*'s parameter gets with an empty cache."""
    _typeref_cache.clear()
    result = await _build(project, name, JediAnalyzer(str(project)))
    _typeref_cache.clear()
    return result


class TestCallOrderIndependence:
    """The issue's repro: the same raw text at different sites."""

    @pytest.mark.asyncio
    async def test_fresh_results_differ_by_site(self, project: Path) -> None:
        """Sanity: with no cache, f and g resolve to different classes."""
        assert (await _fresh(project, "f")).get("handle") == "pkg.core.Foo"
        assert (await _fresh(project, "g")).get("handle") == "pkg.core.Outer.Foo"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "order",
        [("f", "g", "h"), ("g", "f", "h"), ("g", "h", "f"), ("h", "g", "f")],
    )
    async def test_every_order_matches_a_fresh_build(
        self, project: Path, order: tuple[str, ...]
    ) -> None:
        expected = {name: await _fresh(project, name) for name in order}
        analyzer = JediAnalyzer(str(project))
        for name in order:
            assert await _build(project, name, analyzer) == expected[name], name

    @pytest.mark.asyncio
    async def test_forward_ref_does_not_reuse_the_nested_entry(self, project: Path) -> None:
        """``h(x: "Foo")`` has raw ``Foo`` like ``g``; it must not get g's handle."""
        analyzer = JediAnalyzer(str(project))
        await _build(project, "g", analyzer)
        result = await _build(project, "h", analyzer)
        assert result.get("handle") != "pkg.core.Outer.Foo"
        assert result == await _fresh(project, "h")

    @pytest.mark.asyncio
    async def test_same_scope_rebinding_is_position_sensitive(self, tmp_path: Path) -> None:
        """Why the key holds the position, not just the enclosing scope.

        Within ONE scope, a name can be rebound between two annotations. Both
        annotations are written ``X`` at module scope, but resolve differently.
        """
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "a.py").write_text("class X:\n    pass\n")
        (pkg / "b.py").write_text("class X:\n    pass\n")
        mod = pkg / "m.py"
        mod.write_text(
            "from pkg.a import X\n\n\ndef p(x: X) -> None: ...\n\n\n"
            "from pkg.b import X  # noqa: E402,F811\n\n\ndef q(x: X) -> None: ...\n"
        )
        tree = ast.parse(mod.read_text())
        fns = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
        analyzer = JediAnalyzer(str(tmp_path))
        p = await build_typeref(_param_annotation(fns["p"]), mod, analyzer)
        q = await build_typeref(_param_annotation(fns["q"]), mod, analyzer)
        assert p.get("handle") == "pkg.a.X"
        assert q.get("handle") == "pkg.b.X"


class TestProjectInKey:
    @pytest.mark.asyncio
    async def test_same_file_under_two_projects_is_cached_separately(self, project: Path) -> None:
        """A handle is project-relative; one project's entry can't serve another."""
        outer = JediAnalyzer(str(project))
        inner = JediAnalyzer(str(project / "pkg"))
        await _build(project, "f", outer)
        via_inner = await _build(project, "f", inner)
        assert {k[0] for k in _typeref_cache} == {_root(outer), _root(inner)}

        _typeref_cache.clear()
        assert via_inner == await _build(project, "f", JediAnalyzer(str(project / "pkg")))

    def test_key_holds_project_and_position(self, project: Path) -> None:
        core = project / "pkg" / "core.py"
        fns = _functions(ast.parse(core.read_text()))
        key_f = _cache_key(core, _param_annotation(fns["f"]), "/proj/a")
        key_g = _cache_key(core, _param_annotation(fns["g"]), "/proj/a")
        key_f_other = _cache_key(core, _param_annotation(fns["f"]), "/proj/b")
        assert key_f is not None and key_g is not None and key_f_other is not None
        assert key_f != key_g, "same raw text at different positions must not collide"
        assert key_f != key_f_other, "the project must participate"

    def test_quoted_and_unquoted_text_differ_in_key(self, tmp_path: Path) -> None:
        """Even at one position, ``"Foo"`` and ``Foo`` are different annotations."""
        f = tmp_path / "m.py"
        f.write_text("x: Foo\n")
        bare = ast.parse("x: Foo\n").body[0]
        quoted = ast.parse('x: "Foo"\n').body[0]
        assert isinstance(bare, ast.AnnAssign) and isinstance(quoted, ast.AnnAssign)
        assert _cache_key(f, bare.annotation, "/p") != _cache_key(f, quoted.annotation, "/p")

    def test_positionless_node_is_uncacheable(self, tmp_path: Path) -> None:
        """A synthesised node with no position can't be keyed by site."""
        f = tmp_path / "m.py"
        f.write_text("x: int\n")
        assert _cache_key(f, ast.Name(id="int"), "/p") is None


class TestBoundAndInvalidation:
    @pytest.mark.asyncio
    async def test_cache_is_lru_bounded(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(typeref, "_TYPEREF_CACHE_MAX", 2)
        analyzer = JediAnalyzer(str(project))
        core = project / "pkg" / "core.py"
        fns = _functions(ast.parse(core.read_text()))
        keys = {n: _cache_key(core, _param_annotation(fns[n]), _root(analyzer)) for n in fns}

        await _build(project, "f", analyzer)
        await _build(project, "g", analyzer)
        await _build(project, "f", analyzer)  # touch f: g is now least recent
        await _build(project, "h", analyzer)

        assert len(_typeref_cache) == 2
        assert keys["f"] in _typeref_cache
        assert keys["h"] in _typeref_cache
        assert keys["g"] not in _typeref_cache

    def test_default_bound_is_sensible(self) -> None:
        assert 1_000 <= typeref._TYPEREF_CACHE_MAX <= 100_000

    @pytest.mark.asyncio
    async def test_invalidate_project_drops_only_that_project(self, project: Path) -> None:
        """A referenced type can move without the annotation's file changing.

        The watcher calls ``invalidate_project(root)`` on any change under a
        project, since an edit to one file can change what another file's
        annotations resolve to.
        """
        outer = JediAnalyzer(str(project))
        inner = JediAnalyzer(str(project / "pkg"))
        await _build(project, "f", outer)
        await _build(project, "f", inner)
        assert len(_typeref_cache) == 2

        invalidate_project(project / "pkg")
        assert [k[0] for k in _typeref_cache] == [_root(outer)]

    @pytest.mark.asyncio
    async def test_invalidate_all_clears(self, project: Path) -> None:
        await _build(project, "f", JediAnalyzer(str(project)))
        invalidate_all()
        assert len(_typeref_cache) == 0


def _root(analyzer: JediAnalyzer) -> str:
    return analyzer.project_path.resolve().as_posix()

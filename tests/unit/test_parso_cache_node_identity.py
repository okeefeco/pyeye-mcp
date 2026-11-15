"""A filter only uses parso's cache node when it is the filter's own tree (#783).

Jedi's ``_AbstractUsedNamesFilter`` takes parso's cache entry **by path**. It
uses that node as the key of its definition-name memo and in
``get_cached_parent_scope``, while its ``_used_names`` come from the module's
**own** tree. After #713's LRU evicts a file and a Script under another
project re-parses it, the path names a *new* tree. A Script that is still
cached then reads the new tree's names, rejects them all as unreachable, and
``goto`` answers ``[]``: a silent "unresolved", exactly what #713's bound must
never bring back. #774's CI hit it on 3.13.

The guard (``_parso_cache._install_recovery``) treats a node that belongs to
another parse like an evicted one: the filter computes without its memo, with
an identical answer.
"""

from __future__ import annotations

import importlib
import importlib.util
import inspect as pyinspect
import pkgutil
import re
from pathlib import Path

import jedi
import parso
import parso.cache
import pytest

import pyeye  # noqa: F401  (importing pyeye applies the parso cache policy)
from pyeye import _parso_cache
from pyeye._parso_cache import apply_parso_cache_policy
from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.inspect import inspect
from pyeye.settings import settings

_WIDGETS = "class Widget:\n    pass\n\n\nclass Premium(Widget):\n    pass\n"


def _drop_from_parso(path: Path) -> int:
    """Evict *path*'s entries, as the LRU does."""
    dropped = 0
    for items in parso.cache.parser_cache.values():
        for key in [k for k in items if str(k) == str(path)]:
            del items[key]
            dropped += 1
    return dropped


@pytest.fixture
def project(tmp_path: Path) -> Path:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "widgets.py").write_text(_WIDGETS, encoding="utf-8")
    return tmp_path


async def _reparse_elsewhere_then_inspect(project: Path) -> dict:
    """The #774 sequence: inspect, LRU-evict, re-parse under another project, inspect."""
    widgets = (project / "pkg" / "widgets.py").resolve()
    analyzer = JediAnalyzer(str(project))
    first = await inspect("pkg.widgets.Premium", analyzer)
    assert first["superclasses"] == ["pkg.widgets.Widget"]

    # The LRU evicts widgets.py while the analyzer's Script stays cached...
    assert _drop_from_parso(widgets) >= 1
    # ...and a Script under another project re-parses it and resolves the base,
    # filling the NEW tree's definition-name memo.
    other = jedi.Project(str(project), added_sys_path=[str(project / "elsewhere")])
    script = jedi.Script(code=_WIDGETS, path=widgets, project=other)
    assert [d.full_name for d in script.goto(5, 14, follow_imports=True)] == ["pkg.widgets.Widget"]

    return await inspect("pkg.widgets.Premium", analyzer)


@pytest.mark.asyncio
async def test_a_cached_script_survives_its_file_being_reparsed_elsewhere(project: Path) -> None:
    """With the DEFAULT caps, and no dependence on test order."""
    again = await _reparse_elsewhere_then_inspect(project)
    assert again["superclasses"] == ["pkg.widgets.Widget"]
    assert again["edge_counts"]["superclasses"] == 1


@pytest.mark.asyncio
async def test_red_without_the_guard(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The regression test detects the bug: unwrap the guard and it reproduces."""
    filters = importlib.import_module(_parso_cache._FILTER_MODULE)
    cls = filters._AbstractUsedNamesFilter
    monkeypatch.setattr(cls, "__init__", cls.__init__.__wrapped__)

    again = await _reparse_elsewhere_then_inspect(project)

    assert again["superclasses"] == ["Widget"]  # the silent "unresolved" of #774


def test_the_filter_keeps_its_own_trees_node(tmp_path: Path) -> None:
    path = tmp_path / "own.py"
    path.write_text(_WIDGETS, encoding="utf-8")
    script = jedi.Script(code=_WIDGETS, path=path)
    context = script._get_module_context()
    filters = importlib.import_module(_parso_cache._FILTER_MODULE)

    flt = filters.ParserTreeFilter(context)

    # The attributes the guard reads and writes, on a real filter.
    assert flt._node_context.get_root_context().tree_node is context.tree_node
    node = flt._parso_cache_node
    assert node is not None and node.node is context.tree_node


def test_another_parses_node_is_treated_as_evicted(tmp_path: Path) -> None:
    path = (tmp_path / "foreign.py").resolve()
    path.write_text(_WIDGETS, encoding="utf-8")
    script = jedi.Script(code=_WIDGETS, path=path)
    context = script._get_module_context()
    _drop_from_parso(path)
    jedi.Script(code=_WIDGETS, path=path).get_names()  # a second parse takes the path
    filters = importlib.import_module(_parso_cache._FILTER_MODULE)

    flt = filters.ParserTreeFilter(context)

    assert flt._parso_cache_node is None
    assert [n.string_name for n in flt.get("Widget")] == ["Widget"]


class TestPinnedFilterInternals:
    """What the guard relies on. A Jedi or parso upgrade that moves one fails here."""

    def test_the_filter_init_is_wrapped_once(self) -> None:
        filters = importlib.import_module(_parso_cache._FILTER_MODULE)
        init = filters._AbstractUsedNamesFilter.__init__
        assert _parso_cache._is_marked(init)
        assert not _parso_cache._is_marked(init.__wrapped__)

    def test_the_filter_init_signature_is_unchanged(self) -> None:
        filters = importlib.import_module(_parso_cache._FILTER_MODULE)
        init = filters._AbstractUsedNamesFilter.__init__.__wrapped__
        assert list(pyinspect.signature(init).parameters) == [
            "self",
            "parent_context",
            "node_context",
        ]

    def test_the_cache_node_still_carries_its_tree(self) -> None:
        module = parso.parse("x = 1\n")
        assert parso.cache._NodeCacheItem(module, []).node is module

    def test_only_the_filter_takes_the_node_by_path(self) -> None:
        """Every ``get_parso_cache_node(`` caller in Jedi is one the guard covers.

        ``get_cached_code_lines`` reads only ``.lines``, the same text for any
        parse of an unchanged file, so it needs no identity check.
        """
        callers = set()
        for info in pkgutil.walk_packages(jedi.__path__, "jedi."):
            spec = importlib.util.find_spec(info.name)
            if spec is None or spec.origin is None or not spec.origin.endswith(".py"):
                continue
            source = Path(spec.origin).read_text(encoding="utf-8")
            if re.search(r"(?<!def )get_parso_cache_node\(", source):
                callers.add(info.name)
        assert callers == {"jedi.parser_utils", "jedi.inference.filters"}

    def test_subclasses_reach_the_wrapped_init(self) -> None:
        """No filter subclass looks the node up itself instead of via super()."""
        filters = importlib.import_module(_parso_cache._FILTER_MODULE)
        found = _all_subclasses(filters._AbstractUsedNamesFilter)
        # A floor, so a Jedi import change can't leave this checking nothing.
        assert {cls.__name__ for cls in found} >= _KNOWN_FILTER_SUBCLASSES
        for cls in found:
            if "__init__" in vars(cls):
                assert "super().__init__" in pyinspect.getsource(cls.__init__), cls

    def test_apply_does_not_rewrap(self) -> None:
        filters = importlib.import_module(_parso_cache._FILTER_MODULE)
        init = filters._AbstractUsedNamesFilter.__init__
        apply_parso_cache_policy(settings.parso_cache_max_entries)
        _parso_cache._install_recovery()
        assert filters._AbstractUsedNamesFilter.__init__ is init


#: The filter subclasses at jedi 0.20.1, all of which take the node via super().
_KNOWN_FILTER_SUBCLASSES = frozenset(
    {
        "ParserTreeFilter",
        "ClassFilter",
        "GlobalNameFilter",
        "_FunctionExecutionFilter",
        "FunctionExecutionFilter",
        "AnonymousFunctionExecutionFilter",
        "AnonymousMethodExecutionFilter",
        "SelfAttributeFilter",
        "StubFilter",
        "MixedParserTreeFilter",
        "FixtureFilter",
    }
)


def _all_subclasses(cls: type) -> set[type]:
    importlib.import_module("jedi.inference.value.klass")
    importlib.import_module("jedi.inference.gradual.stub_value")
    importlib.import_module("jedi.api.interpreter")
    out: set[type] = set()
    stack = [cls]
    while stack:
        for sub in stack.pop().__subclasses__():
            if sub not in out:
                out.add(sub)
                stack.append(sub)
    return out

"""A project root reached through a symlink names everything canonically (#714).

macOS's temp dir is ``/var/...``, a symlink to ``/private/var/...``, and any
checkout can sit behind a symlink. The analyzer keeps the caller's spelling of
the root (#603), while Jedi resolves symlinks, so the file → module mapper and
the resolver must compare on resolved paths. Before #714, ``resolve`` returned
``found: true`` with an invented ``__main__.MyClass`` handle, and a src-layout
file was named ``src.mypackage.core``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.config import ProjectConfig
from pyeye.mcp.operations.expand import expand
from pyeye.mcp.operations.inspect import inspect
from pyeye.mcp.operations.outline import outline
from pyeye.mcp.operations.resolve import resolve, resolve_at
from pyeye.project_layout import file_for_module, module_name_for_file

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="creating symlinks needs privileges on Windows"
)

_CORE = "class MyClass:\n    def method(self) -> int:\n        return 1\n\n\ndef my_function() -> int:\n    return 2\n"


@pytest.fixture(params=["config", "no-config"])
def analyzer(request, tmp_path: Path) -> JediAnalyzer:
    real = tmp_path / "real" / "proj"
    pkg = real / "src" / "mypackage"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "core.py").write_text(_CORE, encoding="utf-8")
    (real / "pyproject.toml").write_text(
        '[project]\nname = "mypackage"\nversion = "1"\n\n'
        '[tool.setuptools.packages.find]\nwhere = ["src"]\n',
        encoding="utf-8",
    )
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    config = ProjectConfig(str(link)) if request.param == "config" else None
    return JediAnalyzer(str(link), config=config)


def _link_core(analyzer: JediAnalyzer) -> Path:
    return analyzer.project_path / "src" / "mypackage" / "core.py"


def test_mapper_names_a_link_spelled_file(analyzer: JediAnalyzer) -> None:
    assert module_name_for_file(analyzer, _link_core(analyzer)) == "mypackage.core"


def test_mapper_names_a_resolved_file(analyzer: JediAnalyzer) -> None:
    assert module_name_for_file(analyzer, _link_core(analyzer).resolve()) == "mypackage.core"


def test_module_maps_back_to_its_file(analyzer: JediAnalyzer) -> None:
    found = file_for_module(analyzer, "mypackage.core")
    assert found is not None
    assert found.resolve() == _link_core(analyzer).resolve()


@pytest.mark.asyncio
@pytest.mark.parametrize("symbol", ["MyClass", "my_function", "mypackage.core.MyClass"])
async def test_resolve_names_the_symbol_canonically(analyzer: JediAnalyzer, symbol: str) -> None:
    leaf = symbol.rsplit(".", 1)[-1]

    result = await resolve(symbol, analyzer)

    assert result.get("found") is True, result
    assert result["handle"] == f"mypackage.core.{leaf}", result
    # #603: the location keeps the caller's (link) spelling.
    assert result["location"]["file"] == _link_core(analyzer).as_posix()


@pytest.mark.asyncio
async def test_resolve_at_names_the_symbol_canonically(analyzer: JediAnalyzer) -> None:
    result = await resolve_at(_link_core(analyzer).as_posix(), 1, 6, analyzer)

    assert result.get("found") is True, result
    assert result["handle"] == "mypackage.core.MyClass", result


@pytest.mark.asyncio
async def test_inspect_and_expand_use_canonical_handles(analyzer: JediAnalyzer) -> None:
    node = await inspect("mypackage.core.MyClass", analyzer)
    assert node.get("found") is True, node
    assert node["handle"] == "mypackage.core.MyClass"

    members = await expand("mypackage.core", "members", analyzer)
    handles = sorted(s["handle"] for s in members["stubs"])
    assert handles == ["mypackage.core.MyClass", "mypackage.core.my_function"], members


@pytest.mark.asyncio
async def test_outline_uses_canonical_handles(analyzer: JediAnalyzer) -> None:
    tree = await outline("mypackage.core", analyzer)

    assert tree.get("found") is True, tree
    assert tree["node"]["handle"] == "mypackage.core"
    assert sorted(c["node"]["handle"] for c in tree["children"]) == [
        "mypackage.core.MyClass",
        "mypackage.core.my_function",
    ]


@pytest.mark.asyncio
async def test_the_src_prefixed_path_never_comes_back_as_a_handle(analyzer: JediAnalyzer) -> None:
    node = await inspect("src.mypackage.core.MyClass", analyzer)

    assert node.get("handle") != "src.mypackage.core.MyClass", node
    if node.get("found"):
        assert node["handle"] == "mypackage.core.MyClass", node


@pytest.mark.asyncio
@pytest.mark.parametrize("symbol", ["MyClass", "my_function", "method"])
async def test_no_answer_is_ever_a_main_handle(analyzer: JediAnalyzer, symbol: str) -> None:
    result = await resolve(symbol, analyzer)

    handles = [result.get("handle")] + [c["handle"] for c in result.get("candidates", [])]
    assert not any(h and h.startswith("__main__.") for h in handles), result


# ---------------------------------------------------------------------------
# The pieces: path_utils.relative_within and the resolver's anchor rule
# ---------------------------------------------------------------------------


def test_relative_within_as_spelled_and_resolved(tmp_path: Path) -> None:
    from pyeye.path_utils import relative_within

    real = tmp_path / "real"
    (real / "pkg").mkdir(parents=True)
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)

    assert relative_within(real / "pkg" / "m.py", real) == Path("pkg/m.py")
    assert relative_within(link / "pkg" / "m.py", real) == Path("pkg/m.py")
    assert relative_within(real / "pkg" / "m.py", link) == Path("pkg/m.py")
    assert relative_within(tmp_path / "other" / "m.py", real) is None


def test_relative_within_never_counts_dotdot_as_inside(tmp_path: Path) -> None:
    """#668: ``root/../other/x.py`` is lexically under ``root`` but isn't inside it."""
    from pyeye.path_utils import relative_within

    root = tmp_path / "root"
    root.mkdir()
    (tmp_path / "other").mkdir()

    assert relative_within(root / ".." / "other" / "x.py", root) is None


class _Anchor:
    def __init__(self, full_name: str, module_name: str, module_path: Path | None, kind: str):
        self.full_name = full_name
        self.module_name = module_name
        self.module_path = module_path
        self.type = kind
        self.name = full_name.rsplit(".", 1)[-1]


def test_canonical_of_takes_the_module_from_the_mapper(analyzer: JediAnalyzer) -> None:
    from pyeye.resolver import _canonical_of

    anchor = _Anchor("__main__.MyClass.method", "__main__", _link_core(analyzer), "function")

    assert _canonical_of(anchor, "x", analyzer) == "mypackage.core.MyClass.method"


def test_canonical_of_never_returns_a_main_handle(analyzer: JediAnalyzer, tmp_path: Path) -> None:
    from pyeye.resolver import _canonical_of

    outside = tmp_path / "script-dir" / "tool.py"  # no root names it
    assert (
        _canonical_of(_Anchor("__main__.f", "__main__", outside, "function"), "f", analyzer) is None
    )
    assert _canonical_of(_Anchor("__main__.f", "__main__", None, "function"), "f", analyzer) is None


def test_canonical_of_keeps_external_names(analyzer: JediAnalyzer) -> None:
    from pyeye.resolver import _canonical_of

    anchor = _Anchor("json.decoder.JSONDecoder", "json.decoder", None, "class")
    assert _canonical_of(anchor, "x", analyzer) == "json.decoder.JSONDecoder"

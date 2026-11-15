"""Only public bindings are re-exports (#712, the user's decision on that issue).

A binding of symbol ``S`` at ``M.S`` is a re-export when ``M`` is a package
``__init__``, or ``S`` is in ``M``'s ``__all__``, or ``M`` is a public module
importing ``S`` from a private (``_``-prefixed) module. A plain internal import
between public modules is not: ``imported_by`` already reports those. The walk
still follows every binding, so a public re-export reached through an internal
hop is found.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.canonicalization import collect_re_exports
from pyeye.handle import Handle
from pyeye.mcp.operations.inspect import inspect


def _project(tmp_path: Path, files: dict[str, str]) -> JediAnalyzer:
    for rel, text in files.items():
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
    return JediAnalyzer(str(tmp_path))


async def _reexports(analyzer: JediAnalyzer, handle: str) -> list[str]:
    return [str(h) for h in await collect_re_exports(Handle(handle), analyzer)]


_X = "class X:\n    pass\n"


@pytest.mark.asyncio
async def test_rule_1_a_package_init_reexports(tmp_path: Path) -> None:
    a = _project(tmp_path, {"pkg/__init__.py": "from .core import X\n", "pkg/core.py": _X})
    assert await _reexports(a, "pkg.core.X") == ["pkg.X"]


@pytest.mark.asyncio
async def test_rule_2_an_all_entry_in_a_plain_module_reexports(tmp_path: Path) -> None:
    a = _project(
        tmp_path,
        {
            "pkg/__init__.py": "",
            "pkg/core.py": _X,
            "pkg/api.py": "from .core import X\n\n__all__ = ['X']\n",
        },
    )
    assert await _reexports(a, "pkg.core.X") == ["pkg.api.X"]


@pytest.mark.asyncio
async def test_rule_2_reads_augmented_all(tmp_path: Path) -> None:
    a = _project(
        tmp_path,
        {
            "pkg/__init__.py": "",
            "pkg/core.py": _X,
            "pkg/api.py": "from .core import X\n\n__all__ = []\n__all__ += ['X']\n",
        },
    )
    assert await _reexports(a, "pkg.core.X") == ["pkg.api.X"]


@pytest.mark.asyncio
async def test_rule_3_a_public_facade_over_a_private_module(tmp_path: Path) -> None:
    a = _project(
        tmp_path,
        {"pkg/__init__.py": "", "pkg/_impl.py": _X, "pkg/api.py": "from ._impl import X\n"},
    )
    assert await _reexports(a, "pkg._impl.X") == ["pkg.api.X"]


@pytest.mark.asyncio
async def test_an_aliased_reexport_is_named_by_its_alias(tmp_path: Path) -> None:
    a = _project(
        tmp_path,
        {"pkg/__init__.py": "", "pkg/_impl.py": _X, "pkg/api.py": "from ._impl import X as Y\n"},
    )
    assert await _reexports(a, "pkg._impl.X") == ["pkg.api.Y"]


@pytest.mark.asyncio
async def test_a_plain_internal_import_is_not_a_reexport(tmp_path: Path) -> None:
    """The ``pyeye.handle.Handle`` case: public module importing from public module."""
    a = _project(
        tmp_path,
        {
            "pkg/__init__.py": "",
            "pkg/handle.py": _X,
            "pkg/edges.py": "from pkg.handle import X\n\ndef use() -> X: ...\n",
            "pkg/resolver.py": "from .handle import X\n",
        },
    )
    assert await _reexports(a, "pkg.handle.X") == []


@pytest.mark.asyncio
async def test_a_private_modules_own_bindings_are_not_reexports(tmp_path: Path) -> None:
    a = _project(
        tmp_path,
        {
            "pkg/__init__.py": "",
            "pkg/_impl.py": _X,
            "pkg/_helpers.py": "from ._impl import X\n",
        },
    )
    assert await _reexports(a, "pkg._impl.X") == []


@pytest.mark.asyncio
async def test_a_reexport_reached_through_an_internal_hop_is_found(tmp_path: Path) -> None:
    """X in b; a imports it (internal, not reported); the package re-exports it from a."""
    a = _project(
        tmp_path,
        {
            "pkg/__init__.py": "from .a import X\n",
            "pkg/a.py": "from .b import X\n",
            "pkg/b.py": _X,
        },
    )
    assert await _reexports(a, "pkg.b.X") == ["pkg.X"]


@pytest.mark.asyncio
async def test_an_all_reexport_reached_through_an_internal_hop_is_found(tmp_path: Path) -> None:
    a = _project(
        tmp_path,
        {
            "pkg/__init__.py": "",
            "pkg/api.py": "from .a import X\n\n__all__ = ['X']\n",
            "pkg/a.py": "from .b import X\n",
            "pkg/b.py": _X,
        },
    )
    assert await _reexports(a, "pkg.b.X") == ["pkg.api.X"]


@pytest.mark.asyncio
async def test_inspect_reports_only_public_reexports(tmp_path: Path) -> None:
    a = _project(
        tmp_path,
        {
            "pkg/__init__.py": "from .handle import X\n",
            "pkg/handle.py": _X,
            "pkg/edges.py": "from pkg.handle import X\n",
        },
    )
    node = await inspect("pkg.handle.X", a)
    assert node["re_exports"] == ["pkg.X"]


@pytest.mark.asyncio
async def test_this_repos_handle_has_no_internal_import_reexports() -> None:
    """Regression: the six internal ``from pyeye.handle import Handle`` entries drop."""
    a = JediAnalyzer(str(Path(__file__).resolve().parents[1]))
    found = await _reexports(a, "pyeye.handle.Handle")
    assert not [
        h for h in found if h.startswith(("pyeye.mcp.", "pyeye.resolver", "pyeye.canon"))
    ], found

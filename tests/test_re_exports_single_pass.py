"""The re-export scan parses each package file once, however many hops it walks (#795).

``_collect_re_exports_impl`` used to call ``_scan_package_for_handle`` once per
BFS hop, and each call parsed every file under the package. A symbol bound in
many modules (``django.apps.apps``: ~66 binding modules x 907 files) cost tens
of thousands of parses for one ``inspect``. The scan now builds one import
index per call and walks it in memory, so the output is unchanged and the
parse count is the file count.
"""

from __future__ import annotations

from collections import deque
from pathlib import Path
from unittest.mock import patch

import pytest

from pyeye import canonicalization, file_artifact_cache
from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.canonicalization import (
    _collect_re_exports_impl,
    _scan_package_for_handle,
    re_export_scan,
)
from pyeye.handle import Handle
from pyeye.path_utils import path_to_key

_FIXTURES = Path(__file__).parent / "fixtures"

#: Modules that each bind ``pkg.core.X``: every one is a BFS hop.
_N_BINDERS = 12


def _project(tmp_path: Path, files: dict[str, str]) -> JediAnalyzer:
    for rel, text in files.items():
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
    return JediAnalyzer(str(tmp_path))


def _wide_project(tmp_path: Path) -> JediAnalyzer:
    """A package where ``X`` is bound by many modules, some of them chained."""
    files = {
        "pkg/__init__.py": "from .core import X\n",
        "pkg/core.py": "class X:\n    pass\n",
        "pkg/_hub.py": "from .core import X\n",
        "pkg/api.py": "from ._hub import X\n",
    }
    for i in range(_N_BINDERS):
        files[f"pkg/mod{i}.py"] = "from pkg.core import X\n"
        files[f"pkg/sub/use{i}.py"] = f"from pkg.mod{i} import X as Y{i}\n"
    files["pkg/sub/__init__.py"] = "from pkg import X\n"
    return _project(tmp_path, files)


async def _per_hop_reference(handle: str, analyzer: JediAnalyzer) -> list[str]:
    """The pre-#795 walk: one full package scan per hop (the output oracle)."""
    top = canonicalization.find_module_file(handle.split(".")[0], analyzer)
    assert top is not None
    visited, result, queue = {handle}, [], deque([handle])
    while queue:
        for h, public in await _scan_package_for_handle(queue.popleft(), top.parent, analyzer):
            if h not in visited:
                visited.add(h)
                if public:
                    result.append(h)
                queue.append(h)
    return sorted(result)


class _ParseCounter:
    """Wrap ``file_artifact_cache.get_ast`` and count calls per file."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self._real = file_artifact_cache.get_ast

    def __call__(self, path: Path | str):  # type: ignore[no-untyped-def]
        self.calls.append(Path(path).as_posix())
        return self._real(path)


@pytest.mark.asyncio
async def test_scan_parses_each_file_once(tmp_path: Path) -> None:
    """One scan reads each file's AST exactly once, though it walks many hops."""
    analyzer = _wide_project(tmp_path)
    n_files = len(list((tmp_path / "pkg").rglob("*.py")))
    counter = _ParseCounter()

    with patch.object(file_artifact_cache, "get_ast", counter):
        paths = await _collect_re_exports_impl(Handle("pkg.core.X"), analyzer)

    # The walk really is many hops deep (otherwise the count proves nothing).
    hops = await _per_hop_reference("pkg.core.X", analyzer)
    assert len(hops) >= 3
    assert len(counter.calls) == n_files
    assert len(set(counter.calls)) == n_files
    assert [str(p) for p in paths] == hops


@pytest.mark.asyncio
async def test_wide_package_output_matches_the_per_hop_walk(tmp_path: Path) -> None:
    """The single-pass walk reports exactly what the per-hop walk did."""
    analyzer = _wide_project(tmp_path)
    got = [str(p) for p in await _collect_re_exports_impl(Handle("pkg.core.X"), analyzer)]
    assert got == await _per_hop_reference("pkg.core.X", analyzer)
    # Public bindings only (#712): the package inits, and api (a facade over _hub).
    assert got == ["pkg.X", "pkg.api.X", "pkg.sub.X"]


@pytest.mark.parametrize(
    ("fixture", "handle"),
    [
        ("canonicalization_basic", "package._impl.config.Config"),
        ("canonicalization_multihop", "package._impl.config.Config"),
        ("canonicalization_multihop", "alias_pkg.source_mod.definitions.foo"),
        ("canonicalization_multihop", "self_reexport_pkg.submodule.Foo"),
    ],
)
@pytest.mark.asyncio
async def test_fixture_output_matches_the_per_hop_walk(fixture: str, handle: str) -> None:
    """On the existing re-export fixtures, the result is unchanged."""
    root = _FIXTURES / fixture
    analyzer = JediAnalyzer(str(root))
    got = [str(p) for p in await _collect_re_exports_impl(Handle(handle), analyzer)]
    assert got  # each fixture has at least one re-export, so equality is meaningful
    assert got == await _per_hop_reference(handle, analyzer)


@pytest.mark.asyncio
async def test_unparseable_file_is_listed_once_and_the_rest_kept(tmp_path: Path) -> None:
    """A file that doesn't parse is recorded once per scan and the others still count."""
    analyzer = _project(
        tmp_path,
        {
            "pkg/__init__.py": "from .core import X\n",
            "pkg/core.py": "class X:\n    pass\n",
            "pkg/mid.py": "from .core import X\n",
            "pkg/api.py": "from .mid import X\n\n__all__ = ['X']\n",
            "pkg/broken.py": "def (:\n",
        },
    )
    scan = await re_export_scan(Handle("pkg.core.X"), analyzer)
    assert scan.paths == ("pkg.X", "pkg.api.X")
    assert scan.unparseable_files == (path_to_key(tmp_path / "pkg" / "broken.py"),)

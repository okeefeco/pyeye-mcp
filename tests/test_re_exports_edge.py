"""``expand(handle, "re_exports")``: the public modules that re-export a symbol (#393).

One stub per re-exporting MODULE (a re-export path is an alias of the symbol,
not another handle), with ``bindings`` listing the public paths that module
provides. "Public" is #712's definition, shared with ``inspect``'s deprecated
``re_exports`` field through one cached scan. Unparseable package files are
listed in ``unparseable_files`` (#729 shape) and the rest is still reported.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from pyeye import canonicalization
from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.expand import expand
from pyeye.mcp.operations.inspect import inspect
from pyeye.mcp.operations.trace import trace

_X = "class X:\n    pass\n"


def _project(tmp_path: Path, files: dict[str, str]) -> JediAnalyzer:
    for rel, text in files.items():
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
    return JediAnalyzer(str(tmp_path))


_PKG = {
    "pkg/__init__.py": "from ._impl import X\n",
    "pkg/_impl.py": _X,
    "pkg/api.py": "from ._impl import X, X as Y\n",
    "pkg/_internal.py": "from pkg._impl import X\n",
}


@pytest.mark.asyncio
async def test_one_module_stub_per_reexporter_with_its_bindings(tmp_path: Path) -> None:
    a = _project(tmp_path, _PKG)

    result = await expand("pkg._impl.X", "re_exports", a)

    assert result["found"] is True and "unsupported" not in result, result
    stubs = {s["handle"]: s for s in result["stubs"]}
    assert set(stubs) == {"pkg", "pkg.api"}
    assert all(s["kind"] == "module" for s in stubs.values())
    assert stubs["pkg"]["bindings"] == ["pkg.X"]
    assert stubs["pkg.api"]["bindings"] == ["pkg.api.X", "pkg.api.Y"]
    assert result["unparseable_files"] == []
    assert result["ceiling"] == "package_reexports"  # #417


@pytest.mark.asyncio
async def test_the_edge_and_the_deprecated_field_agree(tmp_path: Path) -> None:
    a = _project(tmp_path, _PKG)

    edge = await expand("pkg._impl.X", "re_exports", a)
    node = await inspect("pkg._impl.X", a)

    bindings = sorted(b for s in edge["stubs"] for b in s["bindings"])
    assert bindings == sorted(node["re_exports"])


@pytest.mark.asyncio
async def test_none_found_is_a_measured_empty(tmp_path: Path) -> None:
    a = _project(tmp_path, {"pkg/__init__.py": "", "pkg/core.py": _X})

    result = await expand("pkg.core.X", "re_exports", a)

    assert result["stubs"] == [] and result["unparseable_files"] == []


@pytest.mark.asyncio
async def test_a_module_handle_is_not_applicable(tmp_path: Path) -> None:
    a = _project(tmp_path, _PKG)

    result = await expand("pkg.api", "re_exports", a)

    assert result.get("unsupported") is True and result["reason"] == "not_applicable"
    assert "unparseable_files" not in result


@pytest.mark.asyncio
async def test_an_unparseable_file_is_listed_and_the_rest_still_reported(tmp_path: Path) -> None:
    files = {**_PKG, "pkg/broken.py": "def broken(:\n    pass\n"}
    a = _project(tmp_path, files)

    result = await expand("pkg._impl.X", "re_exports", a)
    node = await inspect("pkg._impl.X", a)

    assert {s["handle"] for s in result["stubs"]} == {"pkg", "pkg.api"}
    assert [Path(f).name for f in result["unparseable_files"]] == ["broken.py"]
    assert all("\\\\" not in f and Path(f).is_absolute() for f in result["unparseable_files"])
    # The deprecated field can't say "incomplete", so it stays absent (#704).
    assert "re_exports" not in node


@pytest.mark.asyncio
async def test_trace_stops_after_one_hop_and_carries_the_loss_map(tmp_path: Path) -> None:
    a = _project(tmp_path, {**_PKG, "pkg/broken.py": "def broken(:\n"})

    graph = await trace("pkg._impl.X", ["re_exports"], a, max_depth=3)

    assert set(graph["nodes"]) == {"pkg._impl.X", "pkg", "pkg.api"}
    assert graph["nodes"]["pkg"]["bindings"] == ["pkg.X"]
    # The reached modules are not walked further: the edge doesn't apply to them.
    assert {e["from"] for e in graph["edges"]} == {"pkg._impl.X"}
    assert "unparseable_files" in graph
    assert [Path(f).name for f in graph["unparseable_files"]["pkg._impl.X"]] == ["broken.py"]


@pytest.mark.asyncio
async def test_re_exports_is_not_in_edge_counts(tmp_path: Path) -> None:
    a = _project(tmp_path, _PKG)

    node = await inspect("pkg._impl.X", a)

    assert "re_exports" not in node["edge_counts"]


@pytest.mark.asyncio
async def test_a_repeat_call_reads_the_cache(tmp_path: Path) -> None:
    a = _project(tmp_path, _PKG)
    real = canonicalization._collect_re_exports_impl
    calls = []

    async def counting(*args, **kwargs):
        calls.append(args[0])
        return await real(*args, **kwargs)

    with patch.object(canonicalization, "_collect_re_exports_impl", counting):
        await expand("pkg._impl.X", "re_exports", a)
        await inspect("pkg._impl.X", a)
        await expand("pkg._impl.X", "re_exports", a)

    assert len(calls) == 1


@pytest.mark.asyncio
async def test_the_watcher_drops_the_projects_cached_scans(tmp_path: Path) -> None:
    from pyeye.project_manager import ProjectManager

    _project(tmp_path, _PKG)
    manager = ProjectManager()
    a = manager.get_analyzer(str(tmp_path))
    first = await expand("pkg._impl.X", "re_exports", a)
    assert {s["handle"] for s in first["stubs"]} == {"pkg", "pkg.api"}

    (tmp_path / "pkg" / "facade.py").write_text("from ._impl import X\n", encoding="utf-8")
    manager._on_files_changed(tmp_path.resolve(), [str(tmp_path / "pkg" / "facade.py")])

    second = await expand("pkg._impl.X", "re_exports", a)
    assert {s["handle"] for s in second["stubs"]} == {"pkg", "pkg.api", "pkg.facade"}
    manager.cleanup_all()


def test_invalidate_re_exports_clears_one_project_or_all(tmp_path: Path) -> None:
    key = (tmp_path.resolve().as_posix(), "layout", "pkg.X")
    other = ("/elsewhere", "layout", "pkg.X")
    scan = canonicalization.ReExportScan(paths=(), unparseable_files=())
    with canonicalization._re_export_lock:
        canonicalization._re_export_cache[key] = scan
        canonicalization._re_export_cache[other] = scan

    canonicalization.invalidate_re_exports(tmp_path)
    assert key not in canonicalization._re_export_cache
    assert other in canonicalization._re_export_cache

    canonicalization.invalidate_re_exports()
    assert not canonicalization._re_export_cache

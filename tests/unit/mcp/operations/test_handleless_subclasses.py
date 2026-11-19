"""Subclasses with no handle are reported, never dropped (#1006, option A).

A class defined in a function, in a file with no importable module path, or
under a name the ASCII-only handle grammar rejects is a real subclass, but no
stub can name it. ``expand(…, "subclasses")`` reports them:

- ``handleless_subclass_count``: always present on the edge, always complete;
- ``handleless_subclasses``: ``[{name, file, line, reason}]``, sorted by file
  then line, capped by ``max_stubs`` as its own budget, so a cut list shows as
  ``count > len(list)``.

``trace`` following ``subclasses`` carries ``handleless_subclass_counts``, a
``{handle: count}`` map of the nodes that have any.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pyeye.analyzers import project_graph
from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.expand import expand
from pyeye.mcp.operations.trace import trace
from pyeye.path_utils import respell_paths

BASE = "app.base.Base"
IMPORT = "from app.base import Base\n"


@pytest.fixture(autouse=True)
def _fresh_graph_store() -> Any:
    project_graph.invalidate()
    yield
    project_graph.invalidate()


def _project(root: Path, files: dict[str, str]) -> JediAnalyzer:
    files = {"app/__init__.py": "", "app/base.py": "class Base:\n    pass\n", **files}
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return JediAnalyzer(root.as_posix())


def _local(name: str, fn: str) -> str:
    return f"def {fn}():\n    class {name}(Base):\n        pass\n"


def _rel(entries: list[dict[str, Any]], root: Path) -> list[tuple[str, str, int, str]]:
    return [
        (e["name"], Path(e["file"]).relative_to(root).as_posix(), e["line"], e["reason"])
        for e in entries
    ]


MIXED = {
    "app/m.py": IMPORT + "\nclass Named(Base):\n    pass\n\n" + _local("Local", "f"),
    "app/u.py": IMPORT + "\nclass Héllo(Base):\n    pass\n",
    "app/migrations/__init__.py": "",
    "app/migrations/0001_initial.py": IMPORT + "\nclass Migration(Base):\n    pass\n",
}


class TestExpandReportsHandlelessSubclasses:
    @pytest.mark.asyncio
    async def test_each_kind_is_listed_with_its_reason_sorted_by_file_then_line(
        self, tmp_path: Path
    ) -> None:
        result = await expand(BASE, "subclasses", _project(tmp_path, MIXED), max_stubs=None)

        assert [s["handle"] for s in result["stubs"]] == ["app.m.Named"]
        assert result["handleless_subclass_count"] == 3
        assert _rel(result["handleless_subclasses"], tmp_path) == [
            ("Local", "app/m.py", 7, "function_local"),
            ("Migration", "app/migrations/0001_initial.py", 3, "no_module_path"),
            ("Héllo", "app/u.py", 3, "not_a_handle"),
        ]

    @pytest.mark.asyncio
    async def test_none_handleless_is_a_measured_zero(self, tmp_path: Path) -> None:
        analyzer = _project(tmp_path, {"app/m.py": IMPORT + "\nclass Named(Base):\n    pass\n"})

        result = await expand(BASE, "subclasses", analyzer)

        assert result["handleless_subclass_count"] == 0
        assert result["handleless_subclasses"] == []

    @pytest.mark.asyncio
    async def test_other_edges_never_carry_the_keys(self, tmp_path: Path) -> None:
        analyzer = _project(tmp_path, MIXED)

        for edge in ("superclasses", "members"):
            result = await expand(BASE, edge, analyzer)
            assert "handleless_subclass_count" not in result, edge
            assert "handleless_subclasses" not in result, edge

    @pytest.mark.asyncio
    async def test_the_list_is_capped_by_max_stubs_on_its_own_budget(self, tmp_path: Path) -> None:
        """Three handleless, cap 2: the count stays complete, the stubs aren't truncated."""
        analyzer = _project(
            tmp_path,
            {"app/m.py": IMPORT + "\n" + _local("A", "f") + _local("B", "g") + _local("C", "h")},
        )

        result = await expand(BASE, "subclasses", analyzer, max_stubs=2)

        assert result["handleless_subclass_count"] == 3
        assert [e["name"] for e in result["handleless_subclasses"]] == ["A", "B"]
        assert result["stubs"] == [] and "truncated" not in result

    @pytest.mark.asyncio
    async def test_no_cap_lists_every_one(self, tmp_path: Path) -> None:
        analyzer = _project(
            tmp_path,
            {"app/m.py": IMPORT + "\n" + "".join(_local(f"L{i}", f"f{i}") for i in range(5))},
        )

        result = await expand(BASE, "subclasses", analyzer, max_stubs=None)

        assert result["handleless_subclass_count"] == len(result["handleless_subclasses"]) == 5


class TestTraceCarriesPerNodeCounts:
    @pytest.mark.asyncio
    async def test_nodes_with_handleless_subclasses_are_counted(self, tmp_path: Path) -> None:
        analyzer = _project(
            tmp_path,
            {
                "app/m.py": IMPORT
                + "\nclass Named(Base):\n    pass\n\n"
                + _local("L1", "f")
                + _local("L2", "g")
                + "\ndef h():\n    class Deep(Named):\n        pass\n",
            },
        )

        result = await trace(BASE, ["subclasses"], analyzer, max_depth=5, max_nodes=50)

        assert result["handleless_subclass_counts"] == {BASE: 2, "app.m.Named": 1}

    @pytest.mark.asyncio
    async def test_the_map_is_empty_when_subclasses_were_walked_and_all_named(
        self, tmp_path: Path
    ) -> None:
        analyzer = _project(tmp_path, {"app/m.py": IMPORT + "\nclass Named(Base):\n    pass\n"})

        result = await trace(BASE, ["subclasses"], analyzer)

        assert result["handleless_subclass_counts"] == {}

    @pytest.mark.asyncio
    async def test_the_map_is_absent_when_subclasses_were_not_walked(self, tmp_path: Path) -> None:
        result = await trace(BASE, ["superclasses"], _project(tmp_path, MIXED))

        assert "handleless_subclass_counts" not in result


def test_each_entry_file_is_respelled_in_the_callers_spelling(tmp_path: Path) -> None:
    """The entries' ``file`` is a ``file`` key, so it's respelled like a stub's (#717)."""
    real = tmp_path / "real"
    (real / "app").mkdir(parents=True)
    link = tmp_path / "link"
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable")
    entry = {"name": "L", "file": (real / "app" / "m.py").as_posix(), "line": 3}

    out = respell_paths({"handleless_subclasses": [entry]}, [link])

    assert out["handleless_subclasses"][0]["file"] == (link / "app" / "m.py").as_posix()

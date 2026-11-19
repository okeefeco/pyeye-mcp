"""The class graph keys classes by definition site, not dotted name (#1006).

``_class_inventory`` keyed every class ``f"{module}.{name}"`` in a dict, so:

- a class nested in a function or a class overwrote a same-named class in the
  same module, and was given that module-level class's handle;
- every file with no importable module path (``migrations/0001_initial.py``)
  fell back to its stem, so same-named classes in different apps collapsed.

On django that hid 23-64% of the direct subclasses of ``Model``, ``Form``,
``ModelAdmin`` and ``Migration``. Each literal ``class B(A):`` is now one entry,
named by its real dotted name, or by none when it has no handle (defined in a
function, in a file with no module path, or under a name the ASCII-only handle
grammar rejects). An unnamed class is never given a false handle.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pyeye.analyzers import project_graph
from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.expand import expand

BASE = "app.base.Base"


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


async def _entries(analyzer: JediAnalyzer) -> list[dict[str, Any]]:
    result = await analyzer.find_subclasses(BASE)
    return sorted(result["subclasses"], key=lambda e: (e["file"], e["line"]))


def _sites(entries: list[dict[str, Any]], root: Path) -> list[tuple[str, int, Any, Any]]:
    return [
        (
            Path(e["file"]).relative_to(root).as_posix(),
            e["line"],
            e["full_name"],
            e.get("unnamed_reason"),
        )
        for e in entries
    ]


async def _stub_handles(analyzer: JediAnalyzer) -> list[tuple[str, int]]:
    result = await expand(BASE, "subclasses", analyzer, max_stubs=None)
    assert result["found"] is True, result
    return sorted((s["handle"], s["line_start"]) for s in result["stubs"])


NESTED = (
    "from app.base import Base\n"  # 1
    "\n"  # 2
    "class Foo(Base):\n"  # 3   app.m.Foo
    "    pass\n"
    "\n"
    "class Outer:\n"  # 6
    "    class Foo(Base):\n"  # 7   app.m.Outer.Foo
    "        pass\n"
    "\n"
    "def f():\n"  # 10
    "    class Foo(Base):\n"  # 11  function-local
    "        pass\n"
    "\n"
    "def g():\n"  # 14
    "    class Foo(Base):\n"  # 15  function-local
    "        pass\n"
)


class TestNestedSameNameClasses:
    @pytest.mark.asyncio
    async def test_every_definition_is_one_entry(self, tmp_path: Path) -> None:
        analyzer = _project(tmp_path, {"app/m.py": NESTED})

        assert _sites(await _entries(analyzer), tmp_path) == [
            ("app/m.py", 3, "app.m.Foo", None),
            ("app/m.py", 7, "app.m.Outer.Foo", None),
            ("app/m.py", 11, None, "function_local"),
            ("app/m.py", 15, None, "function_local"),
        ]

    @pytest.mark.asyncio
    async def test_a_class_in_a_class_gets_its_real_dotted_name(self, tmp_path: Path) -> None:
        analyzer = _project(tmp_path, {"app/m.py": NESTED})

        assert ("app.m.Outer.Foo", 7) in await _stub_handles(analyzer)

    @pytest.mark.asyncio
    async def test_a_function_local_class_is_never_given_a_module_level_handle(
        self, tmp_path: Path
    ) -> None:
        """The false answer #1006 removes: ``app.m.Foo`` pointing at a class in ``f``."""
        analyzer = _project(tmp_path, {"app/m.py": NESTED})

        assert await _stub_handles(analyzer) == [("app.m.Foo", 3), ("app.m.Outer.Foo", 7)]

    @pytest.mark.asyncio
    async def test_a_lone_function_local_class_gets_no_handle(self, tmp_path: Path) -> None:
        """No module-level ``Foo`` exists, so the old key was a handle that resolves nowhere."""
        analyzer = _project(
            tmp_path,
            {
                "app/m.py": "from app.base import Base\n\ndef f():\n    class Foo(Base):\n        pass\n"
            },
        )

        assert _sites(await _entries(analyzer), tmp_path) == [
            ("app/m.py", 4, None, "function_local")
        ]
        assert await _stub_handles(analyzer) == []


MIGRATION = "from app.base import Base\n\nclass Migration(Base):\n    pass\n"


class TestFilesWithNoModulePath:
    @pytest.mark.asyncio
    async def test_same_named_classes_in_two_non_identifier_files_are_two_entries(
        self, tmp_path: Path
    ) -> None:
        analyzer = _project(
            tmp_path,
            {
                "app/migrations/__init__.py": "",
                "app/migrations/0001_initial.py": MIGRATION,
                "other/__init__.py": "",
                "other/migrations/__init__.py": "",
                "other/migrations/0001_initial.py": MIGRATION,
            },
        )

        assert _sites(await _entries(analyzer), tmp_path) == [
            ("app/migrations/0001_initial.py", 3, None, "no_module_path"),
            ("other/migrations/0001_initial.py", 3, None, "no_module_path"),
        ]

    @pytest.mark.asyncio
    async def test_no_stem_based_handle_is_emitted(self, tmp_path: Path) -> None:
        """``0001_initial.Migration`` was never a handle: it's not a module path."""
        analyzer = _project(
            tmp_path,
            {"app/migrations/__init__.py": "", "app/migrations/0001_initial.py": MIGRATION},
        )

        assert await _stub_handles(analyzer) == []


class TestNamesTheHandleGrammarRejects:
    @pytest.mark.asyncio
    async def test_a_non_ascii_class_is_one_entry_with_no_handle(self, tmp_path: Path) -> None:
        """Handles are ASCII identifiers (symbol_parser), so ``Héllo`` can't be one."""
        analyzer = _project(
            tmp_path,
            {"app/u.py": "from app.base import Base\n\nclass Héllo(Base):\n    pass\n"},
        )

        assert _sites(await _entries(analyzer), tmp_path) == [("app/u.py", 3, None, "not_a_handle")]
        assert await _stub_handles(analyzer) == []


class TestTheGraphCountsEveryDefinition:
    @pytest.mark.asyncio
    async def test_graph_direct_children_match_the_literal_class_headers(
        self, tmp_path: Path
    ) -> None:
        """Four in ``m.py``, two migrations, one non-ASCII: seven ``class X(Base)``."""
        analyzer = _project(
            tmp_path,
            {
                "app/m.py": NESTED,
                "app/u.py": "from app.base import Base\n\nclass Héllo(Base):\n    pass\n",
                "app/migrations/__init__.py": "",
                "app/migrations/0001_initial.py": MIGRATION,
                "other/__init__.py": "",
                "other/migrations/__init__.py": "",
                "other/migrations/0001_initial.py": MIGRATION,
            },
        )

        assert len(await _entries(analyzer)) == 7

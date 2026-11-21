"""TYPE_CHECKING-only imports are marked ``type_only: true`` (#1081, shape ruled 2026-11-22).

An import reachable only under a ``TYPE_CHECKING`` guard is a type-checking
dependency, not a runtime one. Layering checks built on ``imports`` reported
them as runtime violations, so:

- ``expand(module, "imports")`` stubs carry ``type_only: true`` for such a
  target. It's absent otherwise, the absent-not-false convention of outline's
  ``truncated`` (O.2): it's always measured, so absence is a measured "no";
- ``trace(follow=["imports"])`` carries it on the EDGE, ``{from, to, kind:
  "imports", type_only: true}``, never on the node. Nodes are deduped by handle,
  and one module can be imported type-only by one module and at runtime by
  another, so the flag belongs to the import, not to the module (refines the
  issue's "same for trace stubs");
- a target imported both ways is not type-only: any runtime import wins.

Computed in #360's one module-scope walk
(:func:`pyeye._module_scope.iter_module_scope_imports_guarded`).
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

from pyeye._module_scope import iter_module_scope_imports, iter_module_scope_imports_guarded
from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.expand import expand
from pyeye.mcp.operations.trace import trace

#: The issue's acceptance fixture: runtime, type-only and both-ways imports of three targets.
ACCEPTANCE = """from __future__ import annotations

from typing import TYPE_CHECKING

from pkg import runtime_mod, both_mod

if TYPE_CHECKING:
    from pkg import typed_mod, both_mod
"""


def _guards(source: str) -> dict[str, bool]:
    """``{imported name: type_only}`` for each module-scope import in *source*."""
    out: dict[str, bool] = {}
    for node, type_only in iter_module_scope_imports_guarded(ast.parse(source)):
        for alias in node.names:
            out[alias.asname or alias.name] = type_only
    return out


class TestTheGuardedWalk:
    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            ("if TYPE_CHECKING:\n    import a\n", {"a": True}),
            (
                "import typing\nif typing.TYPE_CHECKING:\n    import a\n",
                {"typing": False, "a": True},
            ),
            ("import typing as t\nif t.TYPE_CHECKING:\n    import a\n", {"t": False, "a": True}),
            (
                "from typing import TYPE_CHECKING as TC\nif TC:\n    import a\n",
                {"TC": False, "a": True},
            ),
            (
                "import typing_extensions\nif typing_extensions.TYPE_CHECKING:\n    import a\n",
                {"typing_extensions": False, "a": True},
            ),
            ("if TYPE_CHECKING:\n    import a\nelse:\n    import b\n", {"a": True, "b": False}),
            ("if not TYPE_CHECKING:\n    import a\nelse:\n    import b\n", {"a": False, "b": True}),
            (
                "if TYPE_CHECKING:\n    if sys.version_info >= (3, 11):\n        import a\n",
                {"a": True},
            ),
            (
                "if TYPE_CHECKING:\n    try:\n        import a\n    except ImportError:\n        import b\n",
                {"a": True, "b": True},
            ),
            ("if sys.version_info >= (3, 11):\n    import a\n", {"a": False}),
            ("if X:\n    pass\nelif TYPE_CHECKING:\n    import a\n", {"a": True}),
            ("import a\n", {"a": False}),
        ],
        ids=[
            "bare",
            "typing.attr",
            "typing alias",
            "imported alias",
            "typing_extensions",
            "else is runtime",
            "not reverses",
            "nested if",
            "try inside",
            "other guard",
            "elif",
            "unguarded",
        ],
    )
    def test_type_only(self, source: str, expected: dict[str, bool]) -> None:
        assert _guards(source) == expected

    def test_the_plain_walk_is_the_same_walk(self) -> None:
        """members and imports still share #360's walk: same nodes, same order."""
        tree = ast.parse(ACCEPTANCE)

        assert list(iter_module_scope_imports(tree)) == [
            n for n, _ in iter_module_scope_imports_guarded(tree)
        ]


@pytest.fixture
def analyzer(tmp_path: Path) -> JediAnalyzer:
    files = {
        "pkg/__init__.py": "",
        "pkg/runtime_mod.py": "X = 1\n",
        "pkg/typed_mod.py": "X = 1\n",
        "pkg/both_mod.py": "X = 1\n",
        "pkg/importer.py": ACCEPTANCE,
        # A second importer of typed_mod, at runtime: the trace node is shared.
        "pkg/runtime_user.py": "from pkg import typed_mod\n",
        "pkg/both_users.py": "from pkg import importer, runtime_user\n",
    }
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text, encoding="utf-8")
    return JediAnalyzer(tmp_path.as_posix())


class TestExpand:
    @pytest.mark.asyncio
    async def test_only_the_type_only_target_is_marked(self, analyzer: JediAnalyzer) -> None:
        result: dict[str, Any] = dict(await expand("pkg.importer", "imports", analyzer))

        flags = {s["handle"]: s.get("type_only") for s in result["stubs"]}
        assert flags["pkg.typed_mod"] is True
        assert "type_only" not in next(s for s in result["stubs"] if s["handle"] == "pkg.both_mod")
        assert "type_only" not in next(
            s for s in result["stubs"] if s["handle"] == "pkg.runtime_mod"
        )
        assert [h for h, v in flags.items() if v] == ["pkg.typed_mod"]

    @pytest.mark.asyncio
    async def test_never_false(self, analyzer: JediAnalyzer) -> None:
        result: dict[str, Any] = dict(await expand("pkg.importer", "imports", analyzer))

        assert all(s.get("type_only", True) is True for s in result["stubs"])

    @pytest.mark.asyncio
    @pytest.mark.parametrize("edge", ["members", "imported_by", "submodules"])
    async def test_no_other_edge_carries_it(self, analyzer: JediAnalyzer, edge: str) -> None:
        source = "pkg" if edge == "submodules" else "pkg.typed_mod"
        result: dict[str, Any] = dict(await expand(source, edge, analyzer))

        assert all("type_only" not in s for s in result.get("stubs", []))


class TestTrace:
    @pytest.mark.asyncio
    async def test_on_the_edge_not_the_node(self, analyzer: JediAnalyzer) -> None:
        result: dict[str, Any] = dict(
            await trace("pkg.both_users", ["imports"], analyzer, max_depth=2, max_nodes=50)
        )

        edges = {(e["from"], e["to"]): e.get("type_only") for e in result["edges"]}
        assert edges[("pkg.importer", "pkg.typed_mod")] is True
        assert ("pkg.runtime_user", "pkg.typed_mod") in edges
        assert edges[("pkg.runtime_user", "pkg.typed_mod")] is None  # absent: runtime
        assert edges[("pkg.importer", "pkg.both_mod")] is None
        assert all("type_only" not in node for node in result["nodes"].values())
        assert all("type_only" not in e for e in result["edges"] if e["kind"] != "imports")

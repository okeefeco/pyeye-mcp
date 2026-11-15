"""One package predicate: ``project_layout.package_kind`` (#625 slice 2).

Three copies used to decide "is this a package?" from a Jedi ``module_path``:
``inspect._is_package_path``, ``outline._is_package`` and ``edges._package_dirs``.
They split on ``module_path is None``: ``_package_dirs`` treated it as a
namespace package, while the other two said "not a package". The split was
real but unwritten.

``package_kind`` now returns ``"unknown"`` for ``None``, and each caller's
choice is pinned here so it can't drift silently.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from pyeye.project_layout import package_kind

# ``pyeye.mcp.operations.<name>`` as an attribute is the re-exported function,
# not the module, so import the modules explicitly.
edges = importlib.import_module("pyeye.mcp.operations.edges")
inspect = importlib.import_module("pyeye.mcp.operations.inspect")
outline = importlib.import_module("pyeye.mcp.operations.outline")


@pytest.fixture
def tree(tmp_path: Path) -> dict[str, Path]:
    pkg = tmp_path / "pkg"
    ns = tmp_path / "ns"
    pkg.mkdir()
    ns.mkdir()
    init = pkg / "__init__.py"
    mod = pkg / "mod.py"
    stub = pkg / "mod.pyi"
    for f in (init, mod, stub):
        f.write_text("", encoding="utf-8")
    return {"init": init, "mod": mod, "stub": stub, "ns": ns, "missing": tmp_path / "gone"}


class TestPackageKind:
    def test_regular_package(self, tree: dict[str, Path]) -> None:
        assert package_kind(tree["init"]) == "regular"
        assert package_kind(tree["init"].as_posix()) == "regular"

    def test_plain_module(self, tree: dict[str, Path]) -> None:
        assert package_kind(tree["mod"]) == "module"

    def test_namespace_directory(self, tree: dict[str, Path]) -> None:
        assert package_kind(tree["ns"]) == "namespace"

    def test_none_is_unknown(self) -> None:
        assert package_kind(None) == "unknown"

    def test_non_py_file_is_unknown(self, tree: dict[str, Path]) -> None:
        assert package_kind(tree["stub"]) == "unknown"
        assert package_kind(tree["missing"]) == "unknown"

    def test_unstatable_path_is_unknown(self, tmp_path: Path) -> None:
        with patch.object(Path, "is_dir", side_effect=OSError("boom")):
            assert package_kind(tmp_path / "x") == "unknown"


class TestCallersPinTheirUnknownChoice:
    """Each caller's answer for every kind, including ``None``."""

    def test_inspect_is_package(self, tree: dict[str, Path]) -> None:
        assert inspect._is_package_path(tree["init"]) is True
        assert inspect._is_package_path(tree["ns"]) is True
        assert inspect._is_package_path(tree["mod"]) is False
        assert inspect._is_package_path(tree["stub"]) is False
        assert inspect._is_package_path(None) is False  # unknown -> not a package

    def test_outline_is_package(self, tree: dict[str, Path]) -> None:
        def name(p: object) -> SimpleNamespace:
            return SimpleNamespace(module_path=p)

        assert outline._is_package(name(tree["init"])) is True
        assert outline._is_package(name(tree["ns"])) is True
        assert outline._is_package(name(tree["mod"])) is False
        assert outline._is_package(name(None)) is False  # unknown -> not a package
        assert outline._is_package(SimpleNamespace()) is False  # no attribute at all

    def test_package_dirs(self, tree: dict[str, Path]) -> None:
        analyzer = object()
        with patch.object(edges, "find_namespace_package_dirs", return_value=[Path("/x")]) as ns:
            assert edges._package_dirs(
                SimpleNamespace(module_path=tree["init"], full_name="pkg"), analyzer
            ) == [tree["init"].parent]
            assert (
                edges._package_dirs(
                    SimpleNamespace(module_path=tree["mod"], full_name="pkg.mod"), analyzer
                )
                == []
            )
            ns.assert_not_called()

            # unknown -> looked up as a namespace package by name
            assert edges._package_dirs(
                SimpleNamespace(module_path=None, full_name="nspkg"), analyzer
            ) == [Path("/x")]
            ns.assert_called_with("nspkg", analyzer)

            # namespace (a directory path) -> also looked up by name, not the dir itself
            assert edges._package_dirs(
                SimpleNamespace(module_path=tree["ns"], full_name="ns"), analyzer
            ) == [Path("/x")]

            # unknown with no name -> nothing to look up
            assert (
                edges._package_dirs(SimpleNamespace(module_path=None, full_name=""), analyzer) == []
            )

"""A package registered without saving the config reaches Jedi too (#858), in one root order (#962).

``configure_packages(save=False)`` (and ``ProjectManager.register_project``) hands
packages to the analyzer through ``set_additional_paths``, which only stored them
for pyeye's own scope search: Jedi never saw them. Imports of such a package were
unresolved, callees into it and types from it had no handle, and Jedi named a
package nested in the project from the project root, so a relative import inside
one under a dot-directory couldn't be followed. A package saved in ``.pyeye.json``
was fine: the analyzer's constructor puts config packages on Jedi's path.

Jedi's added roots are now composed in ONE order, whichever setter ran last:
config packages or ``src/``, then additional paths, then namespace repo roots. A
``set()`` merge in ``set_namespace_paths`` made it arbitrary (#962), and the order
decides precedence between roots (#419).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer


def _tool(name: str, **args: Any) -> dict[str, Any]:
    from pyeye.mcp.server import mcp

    result = asyncio.run(mcp.call_tool(name, args))
    assert not result.is_error, result.content
    payload = result.structured_content
    assert isinstance(payload, dict)
    return payload


@pytest.fixture(params=["external", "nested-dot-dir"])
def project(request: pytest.FixtureRequest, tmp_path: Path) -> Path:
    """A project using ``mylib``, registered with ``save=False``, outside or under ``.hidden/``."""
    proj = tmp_path / "proj"
    proj.mkdir()
    root = tmp_path / "mylib" if request.param == "external" else proj / ".hidden" / "up"
    pkg = root / "mylib"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("from .core import Lib, make\n", encoding="utf-8")
    (pkg / "core.py").write_text(
        "class Lib:\n    pass\n\n\ndef make() -> Lib:\n    return Lib()\n", encoding="utf-8"
    )
    (proj / "app.py").write_text(
        "from mylib import Lib, make\n\n\ndef run(x: Lib) -> Lib:\n    return make()\n",
        encoding="utf-8",
    )
    _tool(
        "configure_packages", packages=[root.as_posix()], save=False, project_path=proj.as_posix()
    )
    assert not (proj / ".pyeye.json").exists()
    return proj


class TestSaveFalsePackagesReachJedi:
    def test_resolve_at_an_imported_name(self, project: Path) -> None:
        payload = _tool(
            "resolve_at",
            file="app.py",
            line=1,
            column=len("from mylib import L"),
            project_path=project.as_posix(),
        )
        assert payload["handle"] == "mylib.core.Lib"

    def test_the_imports_edge(self, project: Path) -> None:
        payload = _tool("expand", handle="app", edge="imports", project_path=project.as_posix())

        assert {s["handle"] for s in payload["stubs"]} == {"mylib.core.Lib", "mylib.core.make"}
        assert payload.get("unresolved_imports", []) == []

    def test_callees_into_the_package(self, project: Path) -> None:
        payload = _tool("expand", handle="app.run", edge="callees", project_path=project.as_posix())

        assert [s["handle"] for s in payload["stubs"]] == ["mylib.core.make"]
        assert payload["unresolved_call_sites"] == 0

    def test_types_from_the_package(self, project: Path) -> None:
        payload = _tool("inspect", handle="app.run", project_path=project.as_posix())

        assert payload["parameters"][0]["type"]["handle"] == "mylib.core.Lib"
        assert payload["return_type"]["handle"] == "mylib.core.Lib"

    def test_a_relative_re_export_collapses(self, project: Path) -> None:
        payload = _tool("resolve", identifier="mylib.Lib", project_path=project.as_posix())

        assert payload["handle"] == "mylib.core.Lib"


class TestOneRootOrder:
    @pytest.fixture
    def layout(self, tmp_path: Path) -> dict[str, Path]:
        dirs = {name: tmp_path / name for name in ("proj", "pkg_a", "pkg_b", "ns_x", "ns_y")}
        for path in dirs.values():
            path.mkdir()
        (dirs["proj"] / "app.py").write_text("", encoding="utf-8")
        return dirs

    @staticmethod
    def _roots(analyzer: JediAnalyzer) -> list[str]:
        return [p.as_posix() for p in analyzer.added_sys_path]

    def test_additional_then_namespace_roots(self, layout: dict[str, Path]) -> None:
        analyzer = JediAnalyzer(
            layout["proj"].as_posix(),
            namespace_config={"x": [layout["ns_x"].as_posix()], "y": [layout["ns_y"].as_posix()]},
        )
        analyzer.set_additional_paths([layout["pkg_a"], layout["pkg_b"]])

        assert self._roots(analyzer) == [
            layout[name].resolve().as_posix() for name in ("pkg_a", "pkg_b", "ns_x", "ns_y")
        ]

    def test_the_order_does_not_depend_on_which_setter_ran_last(
        self, layout: dict[str, Path]
    ) -> None:
        namespaces = {"x": [layout["ns_x"].as_posix()], "y": [layout["ns_y"].as_posix()]}
        additional = [layout["pkg_a"], layout["pkg_b"]]

        first = JediAnalyzer(layout["proj"].as_posix())
        first.set_namespace_paths(namespaces)
        first.set_additional_paths(additional)
        second = JediAnalyzer(layout["proj"].as_posix())
        second.set_additional_paths(additional)
        second.set_namespace_paths(namespaces)

        assert self._roots(first) == self._roots(second)

    def test_repeated_calls_are_stable(self, layout: dict[str, Path]) -> None:
        """A set() merge (#962) could reorder roots on every call."""
        analyzer = JediAnalyzer(layout["proj"].as_posix())
        analyzer.set_additional_paths([layout["pkg_a"]])
        namespaces = {"y": [layout["ns_y"].as_posix()], "x": [layout["ns_x"].as_posix()]}
        seen = set()
        for _ in range(5):
            analyzer.set_namespace_paths(namespaces)
            seen.add(tuple(self._roots(analyzer)))

        assert len(seen) == 1
        assert next(iter(seen))[1:] == (
            layout["ns_y"].resolve().as_posix(),
            layout["ns_x"].resolve().as_posix(),
        )

    def test_jedi_gets_the_same_order(self, layout: dict[str, Path]) -> None:
        analyzer = JediAnalyzer(layout["proj"].as_posix())
        analyzer.set_additional_paths([layout["pkg_b"], layout["pkg_a"]])

        assert [Path(p).as_posix() for p in analyzer.project.added_sys_path] == self._roots(
            analyzer
        )

    def test_a_missing_path_and_the_project_itself_are_left_out(
        self, layout: dict[str, Path]
    ) -> None:
        analyzer = JediAnalyzer(layout["proj"].as_posix())
        analyzer.set_additional_paths([layout["proj"], layout["pkg_a"] / "gone", layout["pkg_a"]])

        assert self._roots(analyzer) == [layout["pkg_a"].resolve().as_posix()]

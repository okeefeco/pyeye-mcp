"""Process-wide caches are keyed on the effective layout, not the project root (#618).

The name index (``project_graph``) bakes module names in at build time, and module
names depend on the analyzer's layout: source roots, sys.path additions, packages,
namespaces. It was keyed only on the project root, so whichever analyzer built it
first fixed the names for every later analyzer on that root, in either order
(bare -> managed and managed -> bare). ``file_artifact_cache`` keyed Jedi Scripts
on the root alone, so two Projects with different ``added_sys_path`` shared them.

``configure_packages`` also left dependent state stale: the name index survived,
plugins never got the new paths, and it was hard-wired to ``ProjectConfig(".")``.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import jedi
import pytest

import pyeye.project_manager as project_manager_module
from pyeye import file_artifact_cache
from pyeye.analyzers import project_graph
from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.config import ProjectConfig
from pyeye.mcp import server
from pyeye.mcp.operations import typeref
from pyeye.mcp.operations.resolve import resolve
from pyeye.plugins.pydantic import PydanticPlugin
from pyeye.project_layout import layout_key
from pyeye.project_manager import ProjectManager

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _clear_process_caches() -> None:
    project_graph.invalidate()
    file_artifact_cache.invalidate_all()
    typeref.invalidate_all()


@pytest.fixture
def src_project(tmp_path: Path) -> Path:
    """A project whose source root only its config declares.

    ``code/`` holds the package, and only ``.pyeye.json`` makes it a source root.
    A managed analyzer (which reads the config) names ``mypackage.module``; a bare
    one names ``code.mypackage.module``. ``src/`` would not do: since #648 a bare
    analyzer auto-detects ``src/`` too, and the two layouts would coincide,
    hiding the leak (#618 comment: "deliberately different configs").
    """
    root = tmp_path / "proj"
    pkg = root / "code" / "mypackage"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    shutil.copy(FIXTURES / "added_sys_path_project" / "src" / "mypackage" / "module.py", pkg)
    (root / ".pyeye.json").write_text(json.dumps({"packages": ["code"]}))
    return root


@pytest.fixture
def manager() -> Iterator[ProjectManager]:
    m = ProjectManager(max_projects=10)
    yield m
    m.cleanup_all()


async def _handle(analyzer: JediAnalyzer) -> Any:
    result = await resolve("my_function", analyzer)
    return result.get("handle") if result.get("found") else None


async def _alone(src_project: Path, mode: str) -> Any:
    """The answer each mode gives with no other analyzer having touched the root."""
    _clear_process_caches()
    m = ProjectManager(max_projects=10)
    try:
        analyzer = (
            JediAnalyzer(str(src_project)) if mode == "bare" else m.get_analyzer(str(src_project))
        )
        return await _handle(analyzer)
    finally:
        m.cleanup_all()
        _clear_process_caches()


# ---------------------------------------------------------------------------
# The cross-analyzer leak, in both directions, in one process
# ---------------------------------------------------------------------------


class TestNoLeakBetweenLayouts:
    async def test_the_two_modes_really_differ(self, src_project: Path) -> None:
        """Guard: the fixture gives the two layouts different answers, so a leak shows."""
        bare = await _alone(src_project, "bare")
        managed = await _alone(src_project, "get_analyzer")

        assert managed == "mypackage.module.my_function"
        assert bare != managed

    async def test_bare_then_managed(self, src_project: Path, manager: ProjectManager) -> None:
        # On this fixture resolve re-derives a found handle through the managed
        # analyzer's own mapper, which masks a stale bare-built index; worker
        # saw this direction fail on other fixtures (#618), so it stays pinned.
        expected_bare = await _alone(src_project, "bare")
        expected_managed = await _alone(src_project, "get_analyzer")

        bare = await _handle(JediAnalyzer(str(src_project)))
        managed = await _handle(manager.get_analyzer(str(src_project)))

        assert (bare, managed) == (expected_bare, expected_managed)

    async def test_managed_then_bare(self, src_project: Path, manager: ProjectManager) -> None:
        expected_bare = await _alone(src_project, "bare")
        expected_managed = await _alone(src_project, "get_analyzer")

        managed = await _handle(manager.get_analyzer(str(src_project)))
        bare = await _handle(JediAnalyzer(str(src_project)))

        assert (managed, bare) == (expected_managed, expected_bare)

    async def test_both_alive_at_once_keep_their_own_indices(
        self, src_project: Path, manager: ProjectManager
    ) -> None:
        expected_bare = await _alone(src_project, "bare")
        expected_managed = await _alone(src_project, "get_analyzer")
        bare_analyzer = JediAnalyzer(str(src_project))
        managed_analyzer = manager.get_analyzer(str(src_project))

        for _ in range(2):  # interleaved, repeatedly; managed builds first
            assert await _handle(managed_analyzer) == expected_managed
            assert await _handle(bare_analyzer) == expected_bare

    async def test_invalidating_the_root_drops_every_layout(
        self, src_project: Path, manager: ProjectManager
    ) -> None:
        await _handle(JediAnalyzer(str(src_project)))
        await _handle(manager.get_analyzer(str(src_project)))
        root_key = project_graph._normalize(src_project.as_posix())
        assert len(project_graph._name_indices.get(root_key, {})) == 2

        project_graph.invalidate(src_project.as_posix())

        assert root_key not in project_graph._name_indices


# ---------------------------------------------------------------------------
# layout_key: a pure function of the effective layout
# ---------------------------------------------------------------------------


def _layout(root: Path, **overrides: Any) -> SimpleNamespace:
    fields: dict[str, Any] = {
        "project_path": root,
        "source_roots": [],
        "added_sys_path": [],
        "additional_paths": [],
        "namespace_paths": {},
        "standalone_paths": [],
        "_jedi_root_is_parent": False,
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


class TestLayoutKey:
    def test_equal_layouts_have_equal_keys(self, tmp_path: Path) -> None:
        assert layout_key(_layout(tmp_path)) == layout_key(_layout(tmp_path / "." / ""))

    @pytest.mark.parametrize(
        "field",
        [
            "source_roots",
            "added_sys_path",
            "additional_paths",
            "standalone_paths",
            "namespace_paths",
            "_jedi_root_is_parent",
        ],
    )
    def test_every_layout_field_changes_the_key(self, tmp_path: Path, field: str) -> None:
        value: Any = {
            "namespace_paths": {"acme": [tmp_path / "ns"]},
            "_jedi_root_is_parent": True,
        }.get(field, [tmp_path / "x"])

        assert layout_key(_layout(tmp_path)) != layout_key(_layout(tmp_path, **{field: value}))

    def test_sys_path_order_matters(self, tmp_path: Path) -> None:
        a, b = tmp_path / "a", tmp_path / "b"
        assert layout_key(_layout(tmp_path, added_sys_path=[a, b])) != layout_key(
            _layout(tmp_path, added_sys_path=[b, a])
        )

    def test_namespace_order_does_not(self, tmp_path: Path) -> None:
        one = {"x": [tmp_path / "1"], "y": [tmp_path / "2"]}
        two = {"y": [tmp_path / "2"], "x": [tmp_path / "1"]}
        assert layout_key(_layout(tmp_path, namespace_paths=one)) == layout_key(
            _layout(tmp_path, namespace_paths=two)
        )

    def test_analyzer_exposes_it(self, src_project: Path) -> None:
        analyzer = JediAnalyzer(str(src_project), config=ProjectConfig(str(src_project)))
        assert analyzer.layout_key == layout_key(analyzer)
        assert analyzer.layout_key != JediAnalyzer(str(src_project)).layout_key


# ---------------------------------------------------------------------------
# file_artifact_cache Scripts: keyed on the Project's sys.path, API unchanged
# ---------------------------------------------------------------------------


class TestScriptKey:
    def test_projects_with_different_sys_path_get_different_scripts(
        self, src_project: Path
    ) -> None:
        mod = src_project / "code" / "mypackage" / "module.py"
        plain = jedi.Project(path=str(src_project))
        with_src = jedi.Project(path=str(src_project), added_sys_path=[str(src_project / "code")])
        file_artifact_cache.invalidate_all()

        a = file_artifact_cache.get_script(mod, plain)
        b = file_artifact_cache.get_script(mod, with_src)

        assert a is not b
        assert file_artifact_cache.get_script(mod, plain) is a  # still cached per Project layout
        assert file_artifact_cache.get_script(mod, with_src) is b


# ---------------------------------------------------------------------------
# configure_packages: new packages visible without a restart
# ---------------------------------------------------------------------------


_MODEL = "from pydantic import BaseModel\n\n\nclass {name}(BaseModel):\n    x: int\n"


@pytest.fixture
def two_repos(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "app"
    (root / "app").mkdir(parents=True)
    (root / "app" / "__init__.py").write_text("")
    (root / "app" / "models.py").write_text(_MODEL.format(name="AppModel"))
    lib = tmp_path / "lib"
    (lib / "libpkg").mkdir(parents=True)
    (lib / "libpkg" / "__init__.py").write_text("")
    (lib / "libpkg" / "things.py").write_text(
        "class LibThing:\n    pass\n\n\n" + _MODEL.format(name="LibModel")
    )
    return root, lib


@pytest.fixture
def fresh_server(monkeypatch: pytest.MonkeyPatch) -> Iterator[ProjectManager]:
    """Isolate the server's global ProjectManager and plugin list."""
    m = ProjectManager(max_projects=10)
    monkeypatch.setattr(project_manager_module, "_project_manager", m)
    monkeypatch.setattr(server, "_plugins", [])
    _clear_process_caches()
    yield m
    m.cleanup_all()
    _clear_process_caches()


class TestConfigurePackages:
    @pytest.mark.usefixtures("fresh_server")
    async def test_added_package_resolves_and_inspects_without_restart(
        self, two_repos: tuple[Path, Path]
    ) -> None:
        root, lib = two_repos
        assert (await server.resolve("LibThing", project_path=str(root)))["found"] is False

        await server.configure_packages(packages=[lib.as_posix()], project_path=str(root))

        resolved = await server.resolve("LibThing", project_path=str(root))
        assert resolved["found"] is True
        inspected = await server.inspect(resolved["handle"], project_path=str(root))
        assert inspected.get("found", True) is not False
        assert inspected["handle"] == resolved["handle"]

    @pytest.mark.usefixtures("fresh_server")
    async def test_plugins_get_the_new_paths(self, two_repos: tuple[Path, Path]) -> None:
        root, lib = two_repos
        plugin = PydanticPlugin(str(root))
        server._plugins.append(plugin)
        assert {m["name"] for m in await plugin.find_models(scope="all")} == {"AppModel"}

        await server.configure_packages(packages=[lib.as_posix()], project_path=str(root))

        assert {m["name"] for m in await plugin.find_models(scope="all")} == {
            "AppModel",
            "LibModel",
        }

    @pytest.mark.usefixtures("fresh_server")
    async def test_plugins_of_other_projects_are_left_alone(
        self, two_repos: tuple[Path, Path], tmp_path: Path
    ) -> None:
        root, lib = two_repos
        other = tmp_path / "other"
        other.mkdir()
        plugin = PydanticPlugin(str(other))
        server._plugins.append(plugin)

        await server.configure_packages(packages=[lib.as_posix()], project_path=str(root))

        assert plugin.additional_paths == []

    @pytest.mark.usefixtures("fresh_server")
    async def test_uses_the_given_project_not_the_cwd(
        self, two_repos: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root, lib = two_repos
        cwd = tmp_path / "cwd"
        cwd.mkdir()
        monkeypatch.chdir(cwd)

        result = await server.configure_packages(packages=[lib.as_posix()], project_path=str(root))

        assert not (cwd / ".pyeye.json").exists()
        saved = json.loads((root / ".pyeye.json").read_text())
        # Compare as paths: the config stores them in the OS's native form.
        assert [Path(p).resolve() for p in saved["packages"]] == [lib.resolve()]
        assert result["config_file"] == (root.resolve() / ".pyeye.json").as_posix()

    async def test_new_package_root_is_watched(
        self, two_repos: tuple[Path, Path], fresh_server: ProjectManager
    ) -> None:
        root, lib = two_repos
        await server.resolve("AppModel", project_path=str(root))

        await server.configure_packages(packages=[lib.as_posix()], project_path=str(root))
        await server.resolve("LibThing", project_path=str(root))

        assert lib.resolve() in fresh_server.watchers

    @pytest.mark.usefixtures("fresh_server")
    async def test_typerefs_of_the_project_are_dropped(self, two_repos: tuple[Path, Path]) -> None:
        root, lib = two_repos
        key = (root.resolve().as_posix(), "f.py", 1, 0, 0, 0, 0, "X")
        typeref._store_typeref(key, {"raw": "X"})

        await server.configure_packages(packages=[lib.as_posix()], project_path=str(root))

        assert typeref._cached_typeref(key) is None

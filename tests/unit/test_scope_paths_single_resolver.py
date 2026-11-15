"""One scope→paths resolver for the analyzer and the plugins (#690 item 1, #594).

``JediAnalyzer._resolve_scope_to_paths`` and ``AnalyzerPlugin._scope_paths`` had
drifted: the plugin copy didn't know ``standalone``, left standalone dirs out of
``all``, had no sub-namespaces, and its ``packages`` searched the main project and
every namespace. Both now delegate to :func:`pyeye.scope_utils.resolve_scope_paths`
over one :class:`~pyeye.scope_utils.ScopeLayout`.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from pyeye import project_manager as project_manager_module
from pyeye.config import ProjectConfig
from pyeye.mcp.server import _apply_plugin_paths, get_analyzer
from pyeye.plugins.pydantic import PydanticPlugin
from pyeye.project_manager import ProjectManager
from pyeye.scope import classify_scope

SCOPES = ["main", "all", "packages", "standalone", "namespace:acme", "namespace:acme.tools"]


@pytest.fixture(autouse=True)
def isolated_manager(monkeypatch: pytest.MonkeyPatch) -> Iterator[ProjectManager]:
    """A fresh ProjectManager, so no other test's registered packages leak in."""
    m = ProjectManager(max_projects=10)
    monkeypatch.setattr(project_manager_module, "_project_manager", m)
    yield m
    m.cleanup_all()


@pytest.fixture
def layout(tmp_path: Path) -> Path:
    """main + one package + a namespace repo + a standalone scripts dir."""
    main = tmp_path / "main"
    (main / "app").mkdir(parents=True)
    (main / "app" / "__init__.py").write_text("")
    lib = tmp_path / "lib"
    (lib / "libpkg").mkdir(parents=True)
    (lib / "libpkg" / "__init__.py").write_text("def helper(): pass\n")
    ns = tmp_path / "nsrepo"
    (ns / "acme" / "tools").mkdir(parents=True)
    (ns / "acme" / "tools" / "__init__.py").write_text("def tool(): pass\n")
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "job.py").write_text("def run(): pass\n")
    (main / ".pyeye.json").write_text(
        json.dumps(
            {
                "packages": [lib.as_posix()],
                "namespaces": {"acme": [ns.as_posix()]},
                "standalone": {"dirs": [scripts.as_posix()]},
            }
        )
    )
    return tmp_path


def _plugin(root: Path) -> PydanticPlugin:
    main = root / "main"
    plugin = PydanticPlugin(main.as_posix())
    _apply_plugin_paths(plugin, ProjectConfig(main.as_posix()))
    return plugin


def _rel(paths: set[Path], root: Path) -> set[str]:
    return {p.resolve().relative_to(root.resolve()).as_posix() for p in paths}


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", SCOPES)
async def test_plugin_and_analyzer_resolve_every_scope_identically(
    layout: Path, scope: str
) -> None:
    analyzer = get_analyzer((layout / "main").as_posix())
    plugin = _plugin(layout)

    assert _rel(await plugin._resolve_scope_to_paths(scope), layout) == _rel(
        await analyzer._resolve_scope_to_paths(scope), layout
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scope", "expected"),
    [
        ("main", {"main"}),
        # #594: configured packages only, never the main project or the namespaces
        ("packages", {"lib"}),
        ("standalone", {"scripts"}),
        # A PEP 420 ``acme/`` with no Python files of its own: the repository
        # root, plus the namespace directory (the analyzer's long-standing rule).
        ("namespace:acme", {"nsrepo", "nsrepo/acme"}),
        ("namespace:acme.tools", {"nsrepo/acme/tools"}),
        ("all", {"main", "lib", "nsrepo", "nsrepo/acme", "scripts"}),
    ],
)
async def test_scope_semantics(layout: Path, scope: str, expected: set[str]) -> None:
    plugin = _plugin(layout)

    assert _rel(await plugin._resolve_scope_to_paths(scope), layout) == expected


def test_envelope_reports_packages_and_standalone_honestly(layout: Path) -> None:
    plugin = _plugin(layout)

    assert plugin.describe_scope("packages") == (
        ["packages"],
        ["main", "standalone", "namespace:acme"],
    )
    searched, unsearched = plugin.describe_scope("all")
    assert set(searched) == {"main", "packages", "standalone", "namespace:acme"}
    assert unsearched == []


@pytest.mark.asyncio
async def test_every_root_all_searches_is_project_scope(layout: Path) -> None:
    """#690 item 2: the search boundary and the scope classifier agree."""
    analyzer = get_analyzer((layout / "main").as_posix())

    for root in await analyzer._resolve_scope_to_paths("all"):
        for py_file in root.rglob("*.py"):
            assert classify_scope(py_file, analyzer) == "project", py_file

"""The Flask url registry is built once per project generation (#1034).

#957 added ``FlaskPlugin._url_registry``: a pass over every project file that
composes blueprint prefixes. It ran on every ``find_flask_routes`` and
``find_flask_blueprints`` call, which made a warm call ~2.3x slower. It is now
cached in ``project_graph`` beside the class and import graphs: per project,
layout and scope, dropped by ``project_graph.invalidate`` (the watcher,
eviction, ``configure_packages``), and never stored when a change landed while
it was being built (#617).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pyeye import project_manager as project_manager_module
from pyeye.analyzers import project_graph
from pyeye.plugins.flask import FlaskPlugin
from pyeye.project_manager import ProjectManager

_APP = """
from flask import Flask
from .admin import admin_bp

app = Flask(__name__)
app.register_blueprint(admin_bp, url_prefix="{prefix}")
"""
_ADMIN = """
from flask import Blueprint

admin_bp = Blueprint("admin", __name__)


@admin_bp.route("/users")
def users():
    return ""
"""


@pytest.fixture(autouse=True)
def isolated_manager(monkeypatch: pytest.MonkeyPatch):
    """A fresh ProjectManager and graph store per test."""
    m = ProjectManager(max_projects=10)
    monkeypatch.setattr(project_manager_module, "_project_manager", m)
    project_graph.invalidate()
    yield m
    m.cleanup_all()
    project_graph.invalidate()


def _project(tmp_path: Path, prefix: str = "/admin") -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text(_APP.format(prefix=prefix))
    (tmp_path / "app" / "admin.py").write_text(_ADMIN)
    return tmp_path


@pytest.fixture
def builds(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Each registry build, by scope."""
    seen: list[str] = []
    original = FlaskPlugin._build_url_registry

    async def counted(self: FlaskPlugin, scope):  # type: ignore[no-untyped-def]
        seen.append(str(scope))
        return await original(self, scope)

    monkeypatch.setattr(FlaskPlugin, "_build_url_registry", counted)
    return seen


def _users_urls(routes: list[dict]) -> list[str]:
    return next(r["urls"] for r in routes if r["name"] == "users")


@pytest.mark.asyncio
async def test_warm_calls_reuse_one_build(tmp_path: Path, builds: list[str]) -> None:
    plugin = FlaskPlugin(_project(tmp_path).as_posix())

    for _ in range(3):
        assert _users_urls(await plugin.find_routes()) == ["/admin/users"]
    await plugin.find_blueprints()  # same scope, same registry

    assert builds == ["main"]


@pytest.mark.asyncio
async def test_a_new_plugin_on_the_same_project_reuses_it(
    tmp_path: Path, builds: list[str]
) -> None:
    """Plugins are per call (#665): the cache must outlive the plugin object."""
    root = _project(tmp_path).as_posix()
    await FlaskPlugin(root).find_routes()
    await FlaskPlugin(root).find_routes()

    assert builds == ["main"]


@pytest.mark.asyncio
async def test_an_invalidation_rebuilds_with_the_new_source(
    tmp_path: Path, builds: list[str]
) -> None:
    root = _project(tmp_path)
    plugin = FlaskPlugin(root.as_posix())
    assert _users_urls(await plugin.find_routes()) == ["/admin/users"]

    (root / "app" / "__init__.py").write_text(_APP.format(prefix="/staff"))
    project_graph.invalidate(root.as_posix())  # what the watcher does on a change

    assert _users_urls(await plugin.find_routes()) == ["/staff/users"]
    assert builds == ["main", "main"]


@pytest.mark.asyncio
async def test_each_scope_has_its_own_registry(tmp_path: Path, builds: list[str]) -> None:
    plugin = FlaskPlugin(_project(tmp_path).as_posix())
    await plugin.find_routes(scope="main")
    await plugin.find_routes(scope="all")
    await plugin.find_routes(scope="main")

    assert builds == ["main", "all"]


@pytest.mark.asyncio
async def test_a_build_that_raced_a_change_is_not_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A change during the build means the registry may predate it (#617)."""
    root = _project(tmp_path)
    plugin = FlaskPlugin(root.as_posix())
    original = FlaskPlugin._build_url_registry
    seen: list[int] = []

    async def racing(self: FlaskPlugin, scope):  # type: ignore[no-untyped-def]
        registry = await original(self, scope)
        seen.append(1)
        if len(seen) == 1:
            project_graph.invalidate(root.as_posix())  # lands mid-build
        return registry

    monkeypatch.setattr(FlaskPlugin, "_build_url_registry", racing)
    await plugin.find_routes()
    await plugin.find_routes()  # the raced build wasn't stored: built again
    await plugin.find_routes()  # this one was

    assert len(seen) == 2

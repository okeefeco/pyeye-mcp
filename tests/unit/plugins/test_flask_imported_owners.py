"""Route shortcuts on an app or blueprint imported from another module (#910).

#905 counted ``@x.get(...)`` as a route only when ``x`` was bound to
``Flask(...)`` or ``Blueprint(...)`` in the same file, so the common layout
``routes.py: from .blueprints import bp`` was missed. The import is now placed
through pyeye's resolver, and the definition it lands on must itself be a
``Flask(...)`` or ``Blueprint(...)`` binding, so precision is unchanged: an
imported FastAPI router or cache is still not a route.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pyeye import project_manager as project_manager_module
from pyeye.plugins.flask import FlaskPlugin
from pyeye.project_manager import ProjectManager
from tests.utils.performance import PerformanceThresholds, assert_performance_threshold

_BLUEPRINTS = "from flask import Blueprint\n\nbp = Blueprint('bp', __name__)\n"


@pytest.fixture(autouse=True)
def isolated_manager(monkeypatch: pytest.MonkeyPatch):
    """A fresh ProjectManager per test, so analyzers don't leak between projects."""
    m = ProjectManager(max_projects=10)
    monkeypatch.setattr(project_manager_module, "_project_manager", m)
    yield m
    m.cleanup_all()


def _project(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp_path


async def _route_names(root: Path) -> list[str]:
    return sorted(r["name"] for r in await FlaskPlugin(root.as_posix()).find_routes())


def _handler(decorator: str, name: str = "view") -> str:
    return f"\n\n@{decorator}\ndef {name}():\n    return ''\n"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("routes_py", "decorator"),
    [
        ("from app.blueprints import bp", "bp.get('/x')"),
        ("from .blueprints import bp", "bp.post('/x')"),
        ("from .blueprints import bp as admin", "admin.put('/x')"),
        ("from app import bp", "bp.delete('/x')"),  # re-exported by app/__init__.py
        ("from . import blueprints", "blueprints.bp.patch('/x')"),
        ("import app.blueprints", "app.blueprints.bp.get('/x')"),
        ("import app.blueprints as bps", "bps.bp.get('/x')"),
    ],
    ids=[
        "absolute",
        "relative",
        "aliased",
        "re-exported",
        "module-attr",
        "dotted-import",
        "module-alias",
    ],
)
async def test_an_imported_blueprints_shortcut_is_a_route(
    tmp_path: Path, routes_py: str, decorator: str
) -> None:
    root = _project(
        tmp_path,
        {
            "app/__init__.py": "from .blueprints import bp\n",
            "app/blueprints.py": _BLUEPRINTS,
            "app/routes.py": routes_py + _handler(decorator),
        },
    )
    routes = await FlaskPlugin(root.as_posix()).find_routes()
    assert [(r["name"], r["path"], r["methods"]) for r in routes] == [
        ("view", "/x", [decorator.split(".")[-1].split("(")[0].upper()])
    ]


@pytest.mark.asyncio
async def test_an_imported_app_shortcut_is_a_route(tmp_path: Path) -> None:
    root = _project(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/core.py": "import flask\n\napplication = flask.Flask(__name__)\n",
            "app/views.py": "from .core import application" + _handler("application.get('/a')"),
        },
    )
    assert await _route_names(root) == ["view"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("defining", "routes_py", "decorator"),
    [
        (
            "from fastapi import APIRouter\n\nrouter = APIRouter()\n",
            "from .other import router",
            "router.get('/x')",
        ),
        (
            "class Cache:\n    pass\n\ncache = Cache()\n",
            "from .other import cache",
            "cache.get('k')",
        ),
        (
            "from flask import Blueprint\n\ndef make():\n    return Blueprint('b', __name__)\n\nbp = make()\n",
            "from .other import bp",
            "bp.get('/x')",
        ),
        ("", "from missing_module import bp", "bp.get('/x')"),
        ("", "from .other import nothing_here", "nothing_here.get('/x')"),
    ],
    ids=[
        "imported-fastapi-router",
        "imported-cache",
        "factory-result",
        "unresolvable",
        "missing-name",
    ],
)
async def test_an_imported_non_flask_receiver_is_not_a_route(
    tmp_path: Path, defining: str, routes_py: str, decorator: str
) -> None:
    root = _project(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/other.py": defining,
            "app/routes.py": routes_py + _handler(decorator),
        },
    )
    assert await _route_names(root) == []


@pytest.mark.asyncio
async def test_a_function_parameter_receiver_is_not_recognised(tmp_path: Path) -> None:
    """Honest limit (#910): a receiver passed in as an argument can't be placed."""
    root = _project(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/blueprints.py": _BLUEPRINTS,
            "app/routes.py": (
                "def register(bp):\n\n    @bp.get('/x')\n    def view():\n        return ''\n\n"
                "    @bp.route('/y')\n    def other():\n        return ''\n"
            ),
        },
    )
    assert await _route_names(root) == ["other"]


@pytest.mark.asyncio
async def test_one_resolution_per_imported_receiver(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Many shortcuts on one imported blueprint place its import once per call."""
    import pyeye.plugins.flask as flask_plugin

    calls: list[str] = []
    real = flask_plugin.resolve_item

    def counting(path: str, analyzer: object):  # type: ignore[no-untyped-def]
        calls.append(path)
        return real(path, analyzer)  # type: ignore[arg-type]

    monkeypatch.setattr(flask_plugin, "resolve_item", counting)
    handlers = "".join(_handler(f"bp.get('/r{i}')", f"view{i}") for i in range(10))
    root = _project(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/blueprints.py": _BLUEPRINTS,
            "app/routes.py": "from .blueprints import bp" + handlers,
        },
    )
    assert len(await FlaskPlugin(root.as_posix()).find_routes()) == 10
    assert calls == ["app.blueprints.bp"]


@pytest.mark.asyncio
async def test_files_without_an_unplaced_shortcut_never_touch_the_resolver(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import pyeye.plugins.flask as flask_plugin

    def boom(*_a: object) -> None:
        raise AssertionError("resolver consulted")

    monkeypatch.setattr(flask_plugin, "resolve_item", boom)
    root = _project(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/local.py": "from flask import Flask\n\napp = Flask(__name__)"
            + _handler("app.get('/l')"),
            "app/old.py": "from .local import app" + _handler("app.route('/o')", "old"),
        },
    )
    assert await _route_names(root) == ["old", "view"]


#: A warm ``find_flask_routes`` over 50 files, one of them using 10 shortcuts on
#: an imported blueprint. Measured on dev01 under pytest (inert watchers): about
#: 60 ms warm alone; the import placement is one resolve (~3 ms) per call. The local
#: base allows for two concurrent suites (#835); CI values follow ENRICH_MANY's
#: ratios.
IMPORTED_OWNER_ROUTES = PerformanceThresholds(
    base=400.0, linux_ci=600.0, macos_ci=1200.0, windows_ci=1200.0
)


@pytest.mark.asyncio
async def test_placing_an_imported_blueprint_stays_cheap(tmp_path: Path) -> None:
    import statistics
    import time

    files = {"app/__init__.py": "", "app/blueprints.py": _BLUEPRINTS}
    for i in range(48):
        files[f"app/mod{i}.py"] = "from flask import Flask\n\napp = Flask(__name__)" + "".join(
            _handler(f"app.route('/m{i}/{j}')", f"v{j}") for j in range(5)
        )
    files["app/routes.py"] = "from .blueprints import bp" + "".join(
        _handler(f"bp.get('/r{j}')", f"r{j}") for j in range(10)
    )
    plugin = FlaskPlugin(_project(tmp_path, files).as_posix())
    assert len(await plugin.find_routes()) == 250  # cold: builds the analyzer

    samples = []
    for _ in range(3):
        start = time.perf_counter()
        await plugin.find_routes()
        samples.append((time.perf_counter() - start) * 1000)
    assert_performance_threshold(
        statistics.median(samples), IMPORTED_OWNER_ROUTES, "find_flask_routes, imported blueprint"
    )


@pytest.mark.parametrize(
    ("level", "module", "importer", "is_package", "expected"),
    [
        (0, "app.blueprints", "app.routes", False, "app.blueprints"),
        (1, "blueprints", "app.routes", False, "app.blueprints"),
        (1, "", "app.routes", False, "app"),
        (1, "blueprints", "app", True, "app.blueprints"),  # from app/__init__.py
        (2, "core", "app.web.routes", False, "app.core"),
        (2, "core", "app.routes", False, None),  # climbs above the top package
        (1, "x", None, False, None),  # importer outside every root
    ],
)
def test_relative_imports_are_named_like_python_names_them(
    level: int, module: str, importer: str | None, is_package: bool, expected: str | None
) -> None:
    from pyeye.plugins.flask import _absolute_module

    assert _absolute_module(level, module, importer, is_package) == expected


def test_import_bindings_and_receiver_chains() -> None:
    import ast

    from pyeye.plugins.flask import _import_bindings, _receiver_chain

    tree = ast.parse(
        "import a.b\nimport c.d as e\nfrom .m import x as y\nfrom n import z\nfrom q import *\n"
    )
    assert _import_bindings(tree) == {
        "a": (0, "a", None),
        "e": (0, "c.d", None),
        "y": (1, "m", "x"),
        "z": (0, "n", "z"),
    }
    expr = ast.parse("a.b.bp", mode="eval").body
    assert _receiver_chain(expr) == ["a", "b", "bp"]
    assert _receiver_chain(ast.parse("f().bp", mode="eval").body) is None


@pytest.mark.asyncio
async def test_a_relative_import_above_the_top_package_is_not_placed(tmp_path: Path) -> None:
    root = _project(
        tmp_path,
        {"app/__init__.py": "", "app/routes.py": "from ... import bp" + _handler("bp.get('/x')")},
    )
    assert await _route_names(root) == []


@pytest.mark.asyncio
async def test_an_unparseable_defining_file_is_not_an_owner(tmp_path: Path) -> None:
    """The definition can't be checked, so it isn't claimed (absence, not a guess)."""
    root = _project(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/blueprints.py": _BLUEPRINTS + "\ndef broken(:\n",
            "app/routes.py": "from .blueprints import bp" + _handler("bp.get('/x')"),
        },
    )
    assert await _route_names(root) == []


@pytest.mark.asyncio
async def test_a_resolution_without_a_position_is_not_an_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import pyeye.plugins.flask as flask_plugin
    from pyeye.resolver import Resolved

    monkeypatch.setattr(
        flask_plugin,
        "resolve_item",
        lambda path, _analyzer: Resolved(
            handle=path, kind="module", scope="project", anchor=object()
        ),
    )
    root = _project(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/blueprints.py": _BLUEPRINTS,
            "app/routes.py": "from .blueprints import bp" + _handler("bp.get('/x')"),
        },
    )
    assert await _route_names(root) == []

"""``find_flask_routes`` finds Flask 2.0's route shortcuts (#905).

``@app.get(path)``, ``.post``, ``.put``, ``.delete`` and ``.patch`` (on an app
or a blueprint) are ``route`` with one fixed method. They used to be missed,
so a project using them got a confident ``[]`` or a partial list.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pyeye.plugins.flask import FlaskPlugin


async def _routes_in(tmp_path: Path, body: str) -> list[dict]:
    (tmp_path / "app.py").write_text(
        "from flask import Blueprint, Flask\n"
        "app = Flask(__name__)\nbp = Blueprint('bp', __name__)\n\n" + body,
        encoding="utf-8",
    )
    return await FlaskPlugin(tmp_path.as_posix()).find_routes()


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["get", "post", "put", "delete", "patch"])
@pytest.mark.parametrize("owner", ["app", "bp"])
async def test_shortcut_is_a_route_with_its_method(tmp_path: Path, method: str, owner: str) -> None:
    routes = await _routes_in(
        tmp_path, f"@{owner}.{method}('/items')\ndef handler():\n    return ''\n"
    )
    assert [(r["name"], r["path"], r["methods"], r["type"], r["line"]) for r in routes] == [
        ("handler", "/items", [method.upper()], "route", 6)
    ]


@pytest.mark.asyncio
async def test_async_shortcut_is_found(tmp_path: Path) -> None:
    routes = await _routes_in(
        tmp_path, "@app.post('/jobs')\nasync def create_job():\n    return ''\n"
    )
    assert [(r["name"], r["methods"]) for r in routes] == [("create_job", ["POST"])]


@pytest.mark.asyncio
async def test_route_keeps_its_methods_alongside_shortcuts(tmp_path: Path) -> None:
    routes = await _routes_in(
        tmp_path,
        "@app.route('/a', methods=['GET', 'PUT'])\ndef a():\n    return ''\n\n"
        "@app.get('/b')\ndef b():\n    return ''\n",
    )
    assert sorted((r["name"], r["path"], r["methods"]) for r in routes) == [
        ("a", "/a", ["GET", "PUT"]),
        ("b", "/b", ["GET"]),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "decorator",
    [
        "@cache.get(key)",  # not a string path
        "@registry.get()",  # no arguments
        "@app.get",  # not a call
        "@app.head('/x')",  # not a Flask shortcut
        "@app.options('/x')",
    ],
)
async def test_non_routes_are_not_reported(tmp_path: Path, decorator: str) -> None:
    routes = await _routes_in(tmp_path, f"key = 'k'\n{decorator}\ndef f():\n    return ''\n")
    assert routes == []


# --- precision: only a Flask app or Blueprint's shortcut is a route ----------


def _routes_in_file(tmp_path: Path, source: str):  # -> coroutine of list[dict]
    (tmp_path / "mod.py").write_text(source, encoding="utf-8")
    return FlaskPlugin(tmp_path.as_posix()).find_routes()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "source",
    [
        # FastAPI router and app: same decorator spelling, not Flask
        "from fastapi import APIRouter\nrouter = APIRouter()\n\n"
        "@router.get('/x')\ndef read():\n    return {}\n",
        "from fastapi import FastAPI\napp = FastAPI()\n\n"
        "@app.post('/items')\nasync def create():\n    return {}\n",
        # A FastAPI app in a file that also imports flask
        "import flask\nfrom fastapi import FastAPI\napp = FastAPI()\n\n"
        "@app.get('/x')\ndef read():\n    return {}\n",
        # Non-Flask decorators with a string first argument
        "cache = make_cache()\n\n@cache.get('k')\ndef cached():\n    pass\n",
        "registry = Registry()\n\n@registry.post('name')\ndef handler():\n    pass\n",
        # A receiver that isn't a plain name
        "from flask import Flask\n\nclass S:\n    app = None\n\n"
        "@S.app.get('/x')\ndef f():\n    pass\n",
    ],
    ids=["fastapi-router", "fastapi-app", "fastapi-beside-flask", "cache", "registry", "attribute"],
)
async def test_other_frameworks_shortcuts_are_not_routes(tmp_path: Path, source: str) -> None:
    assert await _routes_in_file(tmp_path, source) == []


@pytest.mark.asyncio
async def test_factory_app_shortcut_is_a_route(tmp_path: Path) -> None:
    routes = await _routes_in_file(
        tmp_path,
        "from flask import Flask\n\ndef create_app():\n    app = Flask(__name__)\n\n"
        "    @app.get('/health')\n    def health():\n        return 'ok'\n\n    return app\n",
    )
    assert [(r["name"], r["path"], r["methods"]) for r in routes] == [
        ("health", "/health", ["GET"])
    ]


@pytest.mark.asyncio
async def test_module_attribute_and_annotated_owners_are_recognised(tmp_path: Path) -> None:
    routes = await _routes_in_file(
        tmp_path,
        "import flask\nweb = flask.Flask(__name__)\napi: flask.Blueprint = flask.Blueprint('api', __name__)\n\n"
        "@web.delete('/a')\ndef a():\n    pass\n\n@api.patch('/b')\ndef b():\n    pass\n",
    )
    assert sorted((r["name"], r["methods"]) for r in routes) == [
        ("a", ["DELETE"]),
        ("b", ["PATCH"]),
    ]


@pytest.mark.asyncio
async def test_a_blueprint_imported_from_another_module_is_recognised(tmp_path: Path) -> None:
    """Once #905's limit, closed by #910: the import is placed through the resolver.

    The import cases (relative, re-exported, module attribute, the precision
    negatives) are in ``test_flask_imported_owners.py``.
    """
    (tmp_path / "blueprints.py").write_text(
        "from flask import Blueprint\nbp = Blueprint('bp', __name__)\n", encoding="utf-8"
    )
    routes = await _routes_in_file(
        tmp_path,
        "from blueprints import bp\n\n@bp.get('/x')\ndef x():\n    pass\n\n"
        "@bp.route('/y')\ndef y():\n    pass\n",
    )
    assert sorted(r["name"] for r in routes) == ["x", "y"]

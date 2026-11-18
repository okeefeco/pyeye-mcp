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

"""Flask plugin finds what it used to silently miss (#873).

Each case used to return a confident ``[]`` (or a partial list) where the
project had the thing: ``async def`` handlers, ``<module>.Blueprint(...)`` and
annotated blueprint assignments, and config files outside the main project
when a ``packages`` or ``package:`` scope was asked for.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pyeye.plugins.flask import FlaskPlugin


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# --- async handlers ---------------------------------------------------------


@pytest.mark.asyncio
async def test_async_route_is_found(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.py",
        "from flask import Flask\napp = Flask(__name__)\n\n"
        "@app.route('/sync')\ndef sync_view():\n    return ''\n\n"
        "@app.route('/async', methods=['POST'])\nasync def async_view():\n    return ''\n",
    )
    routes = await FlaskPlugin(tmp_path.as_posix()).find_routes()
    by_name = {r["name"]: r for r in routes}
    assert set(by_name) == {"sync_view", "async_view"}
    assert by_name["async_view"]["path"] == "/async"
    assert by_name["async_view"]["methods"] == ["POST"]
    assert by_name["async_view"]["line"] == 9


@pytest.mark.asyncio
async def test_async_error_handler_is_found(tmp_path: Path) -> None:
    _write(
        tmp_path / "errors.py",
        "from flask import Flask\napp = Flask(__name__)\n\n"
        "@app.errorhandler(404)\nasync def not_found(e):\n    return ''\n",
    )
    handlers = await FlaskPlugin(tmp_path.as_posix()).find_error_handlers()
    assert [(h["name"], h["error_code"]) for h in handlers] == [("not_found", 404)]


@pytest.mark.asyncio
async def test_async_cli_command_is_found(tmp_path: Path) -> None:
    _write(
        tmp_path / "cli.py",
        "from flask import Flask\napp = Flask(__name__)\n\n"
        "@app.cli.command('seed')\nasync def seed_db():\n    pass\n",
    )
    commands = await FlaskPlugin(tmp_path.as_posix()).find_cli_commands()
    assert [(c["name"], c["function"]) for c in commands] == [("seed", "seed_db")]


# --- blueprints -------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "source",
    [
        "import flask\nbp = flask.Blueprint('admin', __name__, url_prefix='/admin')\n",
        "import flask as f\nbp = f.Blueprint('admin', __name__, url_prefix='/admin')\n",
        "from flask import Blueprint\n"
        "bp: Blueprint = Blueprint('admin', __name__, url_prefix='/admin')\n",
        "import flask\nbp: flask.Blueprint = flask.Blueprint('admin', __name__, url_prefix='/admin')\n",
    ],
    ids=["flask.Blueprint", "alias.Blueprint", "annotated", "annotated-attribute"],
)
async def test_blueprint_spellings_are_found(tmp_path: Path, source: str) -> None:
    _write(tmp_path / "admin.py", source)
    blueprints = await FlaskPlugin(tmp_path.as_posix()).find_blueprints()
    assert [(b["name"], b["blueprint_name"], b["url_prefix"], b["line"]) for b in blueprints] == [
        ("bp", "admin", "/admin", 2)
    ]


@pytest.mark.asyncio
async def test_annotation_without_a_value_is_not_a_blueprint(tmp_path: Path) -> None:
    _write(tmp_path / "admin.py", "from flask import Blueprint\nbp: Blueprint\n")
    assert await FlaskPlugin(tmp_path.as_posix()).find_blueprints() == []


@pytest.mark.asyncio
async def test_other_calls_named_like_blueprint_attributes_are_not_blueprints(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "x.py", "import flask\nbp = flask.make_blueprint('admin')  # Blueprint\n")
    assert await FlaskPlugin(tmp_path.as_posix()).find_blueprints() == []


# --- config files follow scope ----------------------------------------------


def _config_files(configs: list[dict]) -> list[str]:
    return sorted(c["file"] for c in configs if c["type"] == "config_file")


@pytest.fixture
def project_with_package(tmp_path: Path) -> tuple[Path, Path]:
    main = tmp_path / "main"
    _write(main / "config.py", "DEBUG = True\n")
    _write(main / "app" / "settings.py", "X = 1\n")
    _write(main / "app" / "deep" / "config.py", "# depth 2: not a config file\n")
    pkg = tmp_path / "shared"
    _write(pkg / "config.py", "Y = 2\n")
    _write(pkg / "sub" / "settings.py", "Z = 3\n")
    _write(pkg / "sub" / "deeper" / "settings.py", "# depth 2\n")
    return main, pkg


@pytest.mark.asyncio
async def test_main_scope_config_files_are_unchanged(
    project_with_package: tuple[Path, Path],
) -> None:
    """Depth <= 1 from the project root, and never a configured package's files."""
    main, pkg = project_with_package
    plugin = FlaskPlugin(main.as_posix())
    plugin.set_additional_paths([pkg])
    assert _config_files(await plugin.find_config()) == [
        (main / "app" / "settings.py").as_posix(),
        (main / "config.py").as_posix(),
    ]


@pytest.mark.asyncio
async def test_packages_scope_searches_the_packages(
    project_with_package: tuple[Path, Path],
) -> None:
    main, pkg = project_with_package
    plugin = FlaskPlugin(main.as_posix())
    plugin.set_additional_paths([pkg])
    assert _config_files(await plugin.find_config(scope="packages")) == [
        (pkg / "config.py").as_posix(),
        (pkg / "sub" / "settings.py").as_posix(),
    ]


@pytest.mark.asyncio
async def test_package_scope_searches_that_directory(
    project_with_package: tuple[Path, Path],
) -> None:
    main, pkg = project_with_package
    plugin = FlaskPlugin(main.as_posix())
    configs = await plugin.find_config(scope=f"package:{pkg.as_posix()}")
    assert _config_files(configs) == [
        (pkg / "config.py").as_posix(),
        (pkg / "sub" / "settings.py").as_posix(),
    ]


@pytest.mark.asyncio
async def test_overlapping_scopes_report_a_config_file_once(
    project_with_package: tuple[Path, Path],
) -> None:
    main, _ = project_with_package
    plugin = FlaskPlugin(main.as_posix())
    configs = await plugin.find_config(scope=["main", f"package:{(main / 'app').as_posix()}"])
    assert _config_files(configs) == [
        (main / "app" / "deep" / "config.py").as_posix(),
        (main / "app" / "settings.py").as_posix(),
        (main / "config.py").as_posix(),
    ]

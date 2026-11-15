"""Regression tests for #622: plugins must not depend on AST nodes removed in Python 3.14.

Python 3.14 removed ``ast.Str``, ``ast.Num``, ``ast.Bytes``, ``ast.NameConstant`` and
``ast.Ellipsis``. The Flask plugin referenced them inside per-file ``except Exception``
blocks, so on 3.14 every reference raised ``AttributeError``, the file was skipped, and
the tools returned *empty results* instead of failing.

CI runs on Python versions where those names still exist, so these tests simulate 3.14
by swapping each plugin module's ``ast`` global for a copy of :mod:`ast` without them.
Under the old code the string-literal paths below returned empty or incomplete results.
"""

import ast
import re
import types
from pathlib import Path

import pytest

import pyeye.plugins.flask as flask_module
import pyeye.plugins.pydantic as pydantic_module
from pyeye.plugins.flask import FlaskPlugin
from pyeye.plugins.pydantic import PydanticPlugin

REMOVED_AST_NODES = ("Str", "Num", "Bytes", "NameConstant", "Ellipsis")

SRC_DIR = Path(__file__).resolve().parents[3] / "src"


def _ast_without_removed_nodes() -> types.ModuleType:
    """Return a stand-in for the ``ast`` module as it looks on Python 3.14+."""
    shim = types.ModuleType("ast")
    for name, value in vars(ast).items():
        if name in REMOVED_AST_NODES or name == "__getattr__":
            continue
        setattr(shim, name, value)
    return shim


@pytest.fixture
def py314_ast(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    """Make the plugin modules see an ``ast`` module without the removed node classes."""
    shim = _ast_without_removed_nodes()
    for name in REMOVED_AST_NODES:
        assert not hasattr(shim, name), f"shim still exposes ast.{name}"
    monkeypatch.setattr(flask_module, "ast", shim)
    monkeypatch.setattr(pydantic_module, "ast", shim)
    return shim


FLASK_APP = """
from flask import Flask, Blueprint, render_template

app = Flask(__name__)
api = Blueprint('api', __name__, url_prefix='/api')
PREFIX = '/dyn'


@app.route('/users', methods=['GET', 'POST'])
def users():
    return render_template('users/list.html')


@app.route(f'{PREFIX}/x')
def dynamic():
    return 'dynamic route path is not a str constant'


@app.route('/after-dynamic')
def after_dynamic():
    return 'same file as the f-string route'


@app.errorhandler(404)
def not_found(e):
    return 'nope', 404


@app.errorhandler(ValueError)
def bad_value(e):
    return 'bad', 400


@app.cli.command('seed-db')
def seed():
    pass
"""


@pytest.fixture
def flask_project(tmp_path: Path) -> Path:
    (tmp_path / "app.py").write_text(FLASK_APP)
    return tmp_path


class TestFlaskStringLiteralPathsWithoutRemovedNodes:
    """Every string-literal path that used ``ast.Str`` returns results on a 3.14-shaped ``ast``."""

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("py314_ast")
    async def test_routes_paths_and_methods(self, flask_project: Path) -> None:
        routes = await FlaskPlugin(str(flask_project)).find_routes()
        by_name = {r["name"]: r for r in routes}

        assert by_name["users"]["path"] == "/users"
        assert by_name["users"]["methods"] == ["GET", "POST"]
        assert by_name["after_dynamic"]["path"] == "/after-dynamic"
        # A non-literal path is not a route we can name, but it must not hide the others.
        assert "dynamic" not in by_name

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("py314_ast")
    async def test_blueprint_name_and_prefix(self, flask_project: Path) -> None:
        blueprints = await FlaskPlugin(str(flask_project)).find_blueprints()

        assert blueprints == [
            {
                "name": "api",
                "blueprint_name": "api",
                "file": (flask_project / "app.py").as_posix(),
                "line": 5,
                "url_prefix": "/api",
                "type": "blueprint",
            }
        ]

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("py314_ast")
    async def test_render_template_name(self, flask_project: Path) -> None:
        result = await FlaskPlugin(str(flask_project)).find_templates()

        assert [c["template"] for c in result[0]["render_calls"]] == ["users/list.html"]

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("py314_ast")
    async def test_error_handler_codes(self, flask_project: Path) -> None:
        handlers = await FlaskPlugin(str(flask_project)).find_error_handlers()

        assert {h["name"]: h["error_code"] for h in handlers} == {
            "not_found": 404,
            "bad_value": "ValueError",
        }

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("py314_ast")
    async def test_cli_command_name(self, flask_project: Path) -> None:
        commands = await FlaskPlugin(str(flask_project)).find_cli_commands()

        assert [(c["name"], c["function"]) for c in commands] == [("seed-db", "seed")]


class TestPydanticValidatorFieldsWithoutRemovedNodes:
    @pytest.mark.asyncio
    @pytest.mark.usefixtures("py314_ast")
    async def test_validator_fields_with_non_literal_arg(self, tmp_path: Path) -> None:
        (tmp_path / "models.py").write_text("""
from pydantic import BaseModel, field_validator

FIELD = 'email'


class User(BaseModel):
    name: str
    email: str

    @field_validator('name', FIELD)
    def check(cls, v):
        return v
""")
        validators = await PydanticPlugin(str(tmp_path)).find_validators()

        assert [(v["name"], v["fields"]) for v in validators] == [("check", ["name"])]


class TestFlaskErrorContract:
    """Unparseable user code is still skipped; analysis bugs are no longer swallowed."""

    @pytest.mark.asyncio
    async def test_syntax_error_file_is_skipped_others_still_found(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        (tmp_path / "broken.py").write_text("@app.route('/x'\ndef f(:\n")
        (tmp_path / "app.py").write_text(FLASK_APP)

        routes = await FlaskPlugin(str(tmp_path)).find_routes()

        assert {r["path"] for r in routes} == {"/users", "/after-dynamic"}
        assert any("broken.py" in rec.getMessage() for rec in caplog.records)

    @pytest.mark.asyncio
    async def test_undecodable_file_is_skipped(self, tmp_path: Path) -> None:
        (tmp_path / "latin1.py").write_bytes(b"# \xff\xfe route @\n")
        (tmp_path / "app.py").write_text(FLASK_APP)

        routes = await FlaskPlugin(str(tmp_path)).find_routes()

        assert {r["path"] for r in routes} == {"/users", "/after-dynamic"}

    @pytest.mark.parametrize(
        "tool",
        [
            "find_routes",
            "find_blueprints",
            "find_views",
            "find_templates",
            "find_extensions",
            "find_config",
            "find_error_handlers",
            "find_cli_commands",
        ],
    )
    @pytest.mark.asyncio
    async def test_analysis_errors_propagate_instead_of_returning_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: str
    ) -> None:
        """An AST-API change (e.g. a removed node class) must surface, not read as 'none found'."""
        (tmp_path / "app.py").write_text(
            FLASK_APP
            + "\nfrom flask_login import LoginManager\napp.config['DEBUG'] = True\n"
            + "from flask.views import MethodView\nclass V(MethodView):\n    pass\n"
        )
        shim = _ast_without_removed_nodes()

        def broken_walk(_node: ast.AST) -> object:
            raise AttributeError("module 'ast' has no attribute 'Str'")

        shim.walk = broken_walk  # type: ignore[attr-defined]
        monkeypatch.setattr(flask_module, "ast", shim)

        with pytest.raises(AttributeError, match="no attribute 'Str'"):
            await getattr(FlaskPlugin(str(tmp_path)), tool)()


def test_no_removed_ast_nodes_referenced_in_src() -> None:
    """Guard: nothing under ``src/`` references an AST node class removed in Python 3.14."""
    pattern = re.compile(r"\bast\.(?:" + "|".join(REMOVED_AST_NODES) + r")\b")
    offenders = [
        f"{path.relative_to(SRC_DIR).as_posix()}:{lineno}: {line.strip()}"
        for path in sorted(SRC_DIR.rglob("*.py"))
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if pattern.search(line)
    ]
    assert offenders == [], "removed ast nodes referenced:\n" + "\n".join(offenders)

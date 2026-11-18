"""``find_cli_commands`` reads ``.cli.command`` with or without parentheses (#980).

``@app.cli.command`` (bare) is as valid in Flask and Click as
``@app.cli.command()``, and on a blueprint as on the app. The bare form used to
be missed silently: an absent command read as "no command".
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pyeye.plugins.flask import FlaskPlugin


async def _commands(root: Path) -> list[tuple[str, str]]:
    found = await FlaskPlugin(str(root)).find_cli_commands()
    return sorted((c["name"], c["function"]) for c in found)


@pytest.mark.asyncio
async def test_bare_and_called_forms_on_app_and_blueprint(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text(
        "from flask import Blueprint, Flask\n\n"
        "app = Flask(__name__)\n"
        "bp = Blueprint('admin', __name__)\n\n"
        "@app.cli.command\n"
        "def bare_app():\n    pass\n\n"
        "@app.cli.command()\n"
        "def called_app():\n    pass\n\n"
        "@bp.cli.command\n"
        "def bare_blueprint():\n    pass\n\n"
        "@bp.cli.command('reindex')\n"
        "def named_blueprint():\n    pass\n",
        encoding="utf-8",
    )

    assert await _commands(tmp_path) == [
        ("bare_app", "bare_app"),
        ("bare_blueprint", "bare_blueprint"),
        ("called_app", "called_app"),
        ("reindex", "named_blueprint"),
    ]


@pytest.mark.asyncio
async def test_a_bare_command_is_named_by_its_function(tmp_path: Path) -> None:
    """No call means no name argument: the function's name is the command's."""
    (tmp_path / "manage.py").write_text(
        "from flask import Flask\n\napp = Flask(__name__)\n\n"
        "@app.cli.command\n"
        "async def warm_cache():\n    pass\n",
        encoding="utf-8",
    )

    assert await _commands(tmp_path) == [("warm_cache", "warm_cache")]


@pytest.mark.asyncio
async def test_other_command_decorators_are_unchanged(tmp_path: Path) -> None:
    """``@click.command`` stays out; a bare ``@command`` stays in."""
    (tmp_path / "cli.py").write_text(
        "import click\nfrom click import command\nfrom flask import Flask\n\n"
        "app = Flask(__name__)\n\n"
        "@click.command\n"
        "def via_click():\n    pass\n\n"
        "@command\n"
        "def imported():\n    pass\n\n"
        "@app.command\n"
        "def not_cli():\n    pass\n",
        encoding="utf-8",
    )

    assert await _commands(tmp_path) == [("imported", "imported")]

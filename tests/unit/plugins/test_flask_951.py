"""Silent misses in the Flask plugin, found by a docs review (#951).

Each test is a case the plugin used to drop or double-count while its docs
promised the whole set: every render_template call, the MethodView
subclasses, app.config access through an attribute, and each template once.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from pyeye.plugins.flask import FlaskPlugin

_APP = """
import flask
import flask.views as fv
from flask import Flask, render_template, render_template as rt, current_app
from flask.views import MethodView, MethodView as MV

app = Flask(__name__)


def a():
    return render_template("a.html")


def b():
    return flask.render_template("b.html")


def c():
    return rt("c.html")


def d():
    return render_template(template_name_or_list="d.html")


def not_flask(render_template):
    return render_template.render("x.html")


class Base(MethodView):
    pass


class Child(Base):
    pass


class Aliased(MV):
    pass


class Qualified(fv.MethodView):
    pass


class Service:
    def __init__(self, app):
        self.app = app

    def read(self):
        return self.app.config["A"], flask.current_app.config["B"], current_app.config["C"]


DEBUG = app.config["DEBUG"]
"""

_FAKE = '''
class MethodView:
    """A local class that merely shares the name."""


class NotAView(MethodView):
    pass


def render_template(name):
    return name


def e():
    return render_template("e.html")
'''


@pytest.fixture
def project(tmp_path: Path) -> Path:
    pkg = tmp_path / "app"
    (pkg / "templates").mkdir(parents=True)
    (pkg / "__init__.py").write_text(_APP)
    (tmp_path / "fake.py").write_text(_FAKE)
    for name in ("a", "b", "c", "d"):
        (pkg / "templates" / f"{name}.html").write_text("x")
    return tmp_path


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


def test_every_render_template_form_is_found(project: Path) -> None:
    result = _run(FlaskPlugin(project).find_templates())[0]

    # Bare, module-qualified, aliased and keyword forms; a local function that
    # merely shares the name (fake.py) isn't Flask's.
    assert sorted(r["template"] for r in result["render_calls"]) == [
        "a.html",
        "b.html",
        "c.html",
        "d.html",
    ]


def test_each_template_is_listed_once(project: Path) -> None:
    result = _run(FlaskPlugin(project).find_templates())[0]

    files = [t["file"] for t in result["templates"]]
    assert len(files) == len(set(files)) == 4


def test_method_views_follow_imports_and_the_class_graph(project: Path) -> None:
    views = _run(FlaskPlugin(project).find_views())

    # Child subclasses a project MethodView; Aliased and Qualified name Flask's
    # through an alias and a module. fake.NotAView's base is a local class.
    assert sorted(v["name"] for v in views) == ["Aliased", "Base", "Child", "Qualified"]
    assert all(v["type"] == "method_view" for v in views)


def test_config_access_through_an_attribute_receiver(project: Path) -> None:
    configs = _run(FlaskPlugin(project).find_config())

    lines = sorted(c["line"] for c in configs if c["type"] == "config_access")
    source = (project / "app" / "__init__.py").read_text().splitlines()
    read_line = next(i for i, text in enumerate(source, 1) if "self.app.config" in text)
    debug_line = next(i for i, text in enumerate(source, 1) if text.startswith("DEBUG ="))
    # self.app.config, flask.current_app.config and current_app.config on one
    # line, plus the module-level app.config.
    assert lines == [read_line, read_line, read_line, debug_line]

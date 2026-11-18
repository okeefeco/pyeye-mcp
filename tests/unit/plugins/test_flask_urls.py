"""Routes' served ``urls`` and blueprints' ``url_prefixes``, composed as Flask does (#952).

Flask's rules: a ``register_blueprint(bp, url_prefix=...)`` prefix overrides
the blueprint's constructor prefix; a nested blueprint's prefix joins its
parent's; a route's rule joins its blueprint's prefix. Lists throughout, sorted
and deduped. Both fields are present only when EVERY registration's prefix is
statically known, never partial.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from pyeye.plugins.flask import FlaskPlugin

_FILES = {
    "app/__init__.py": """
from flask import Flask
from .admin import admin_bp
from .api import api
from .twice import tw
from .dynamic import dyn

app = Flask(__name__)
app.register_blueprint(admin_bp)
app.register_blueprint(api, url_prefix="/api/v1")
app.register_blueprint(tw, url_prefix="/a")
app.register_blueprint(tw, url_prefix="/b", name="tw2")
app.register_blueprint(dyn)


@app.route("/health")
def health():
    return "ok"
""",
    "app/admin.py": """
from flask import Blueprint

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


@admin_bp.route("/")
def dashboard():
    return ""


@admin_bp.route("/users")
def users():
    return ""
""",
    "app/api.py": """
from flask import Blueprint

api = Blueprint("api", __name__, url_prefix="/overridden")
child = Blueprint("child", __name__, url_prefix="/c")
api.register_blueprint(child)


@api.route("")
def root():
    return ""


@child.route("/x")
def x():
    return ""
""",
    "app/twice.py": """
from flask import Blueprint

tw = Blueprint("tw", __name__)


@tw.route("/r")
def r():
    return ""
""",
    "app/dynamic.py": """
from flask import Blueprint

PREFIX = "/dyn"
dyn = Blueprint("dyn", __name__, url_prefix=PREFIX)


@dyn.route("/d")
def d():
    return ""
""",
    "app/lone.py": """
from flask import Blueprint

lone = Blueprint("lone", __name__, url_prefix="/lone")


@lone.route("/l")
def l():
    return ""
""",
}


@pytest.fixture
def project(tmp_path: Path) -> Path:
    for rel, source in _FILES.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)
    return tmp_path


def _routes(project: Path) -> dict[str, dict]:
    return {r["name"]: r for r in asyncio.run(FlaskPlugin(project).find_routes())}


def _blueprints(project: Path) -> dict[str, dict]:
    return {b["name"]: b for b in asyncio.run(FlaskPlugin(project).find_blueprints())}


def test_route_urls_follow_flasks_composition(project: Path) -> None:
    routes = _routes(project)

    assert routes["health"]["urls"] == ["/health"]  # an app route: its own path
    assert routes["dashboard"]["urls"] == ["/admin/"]  # the constructor prefix
    assert routes["users"]["urls"] == ["/admin/users"]
    assert routes["root"]["urls"] == ["/api/v1"]  # register-time prefix overrides; empty rule
    assert routes["x"]["urls"] == ["/api/v1/c/x"]  # nested: parent prefix + child prefix
    assert routes["r"]["urls"] == ["/a/r", "/b/r"]  # registered twice: both, sorted


def test_path_is_unchanged(project: Path) -> None:
    routes = _routes(project)

    assert routes["dashboard"]["path"] == "/" and routes["x"]["path"] == "/x"


@pytest.mark.parametrize("name", ["d", "l"], ids=["dynamic_prefix", "never_registered"])
def test_urls_are_omitted_when_not_statically_known(project: Path, name: str) -> None:
    assert "urls" not in _routes(project)[name]


def test_blueprint_url_prefixes(project: Path) -> None:
    blueprints = _blueprints(project)

    assert blueprints["admin_bp"]["url_prefixes"] == ["/admin"]
    assert blueprints["api"]["url_prefixes"] == ["/api/v1"]
    assert blueprints["child"]["url_prefixes"] == ["/api/v1/c"]
    assert blueprints["tw"]["url_prefixes"] == ["/a", "/b"]
    assert "url_prefixes" not in blueprints["dyn"]
    assert "url_prefixes" not in blueprints["lone"]
    # The constructor's literal stays where it was.
    assert blueprints["api"]["url_prefix"] == "/overridden"


@pytest.mark.parametrize(
    "registration",
    [
        'app.register_blueprint(bp, url_prefix="/known")\napp.register_blueprint(bp, url_prefix=P)\n',
        'app.register_blueprint(bp, subdomain="api")\n',
        "app.register_blueprint(bp, **OPTIONS)\n",
    ],
    ids=["one_known_one_dynamic", "subdomain", "splat"],
)
def test_any_unknown_registration_omits_both(tmp_path: Path, registration: str) -> None:
    (tmp_path / "m.py").write_text(
        "from flask import Flask, Blueprint\n"
        "P = '/p'\nOPTIONS = {}\n"
        "app = Flask(__name__)\n"
        "bp = Blueprint('bp', __name__)\n"
        "@bp.route('/z')\ndef z():\n    return ''\n" + registration
    )

    assert "urls" not in _routes(tmp_path)["z"]
    assert "url_prefixes" not in _blueprints(tmp_path)["bp"]


def test_a_registration_cycle_omits_both(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text(
        "from flask import Blueprint\n"
        "a = Blueprint('a', __name__, url_prefix='/a')\n"
        "b = Blueprint('b', __name__, url_prefix='/b')\n"
        "a.register_blueprint(b)\nb.register_blueprint(a)\n"
        "@a.route('/q')\ndef q():\n    return ''\n"
    )

    assert "urls" not in _routes(tmp_path)["q"]
    assert "url_prefixes" not in _blueprints(tmp_path)["a"]

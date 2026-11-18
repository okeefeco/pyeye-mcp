"""Plugin results carry canonical handles, scope and an absolute location (#627).

Framework plugins walk their own ASTs and returned ``{name, file, line}`` only: no
handle (so a result couldn't be passed to ``inspect`` without an ambiguous
``resolve(name)``), no scope, and paths relative to wherever the server started.

Every plugin result now also carries:

- ``location``: the primitives' ``Location`` shape. For a placed symbol it equals
  ``inspect(handle)["location"]``; otherwise the ``{file, line_start, line_end}``
  (or ``{file}``) subset. ``file`` is an absolute posix path;
- ``scope``: ``"project"`` or ``"external"``;
- for a result that names a symbol, ``handle`` from ``pyeye.resolver.resolve_handle``
  (the one canonical resolver), or, when the resolver can't place it,
  ``unresolved: {reason, detail}`` and **no** handle. Never a fabricated handle.

``name``, ``file`` and ``line`` are unchanged (additive in 2.x), except that
``find_flask_config``'s ``line`` becomes the int every other tool returns (Fixed).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from mcp.server.mcpserver import MCPServer

import pyeye.project_manager as project_manager_module
from pyeye.config import ProjectConfig
from pyeye.mcp import server
from pyeye.mcp.server import register_plugin_tools
from pyeye.plugins.base import AnalyzerPlugin
from pyeye.plugins.django import DjangoPlugin
from pyeye.plugins.flask import FlaskPlugin
from pyeye.plugins.pydantic import PydanticPlugin
from pyeye.project_manager import ProjectManager
from pyeye.scope_utils import SmartScopeResolver
from tests.utils.performance import PerformanceThresholds, assert_performance_threshold

ADDED_KEYS = {"location", "scope", "handle", "unresolved"}

FILES: dict[str, str] = {
    "shop/__init__.py": "from shop._models import Product\n",
    "shop/_models.py": """\
from pydantic import BaseModel, computed_field, field_validator


class Product(BaseModel):
    title: str
    model_config = {"frozen": True}

    @field_validator("title")
    def check_title(cls, v):
        return v

    @computed_field
    @property
    def slug(self) -> str:
        return self.title.lower()


class Order(BaseModel):
    qty: int

    class Config:
        extra = "forbid"
""",
    "app.py": """\
from flask import Flask, Blueprint, render_template
from flask_login import LoginManager
from flask.views import MethodView

app = Flask(__name__)
bp = Blueprint("bp", __name__, url_prefix="/bp")
app.config["DEBUG"] = True


@app.route("/")
def index():
    return render_template("index.html")


@app.errorhandler(404)
def missing(e):
    return "x", 404


@app.cli.command("seed")
def seed_db():
    pass


class ItemView(MethodView):
    pass


def create_app():
    inner = Flask(__name__)

    @inner.route("/inner")
    def nested_route():
        return "nested"

    return inner
""",
    "blog/__init__.py": "",
    "blog/models.py": """\
from django.db import models


class Post(models.Model):
    title = models.CharField(max_length=10)
""",
    "blog/views.py": """\
from django.views import View


def post_list(request):
    pass


class PostView(View):
    pass
""",
    "blog/urls.py": "urlpatterns = []\n",
}


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    for rel, text in FILES.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    (root / "templates").mkdir()
    (root / "templates" / "index.html").write_text("<p/>")
    return root


@pytest.fixture
def isolated_manager(monkeypatch: pytest.MonkeyPatch) -> Iterator[ProjectManager]:
    m = ProjectManager(max_projects=10)
    monkeypatch.setattr(project_manager_module, "_project_manager", m)
    yield m
    m.cleanup_all()


def _plugins(root: Path) -> list[AnalyzerPlugin]:
    return [cls(str(root)) for cls in (PydanticPlugin, DjangoPlugin, FlaskPlugin)]


def _server(root: Path) -> MCPServer:
    s = MCPServer("handles")
    register_plugin_tools(s, _plugins(root), SmartScopeResolver(ProjectConfig(str(root))))
    return s


async def _call(s: MCPServer, tool: str, **args: Any) -> Any:
    result = await s.call_tool(tool, args)
    assert not result.is_error, result.content
    items = [json.loads(c.text) for c in result.content]
    return items


def _records(tool: str, payload: Any) -> list[dict[str, Any]]:
    """Every result record of a tool's answer, however the tool nests them."""
    if tool in ("get_model_schema", "trace_model_inheritance"):
        top = payload[0] if isinstance(payload, list) else payload
        return [top, *top.get("children", [])]
    if tool == "find_flask_templates":
        top = payload[0] if isinstance(payload, list) else payload
        if isinstance(top, list):
            top = top[0]
        return [*top["templates"], *top["render_calls"]]
    return list(payload)


def _by(records: list[dict[str, Any]], key: str, value: str) -> dict[str, Any]:
    matches = [r for r in records if r.get(key) == value]
    assert len(matches) == 1, (key, value, records)
    return matches[0]


EXTRA_ARGS = {
    "get_model_schema": {"model_name": "Product"},
    "trace_model_inheritance": {"model_name": "Product"},
}


@pytest.mark.usefixtures("isolated_manager")
class TestSymbolHandles:
    """Each symbol result's handle is canonical and round-trips through inspect."""

    @pytest.mark.parametrize(
        ("tool", "key", "value", "expected_handle"),
        [
            ("find_pydantic_models", "name", "Product", "shop._models.Product"),
            ("find_pydantic_models", "name", "Order", "shop._models.Order"),
            ("find_validators", "name", "check_title", "shop._models.Product.check_title"),
            ("find_field_validators", "name", "check_title", "shop._models.Product.check_title"),
            ("find_computed_fields", "name", "slug", "shop._models.Product.slug"),
            ("find_model_config", "model", "Order", "shop._models.Order"),
            ("find_model_config", "model", "Product", "shop._models.Product"),
            ("get_model_schema", "model", "Product", "shop._models.Product"),
            ("trace_model_inheritance", "model", "Product", "shop._models.Product"),
            ("find_django_models", "name", "Post", "blog.models.Post"),
            ("find_django_views", "name", "post_list", "blog.views.post_list"),
            ("find_django_views", "name", "PostView", "blog.views.PostView"),
            ("find_flask_routes", "name", "index", "app.index"),
            ("find_flask_blueprints", "name", "bp", "app.bp"),
            ("find_flask_views", "name", "ItemView", "app.ItemView"),
            ("find_error_handlers", "name", "missing", "app.missing"),
            ("find_cli_commands", "function", "seed_db", "app.seed_db"),
        ],
    )
    async def test_handle_is_canonical_and_inspectable(
        self, project: Path, tool: str, key: str, value: str, expected_handle: str
    ) -> None:
        payload = await _call(_server(project), tool, scope="main", **EXTRA_ARGS.get(tool, {}))
        # One record per symbol: find_computed_fields no longer repeats a property
        # once per matching decorator (@computed_field + @property, #672).
        records = [r for r in _records(tool, payload) if r.get(key) == value]
        assert len(records) == 1, records
        record = records[0]
        assert record["handle"] == expected_handle
        assert record["scope"] == "project"
        assert "unresolved" not in record
        inspected = await server.inspect(record["handle"], project_path=str(project))
        assert inspected.get("found", True) is not False
        assert inspected["handle"] == expected_handle
        # Drift guard: the record's location IS inspect's location (#627).
        assert record["location"] == inspected["location"]

    async def test_reexported_model_gets_the_definition_site_handle(self, project: Path) -> None:
        """``shop.Product`` is a re-export; the canonical handle is where it's defined."""
        payload = await _call(_server(project), "find_pydantic_models", scope="main")

        assert _by(payload, "name", "Product")["handle"] == "shop._models.Product"

    async def test_extension_result_names_the_external_module(self, project: Path) -> None:
        payload = await _call(_server(project), "find_flask_extensions", scope="main")
        record = _by(payload, "extension", "flask_login")

        # flask_login isn't installed in the test env: an honest unresolved, no handle.
        if "handle" in record:
            assert record["handle"] == "flask_login"
            assert record["scope"] == "external"
        else:
            assert record["unresolved"]["reason"] == "unresolved"


@pytest.mark.usefixtures("isolated_manager")
class TestUnplaceableSymbols:
    async def test_route_nested_in_a_factory_is_unresolved_not_fabricated(
        self, project: Path
    ) -> None:
        payload = await _call(_server(project), "find_flask_routes", scope="main")
        record = _by(payload, "name", "nested_route")

        assert "handle" not in record
        assert record["unresolved"]["reason"] == "unresolved"
        assert "nested_route" in record["unresolved"]["detail"]
        # Location and scope are still known: the record's line, as a Location subset.
        assert record["location"] == {
            "file": Path(record["file"]).resolve().as_posix(),
            "line_start": record["line"],
            "line_end": record["line"],
        }
        assert record["scope"] == "project"


@pytest.mark.usefixtures("isolated_manager")
class TestLocationAndScope:
    @pytest.mark.parametrize("tool", ["find_flask_routes", "find_django_urls", "find_flask_config"])
    async def test_every_record_has_an_absolute_location_and_scope(
        self, project: Path, tool: str
    ) -> None:
        payload = await _call(_server(project), tool, scope="main")
        assert payload

        for record in _records(tool, payload):
            assert Path(record["location"]["file"]).is_absolute()
            assert record["location"]["file"] == Path(record["file"]).resolve().as_posix()
            assert record["scope"] == "project"

    async def test_file_only_results_have_no_handle_and_no_unresolved(self, project: Path) -> None:
        """Not a symbol result: neither key, so absence can't be misread as a miss."""
        payload = await _call(_server(project), "find_django_urls", scope="main")
        record = payload[0]

        assert "handle" not in record
        assert "unresolved" not in record
        assert set(record["location"]) == {"file"}

    async def test_template_render_calls_are_located(self, project: Path) -> None:
        payload = await _call(_server(project), "find_flask_templates", scope="main")
        records = _records("find_flask_templates", payload)

        call = _by(records, "template", "index.html")
        assert call["location"]["line_start"] == call["line"] == call["location"]["line_end"]
        assert "handle" not in call


@pytest.mark.usefixtures("isolated_manager")
class TestUnchangedFieldsAndFixes:
    @pytest.mark.parametrize(
        "tool",
        [
            "find_pydantic_models",
            "find_validators",
            "find_model_config",
            "find_computed_fields",
            "find_django_models",
            "find_django_views",
            "find_django_urls",
            "find_flask_routes",
            "find_flask_blueprints",
            "find_flask_views",
            "find_flask_extensions",
            "find_error_handlers",
            "find_cli_commands",
        ],
    )
    async def test_existing_fields_are_byte_for_byte_unchanged(
        self, project: Path, tool: str
    ) -> None:
        plugins = _plugins(project)
        method = next(p.register_tools()[tool] for p in plugins if tool in p.register_tools())
        raw = json.loads(json.dumps(await method(scope="main")))

        payload = await _call(_server(project), tool, scope="main")

        stripped = [{k: v for k, v in r.items() if k not in ADDED_KEYS} for r in payload]
        assert stripped == raw

    async def test_flask_config_line_is_an_int(self, project: Path) -> None:
        payload = await _call(_server(project), "find_flask_config", scope="main")
        accesses = [r for r in payload if r["type"] == "config_access"]

        assert accesses
        assert all(isinstance(r["line"], int) for r in accesses)

    async def test_schema_and_trace_report_where_the_model_is(self, project: Path) -> None:
        s = _server(project)
        for tool in ("get_model_schema", "trace_model_inheritance"):
            top = (await _call(s, tool, scope="main", model_name="Product"))[0]
            assert top["file"].endswith("shop/_models.py")
            assert top["line"] == 4


@pytest.mark.usefixtures("isolated_manager")
class TestEnvelopeAndBareAgree:
    async def test_envelope_results_carry_the_same_enrichment(self, project: Path) -> None:
        s = _server(project)
        bare = await _call(s, "find_pydantic_models", scope="main")
        envelope = (await _call(s, "find_pydantic_models", scope="main", envelope=True))[0]

        assert envelope["results"] == bare


def test_plugins_alias_stays_live_after_initialize(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``PLUGINS`` was bound to the list ``initialize_plugins`` then replaced."""
    # Don't register plugin tools on the module-level server other tests read.
    monkeypatch.setattr(server, "register_plugin_tools", lambda *_a, **_k: [])
    (tmp_path / "app.py").write_text("from flask import Flask\napp = Flask(__name__)\n")
    original = server.PLUGINS
    try:
        server.initialize_plugins(str(tmp_path))
        assert server.PLUGINS is server._plugins
        assert any(p.name() == "Flask" for p in server.PLUGINS)
    finally:
        server._plugins[:] = []
        assert server.PLUGINS is original


#: Enriching every result of a mid-sized project (resolve_handle per symbol).
#: The local base is sized for the load local runs actually see: dev01 runs up to
#: two full suites at once, which pushed this to 4.3-5.2 s (#835). Alone it takes
#: 3.2-3.5 s, so 7000 ms is about 2x the quiet cost. CI values are unchanged.
ENRICH_MANY = PerformanceThresholds(
    base=7000.0, linux_ci=8000.0, macos_ci=12000.0, windows_ci=12000.0
)


@pytest.mark.usefixtures("isolated_manager")
async def test_enrichment_cost_on_many_results(tmp_path: Path) -> None:
    import time

    root = tmp_path / "big"
    pkg = root / "pkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    for i in range(20):
        body = "from pydantic import BaseModel\n\n" + "".join(
            f"\nclass M{i}_{j}(BaseModel):\n    x: int\n" for j in range(10)
        )
        (pkg / f"m{i}.py").write_text(body)
    s = _server(root)

    start = time.perf_counter()
    payload = await _call(s, "find_pydantic_models", scope="main")
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert len(payload) == 200
    assert all("handle" in r for r in payload)
    assert_performance_threshold(elapsed_ms, ENRICH_MANY, "Enrich 200 plugin results")

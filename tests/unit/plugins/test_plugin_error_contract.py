"""Regression tests for #637: plugin failures must not be reported as empty results.

#622/#632 fixed the Flask AST walkers. The same broad ``except Exception`` remained in
the Pydantic and Django AST tools, in ``AnalyzerPlugin.get_project_files``, and in every
plugin's ``detect()``. There an internal error read as "nothing found" (``[]``) or
"not this framework" (``False``).

The contract, shared by every plugin (see the #622 entry in docs/decisions/entries/):

- an unreadable file (``OSError``/``UnicodeDecodeError``) or unparseable source
  (``SyntaxError``/``ValueError``/``RecursionError``) is warned about and skipped;
- any other error propagates.
"""

import ast
import logging
import types
from pathlib import Path
from typing import Any

import pytest

import pyeye.async_utils as async_utils_module
import pyeye.plugins.django as django_module
import pyeye.plugins.flask as flask_module
import pyeye.plugins.pydantic as pydantic_module
from pyeye.mcp import server as server_module
from pyeye.plugins.base import AnalyzerPlugin
from pyeye.plugins.django import DjangoPlugin
from pyeye.plugins.flask import FlaskPlugin
from pyeye.plugins.pydantic import PydanticPlugin

PYDANTIC_SOURCE = """
from pydantic import BaseModel, field_validator, computed_field


class User(BaseModel):
    name: str
    model_config = {"frozen": True}

    class Config:
        extra = "forbid"

    @field_validator("name")
    def check(cls, v):
        return v

    @computed_field
    @property
    def upper(self) -> str:
        return self.name.upper()
"""

DJANGO_MODELS = """
from django.db import models


class Post(models.Model):
    title = models.CharField(max_length=10)
"""

DJANGO_VIEWS = """
from django.views import View


def index(request):
    pass


class PostView(View):
    pass
"""

WALK_ERROR = "simulated AST-API change"


def _ast_with_broken_walk() -> types.ModuleType:
    shim = types.ModuleType("ast")
    for name, value in vars(ast).items():
        setattr(shim, name, value)

    def broken_walk(_node: ast.AST) -> Any:
        raise AttributeError(WALK_ERROR)

    shim.walk = broken_walk  # type: ignore[attr-defined]
    return shim


@pytest.fixture
def pydantic_project(tmp_path: Path) -> Path:
    (tmp_path / "models.py").write_text(PYDANTIC_SOURCE)
    return tmp_path


@pytest.fixture
def django_project(tmp_path: Path) -> Path:
    app = tmp_path / "blog"
    app.mkdir()
    (app / "models.py").write_text(DJANGO_MODELS)
    (app / "views.py").write_text(DJANGO_VIEWS)
    return tmp_path


PYDANTIC_TOOLS = ["find_models", "find_validators", "find_model_config", "find_computed_fields"]
DJANGO_TOOLS = ["find_models", "find_views"]


class TestFixturesProduceResults:
    """Guard the fixtures: each tool finds something, so an empty result can't pass by accident."""

    @pytest.mark.parametrize("tool", PYDANTIC_TOOLS)
    @pytest.mark.asyncio
    async def test_pydantic_tool_finds_results(self, pydantic_project: Path, tool: str) -> None:
        assert await getattr(PydanticPlugin(str(pydantic_project)), tool)()

    @pytest.mark.parametrize("tool", DJANGO_TOOLS)
    @pytest.mark.asyncio
    async def test_django_tool_finds_results(self, django_project: Path, tool: str) -> None:
        assert await getattr(DjangoPlugin(str(django_project)), tool)()


class TestWalkErrorsPropagate:
    @pytest.mark.parametrize("tool", PYDANTIC_TOOLS)
    @pytest.mark.asyncio
    async def test_pydantic(
        self, pydantic_project: Path, monkeypatch: pytest.MonkeyPatch, tool: str
    ) -> None:
        monkeypatch.setattr(pydantic_module, "ast", _ast_with_broken_walk())
        with pytest.raises(AttributeError, match=WALK_ERROR):
            await getattr(PydanticPlugin(str(pydantic_project)), tool)()

    @pytest.mark.parametrize("tool", DJANGO_TOOLS)
    @pytest.mark.asyncio
    async def test_django(
        self, django_project: Path, monkeypatch: pytest.MonkeyPatch, tool: str
    ) -> None:
        monkeypatch.setattr(django_module, "ast", _ast_with_broken_walk())
        with pytest.raises(AttributeError, match=WALK_ERROR):
            await getattr(DjangoPlugin(str(django_project)), tool)()


class TestBrokenUserFilesStillSkipped:
    """The kept half of the contract: broken user code is skipped with a *warning*."""

    @pytest.mark.parametrize("tool", PYDANTIC_TOOLS)
    @pytest.mark.asyncio
    async def test_pydantic(
        self, pydantic_project: Path, caplog: pytest.LogCaptureFixture, tool: str
    ) -> None:
        (pydantic_project / "broken.py").write_text(
            "from pydantic import BaseModel, validator\n@property\nclass Config(:\n"
        )
        (pydantic_project / "latin1.py").write_bytes(b"# \xff BaseModel Config @property\n")
        caplog.set_level(logging.WARNING)

        assert await getattr(PydanticPlugin(str(pydantic_project)), tool)()

        warned = " ".join(r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING)
        assert "broken.py" in warned
        assert "latin1.py" in warned

    @pytest.mark.parametrize("tool", DJANGO_TOOLS)
    @pytest.mark.asyncio
    async def test_django(
        self, django_project: Path, caplog: pytest.LogCaptureFixture, tool: str
    ) -> None:
        other = django_project / "other"
        other.mkdir()
        (other / "models.py").write_text("from django.db import models\nclass X(:\n")
        (other / "views.py").write_text("from django import x\ndef f(:\n")
        caplog.set_level(logging.WARNING)

        assert await getattr(DjangoPlugin(str(django_project)), tool)()

        assert any(
            "other/" in r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING
        )


class TestFileDiscovery:
    @pytest.mark.asyncio
    async def test_discovery_error_propagates(
        self, pydantic_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def broken_rglob(_pattern: str, _path: Path) -> list[Path]:
            raise RuntimeError("discovery broke")

        monkeypatch.setattr(async_utils_module, "rglob_async", broken_rglob)

        with pytest.raises(RuntimeError, match="discovery broke"):
            await PydanticPlugin(str(pydantic_project)).find_models()

    @pytest.mark.asyncio
    async def test_missing_search_path_is_not_an_error(self, tmp_path: Path) -> None:
        plugin = FlaskPlugin(str(tmp_path))
        plugin.set_additional_paths([tmp_path / "does-not-exist"])

        assert await plugin.get_project_files("*.py", "all") == []


def _raise_for(name: str, error: BaseException) -> Any:
    real_read_text = Path.read_text

    def read_text(self: Path, *args: Any, **kwargs: Any) -> str:
        if self.name == name:
            raise error
        return real_read_text(self, *args, **kwargs)

    return read_text


DETECT_CASES = [
    (PydanticPlugin, "models.py", "from pydantic import BaseModel\n"),
    (DjangoPlugin, "requirements.txt", "django==5.0\n"),
    (FlaskPlugin, "app.py", "from flask import Flask\n"),
]


class TestDetection:
    @pytest.mark.parametrize(("plugin_class", "file_name", "source"), DETECT_CASES)
    def test_detects_framework(
        self, tmp_path: Path, plugin_class: type[AnalyzerPlugin], file_name: str, source: str
    ) -> None:
        (tmp_path / file_name).write_text(source)
        assert plugin_class(str(tmp_path)).detect() is True

    @pytest.mark.parametrize(("plugin_class", "file_name", "source"), DETECT_CASES)
    def test_internal_error_propagates_instead_of_false(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        plugin_class: type[AnalyzerPlugin],
        file_name: str,
        source: str,
    ) -> None:
        (tmp_path / file_name).write_text(source)
        monkeypatch.setattr(Path, "read_text", _raise_for(file_name, RuntimeError("detect broke")))

        with pytest.raises(RuntimeError, match="detect broke"):
            plugin_class(str(tmp_path)).detect()

    @pytest.mark.parametrize(("plugin_class", "file_name", "source"), DETECT_CASES)
    def test_unreadable_file_is_skipped_with_warning(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
        plugin_class: type[AnalyzerPlugin],
        file_name: str,
        source: str,
    ) -> None:
        (tmp_path / file_name).write_text(source)
        monkeypatch.setattr(Path, "read_text", _raise_for(file_name, PermissionError("denied")))
        caplog.set_level(logging.WARNING)

        assert plugin_class(str(tmp_path)).detect() is False
        assert any(
            file_name in r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING
        )


class TestPluginLoadFailureIsReported:
    def test_detect_error_is_logged_as_error_with_traceback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        def broken_detect(_self: AnalyzerPlugin) -> bool:
            raise RuntimeError("detect broke")

        monkeypatch.setattr(FlaskPlugin, "detect", broken_detect)
        # register_plugin_tools returns the names it registered (#659 records them).
        monkeypatch.setattr(server_module, "register_plugin_tools", lambda *_a, **_k: [])
        caplog.set_level(logging.WARNING)

        server_module.initialize_plugins(str(tmp_path))

        failures = [r for r in caplog.records if "FlaskPlugin" in r.getMessage()]
        assert failures, "plugin load failure was not reported"
        assert failures[0].levelno == logging.ERROR
        assert failures[0].exc_info is not None


class TestFlaskFrameworkComponents:
    def test_unreadable_file_skipped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        (tmp_path / "views.py").write_text("@app.route('/')\ndef f(): pass\n")
        (tmp_path / "bad.py").write_text("@app.route('/')\n")
        monkeypatch.setattr(Path, "read_text", _raise_for("bad.py", PermissionError("denied")))
        caplog.set_level(logging.WARNING)

        components = FlaskPlugin(str(tmp_path)).get_framework_components()

        assert [Path(p).name for p in components["routes"]] == ["views.py"]
        assert any("bad.py" in r.getMessage() for r in caplog.records)

    def test_internal_error_propagates(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "views.py").write_text("@app.route('/')\ndef f(): pass\n")
        monkeypatch.setattr(Path, "read_text", _raise_for("views.py", RuntimeError("broke")))

        with pytest.raises(RuntimeError, match="broke"):
            FlaskPlugin(str(tmp_path)).get_framework_components()


def test_flask_module_has_no_private_read_helpers() -> None:
    """The read/parse helpers live once, on AnalyzerPlugin, not copied per plugin."""
    for module in (flask_module, pydantic_module, django_module):
        for cls in vars(module).values():
            if (
                isinstance(cls, type)
                and issubclass(cls, AnalyzerPlugin)
                and cls is not AnalyzerPlugin
            ):
                assert "_read_source" not in vars(cls), cls
                assert "_parse_source" not in vars(cls), cls

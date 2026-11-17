"""A relative caller path resolves against project_path, not the server's cwd (#842, #843).

Every test runs with the working directory set to an empty directory that is
NOT the project, the situation a multi-project server is always in. Absolute
paths must be unchanged.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import pytest

from pyeye.path_utils import anchor
from pyeye.scope_utils import ScopeLayout, package_scope_path, resolve_scope_paths

#: A tiny project: ``Cache.evict`` is defined on line 5, its name at column 8.
_FILES = {
    "myapp/__init__.py": "",
    "myapp/cache.py": (
        '"""A small cache."""\n'
        "\n"
        "\n"
        "class Cache:\n"
        "    def evict(self, key: str) -> None:\n"
        "        del key\n"
    ),
    "myapp/db/__init__.py": "",
    "myapp/schemas.py": (
        "from pydantic import BaseModel\n\n\nclass User(BaseModel):\n    name: str\n"
    ),
}
EVICT_LINE = 5


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A small project; cwd is an unrelated empty directory."""
    target = tmp_path / "project"
    for rel, text in _FILES.items():
        (target / rel).parent.mkdir(parents=True, exist_ok=True)
        (target / rel).write_text(text, encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    return target


def _tool(name: str, **args: Any) -> dict[str, Any]:
    from pyeye.mcp.server import mcp

    result = asyncio.run(mcp.call_tool(name, args))
    assert not result.is_error, result.content
    payload = result.structured_content
    assert isinstance(payload, dict)
    return payload


class TestAnchor:
    def test_relative_joins_the_root(self, tmp_path: Path) -> None:
        assert anchor("a/b.py", tmp_path) == tmp_path / "a" / "b.py"

    def test_dot_dot_collapses_lexically(self, tmp_path: Path) -> None:
        assert anchor("a/../b.py", tmp_path / "root") == tmp_path / "root" / "b.py"

    def test_absolute_is_unchanged(self, tmp_path: Path) -> None:
        absolute = tmp_path / "x" / ".." / "y.py"

        assert anchor(absolute, tmp_path / "root") == absolute

    def test_tilde_is_not_expanded(self, tmp_path: Path) -> None:
        assert anchor("~/x.py", tmp_path) == tmp_path / "~" / "x.py"

    def test_the_callers_spelling_is_kept(self, tmp_path: Path) -> None:
        real = tmp_path / "real"
        real.mkdir()
        link = tmp_path / "link"
        try:
            link.symlink_to(real, target_is_directory=True)
        except OSError:
            pytest.skip("symlinks need privileges here")

        assert anchor("a.py", link) == link / "a.py"


class TestResolveAt:
    """#843."""

    def test_a_relative_file_resolves_in_the_project(self, project: Path) -> None:
        result = _tool(
            "resolve_at",
            file="myapp/cache.py",
            line=EVICT_LINE,
            column=8,
            project_path=project.as_posix(),
        )

        assert result["found"] is True
        assert result["handle"] == "myapp.cache.Cache.evict"

    def test_an_absolute_file_is_unchanged(self, project: Path) -> None:
        result = _tool(
            "resolve_at",
            file=(project / "myapp" / "cache.py").as_posix(),
            line=EVICT_LINE,
            column=8,
            project_path=project.as_posix(),
        )

        assert result["handle"] == "myapp.cache.Cache.evict"

    def test_a_missing_relative_file_echoes_the_callers_spelling(self, project: Path) -> None:
        result = _tool(
            "resolve_at", file="myapp/gone.py", line=1, column=0, project_path=project.as_posix()
        )

        assert result["found"] is False
        assert result["reason"] == "file_not_found"
        assert result["file"] == "myapp/gone.py"

    def test_a_file_only_in_the_cwd_is_not_found(self, project: Path) -> None:
        """The cwd must no longer be searched: the same relative path there is ignored."""
        (Path.cwd() / "stray.py").write_text("x = 1\n", encoding="utf-8")

        result = _tool(
            "resolve_at", file="stray.py", line=1, column=0, project_path=project.as_posix()
        )

        assert result["reason"] == "file_not_found"


class TestResolveFileForms:
    """#843 comment: resolve's ``file:line`` and ``file`` forms have the same bug."""

    @pytest.mark.parametrize(
        ("identifier", "handle"),
        [
            (f"myapp/cache.py:{EVICT_LINE}", "myapp.cache.Cache.evict"),
            ("myapp/cache.py", "myapp.cache"),
        ],
    )
    def test_relative_forms_resolve_in_the_project(
        self, project: Path, identifier: str, handle: str
    ) -> None:
        result = _tool("resolve", identifier=identifier, project_path=project.as_posix())

        assert result["found"] is True, result
        assert result["handle"] == handle

    def test_the_echo_keeps_the_callers_spelling(self, project: Path) -> None:
        result = _tool("resolve", identifier="myapp/gone.py:3", project_path=project.as_posix())

        assert result["reason"] == "file_not_found"
        assert result["identifier"] == "myapp/gone.py:3"


class TestPackageScope:
    """#842."""

    def test_a_relative_package_scope_resolves_in_the_project(self, project: Path) -> None:
        layout = ScopeLayout(project_path=project)

        assert resolve_scope_paths("package:myapp/db", layout) == {project / "myapp" / "db"}
        assert package_scope_path("package:myapp/db", layout) == project / "myapp" / "db"

    def test_an_absolute_package_scope_is_unchanged(self, project: Path) -> None:
        layout = ScopeLayout(project_path=project / "myapp")
        absolute = (project / "myapp" / "db").as_posix()

        assert resolve_scope_paths(f"package:{absolute}", layout) == {Path(absolute)}

    def test_a_package_scope_in_the_cwd_is_not_searched(self, project: Path) -> None:
        (Path.cwd() / "lib").mkdir()

        assert resolve_scope_paths("package:lib", ScopeLayout(project_path=project)) == set()

    def test_a_plugin_tool_searches_the_relative_package(self, project: Path) -> None:
        from pyeye.mcp.server import _build_plugin_context
        from pyeye.plugins.pydantic import PydanticPlugin

        plugin = _build_plugin_context(PydanticPlugin, project.as_posix()).plugin
        found = asyncio.run(plugin.find_models(scope="package:myapp"))

        assert [m["name"] for m in found] == ["User"]
        assert os.getcwd() != project.as_posix()
        assert json.dumps(found)  # serialisable, as on the wire

"""A relative caller path resolves against project_path, not the server's cwd (#842, #843).

Every test runs with the working directory set to an empty directory that is
NOT the project, the situation a multi-project server is always in. Absolute
paths must be unchanged.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

import pytest

from pyeye.path_utils import anchor, drive_relative
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


class TestWindowsDriveRelative:
    """``C:foo`` is relative to drive C's cwd: the same trap, on Windows (#852 review)."""

    def test_same_drive_drops_the_drive(self) -> None:
        assert drive_relative(PureWindowsPath("C:foo/bar.py"), PureWindowsPath("C:/proj")) == (
            PureWindowsPath("foo/bar.py")
        )

    def test_drive_letters_compare_case_insensitively(self) -> None:
        assert drive_relative(PureWindowsPath("c:foo"), PureWindowsPath("C:/proj")) == (
            PureWindowsPath("foo")
        )

    def test_another_drive_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="relative to drive C:'s current directory"):
            drive_relative(PureWindowsPath("C:foo"), PureWindowsPath("D:/proj"))

    @pytest.mark.parametrize("path", ["C:/abs/x.py", "foo/x.py", "\\\\server\\share\\x.py"])
    def test_absolute_and_plain_relative_are_unchanged(self, path: str) -> None:
        assert drive_relative(PureWindowsPath(path), PureWindowsPath("D:/proj")) == PureWindowsPath(
            path
        )

    def test_posix_paths_have_no_drive(self) -> None:
        assert drive_relative(PurePosixPath("C:foo"), PurePosixPath("/proj")) == PurePosixPath(
            "C:foo"
        )


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

    def test_dot_dot_is_collapsed_inside_the_project(self, project: Path) -> None:
        result = _tool(
            "resolve_at",
            file="myapp/../myapp/cache.py",
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

    def test_the_envelope_reports_a_relative_package_scope_as_searched(self, project: Path) -> None:
        from pyeye.mcp.server import _build_plugin_context
        from pyeye.plugins.pydantic import PydanticPlugin

        plugin = _build_plugin_context(PydanticPlugin, project.as_posix()).plugin

        searched, unsearched = plugin.describe_scope("package:myapp")

        assert "package:myapp" in searched
        assert "package:myapp" not in unsearched


class TestEnvelopeMissingPackage:
    """#842: a missing package: path is listed in unsearched_scopes, as the caller spelled it."""

    @pytest.mark.parametrize("spec", ["package:not/here", "package:/no/such/dir"])
    def test_a_missing_package_scope_is_unsearched(self, project: Path, spec: str) -> None:
        from pyeye.mcp.server import _build_plugin_context
        from pyeye.plugins.pydantic import PydanticPlugin

        plugin = _build_plugin_context(PydanticPlugin, project.as_posix()).plugin

        searched, unsearched = plugin.describe_scope(spec)

        assert spec in unsearched
        assert spec not in searched

    def test_one_missing_among_several_is_listed_once(self, project: Path) -> None:
        from pyeye.mcp.server import _build_plugin_context
        from pyeye.plugins.pydantic import PydanticPlugin

        plugin = _build_plugin_context(PydanticPlugin, project.as_posix()).plugin

        searched, unsearched = plugin.describe_scope(
            ["package:myapp", "package:gone", "package:gone"]
        )

        assert "package:myapp" in searched
        assert unsearched.count("package:gone") == 1

    def test_the_wire_envelope_lists_it(self, project: Path) -> None:
        from mcp.server.mcpserver import MCPServer

        from pyeye.config import ProjectConfig
        from pyeye.mcp.server import _PLUGIN_CLASSES, register_plugin_tools
        from pyeye.scope_utils import SmartScopeResolver

        server = MCPServer("relative-paths")
        plugins = [cls(project.as_posix()) for cls in _PLUGIN_CLASSES]
        register_plugin_tools(
            server, plugins, SmartScopeResolver(ProjectConfig(project.as_posix()))
        )

        result = asyncio.run(
            server.call_tool(
                "find_pydantic_models",
                {"scope": "package:not/here", "envelope": True, "project_path": project.as_posix()},
            )
        )

        assert not result.is_error
        payload = json.loads(result.content[0].text)
        assert payload["results"] == []
        # main is configured and was not searched; the missing path follows it.
        assert payload["unsearched_scopes"] == ["main", "package:not/here"]

    def test_the_per_call_project_path_envelope(self, project: Path, tmp_path: Path) -> None:
        """#665: plugins registered for another project still anchor on the call's project."""
        from mcp.server.mcpserver import MCPServer

        from pyeye.config import ProjectConfig
        from pyeye.mcp.server import _PLUGIN_CLASSES, register_plugin_tools
        from pyeye.scope_utils import SmartScopeResolver

        startup = tmp_path / "startup"
        startup.mkdir()
        server = MCPServer("relative-paths-per-call")
        register_plugin_tools(
            server,
            [cls(startup.as_posix()) for cls in _PLUGIN_CLASSES],
            SmartScopeResolver(ProjectConfig(startup.as_posix())),
        )

        result = asyncio.run(
            server.call_tool(
                "find_pydantic_models",
                {
                    "scope": ["package:myapp", "package:not/here"],
                    "envelope": True,
                    "project_path": project.as_posix(),
                },
            )
        )

        assert not result.is_error, result.content
        payload = json.loads(result.content[0].text)
        assert [m["name"] for m in payload["results"]] == ["User"]
        assert "package:myapp" in payload["searched"]
        assert payload["unsearched_scopes"][-1] == "package:not/here"


class TestValidatorKeepsRelativePaths:
    """The MCP input validator anchored a relative ``..`` path on the cwd (#852 review)."""

    def test_configure_packages_dot_dot_is_relative_to_the_project(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project = tmp_path / "project"
        project.mkdir()
        (project / "app.py").write_text("", encoding="utf-8")
        lib = tmp_path / "lib" / "libpkg"
        lib.mkdir(parents=True)
        (lib / "__init__.py").write_text("class L:\n    pass\n", encoding="utf-8")
        # Two levels deep, so "../lib" from the cwd is tmp_path/x/lib, not tmp_path/lib.
        cwd = tmp_path / "x" / "y"
        cwd.mkdir(parents=True)
        monkeypatch.chdir(cwd)

        configured = _tool(
            "configure_packages", packages=["../lib"], save=False, project_path=project.as_posix()
        )
        found = _tool("resolve", identifier="libpkg.L", project_path=project.as_posix())

        assert (tmp_path / "lib").as_posix() in configured["packages"]
        assert found["handle"] == "libpkg.L"

    def test_the_validator_returns_a_relative_path_unchanged(self) -> None:
        from pyeye.validation import PathValidator

        assert PathValidator.validate_path("a/../b.py") == Path("a/../b.py")


#: Either of the validator's two refusals: the given string, or its resolved target.
REFUSED = "suspicious component|restricted location"


def _assert_refused(tool: str, args: dict[str, Any]) -> None:
    """The call is refused: an MCP ``ToolError`` (or a returned error result)."""
    from mcp.server.mcpserver.exceptions import ToolError

    from pyeye.mcp.server import mcp

    try:
        result = asyncio.run(mcp.call_tool(tool, args))
    except ToolError as error:
        assert re.search(REFUSED, str(error)), error
        return
    assert result.is_error, result.content
    assert re.search(REFUSED, str(result.content)), result.content


def _up_to_root(project: Path) -> str:
    """Enough ``..`` to climb from *project* to the filesystem root."""
    return "../" * (len(project.parts) - 1)


@pytest.mark.skipif(os.name == "nt", reason="the deny-list names POSIX system directories")
class TestDenyListSeesTheAnchoredPath:
    """#852 review: keeping relative paths relative must not loosen the deny-list."""

    @pytest.fixture
    def deep_project(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        project = tmp_path / "a" / "b" / "c" / "project"
        (project / "myapp").mkdir(parents=True)
        (project / "myapp" / "__init__.py").write_text("", encoding="utf-8")
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)
        return project

    @pytest.mark.parametrize("target", ["etc", "etc/passwd", "proc/self", "proc/self/environ"])
    def test_the_validator_rejects_a_climb_into_a_system_dir(
        self, deep_project: Path, target: str
    ) -> None:
        from pyeye.exceptions import ValidationError
        from pyeye.validation import PathValidator

        with pytest.raises(ValidationError, match=REFUSED):
            PathValidator.validate_path(
                _up_to_root(deep_project) + target, anchor_root=deep_project
            )

    @pytest.mark.parametrize("target", ["etc", "proc/self"])
    def test_a_tool_call_is_refused(self, deep_project: Path, target: str) -> None:

        _assert_refused(
            "resolve_at",
            {
                "file": _up_to_root(deep_project) + target,
                "line": 1,
                "column": 0,
                "project_path": deep_project.as_posix(),
            },
        )

    def test_configure_packages_is_refused(self, deep_project: Path) -> None:

        _assert_refused(
            "configure_packages",
            {
                "packages": [_up_to_root(deep_project) + "etc"],
                "save": False,
                "project_path": deep_project.as_posix(),
            },
        )

    def test_a_harmless_climb_inside_tmp_still_passes(self, deep_project: Path) -> None:
        from pyeye.validation import PathValidator

        assert PathValidator.validate_path("../../x.py", anchor_root=deep_project) == Path(
            "../../x.py"
        )


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory names")
class TestDirsNamedLikeSystemDirs:
    """#852 re-review: a project dir that ENDS in root/etc is not a system directory."""

    @pytest.mark.parametrize("last", ["root", "etc"])
    def test_a_project_path_ending_in_a_system_name_passes(self, tmp_path: Path, last: str) -> None:
        from pyeye.validation import PathValidator

        project = tmp_path / "repos" / last
        project.mkdir(parents=True)

        assert PathValidator.validate_path(project.as_posix()) == project

    def test_a_package_dot_dot_root_passes(self, tmp_path: Path) -> None:
        from pyeye.validation import PathValidator

        project = tmp_path / "repos" / "app"
        (tmp_path / "repos" / "root").mkdir(parents=True)
        project.mkdir()

        assert PathValidator.validate_path("../root", anchor_root=project) == Path("../root")

    def test_configure_packages_with_such_dirs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project = tmp_path / "repos" / "etc"
        project.mkdir(parents=True)
        (tmp_path / "repos" / "root").mkdir()
        monkeypatch.chdir(tmp_path)

        configured = _tool(
            "configure_packages", packages=["../root"], save=False, project_path=project.as_posix()
        )

        assert (tmp_path / "repos" / "root").as_posix() in configured["packages"]


def test_the_echo_keeps_the_callers_spelling_with_cwd_inside_the_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#852 re-review: the not-found echo was respelled against a cwd inside the project."""
    project = tmp_path / "project"
    (project / "sub").mkdir(parents=True)
    monkeypatch.chdir(project / "sub")

    result = _tool("resolve_at", file="pkg/m.py", line=1, column=0, project_path=project.as_posix())

    assert result["reason"] == "file_not_found"
    assert result["file"] == "pkg/m.py"

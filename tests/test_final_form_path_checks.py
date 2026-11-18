"""Every caller path is checked in the form the tool finally uses (#856).

pyeye's path check is "a sanity check, not a sandbox" (SECURITY.md), but some
inputs skipped even that on the path the tool really reads:

A. a relative ``file`` / ``project_path`` without ``..`` was checked only as
   written, never anchored or resolved (``etc/passwd`` with ``project_path="/"``,
   or a path through a symlink inside the project);
B. ``resolve``'s identifier file forms (``f.py:42``, ``f.py``) were never checked;
C. a plugin ``scope="package:<path>"`` was never checked;
D. ``configure_packages``' ``namespaces`` values and ``standalone_dirs`` were
   never checked;
E. namespace and standalone paths from the config reached analysis unchecked.

The deny-list stays POSIX-only (it names POSIX system directories), so this
module is skipped on Windows. Controls check that ordinary relative paths and a
symlinked project root (macOS ``/tmp`` -> ``/private/tmp``) still pass.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.skipif(
    os.name == "nt", reason="the deny-list names POSIX system directories"
)

#: Either refusal the validator gives: the given spelling, or the checked target.
REFUSED = "suspicious component|restricted location"


def _assert_refused(tool: str, args: dict[str, Any], server: Any = None) -> None:
    """The call is refused as an MCP tool error, with the validator's message."""
    from mcp.server.mcpserver.exceptions import ToolError

    from pyeye.mcp.server import mcp

    target = server if server is not None else mcp
    try:
        result = asyncio.run(target.call_tool(tool, args))
    except ToolError as error:
        assert re.search(REFUSED, str(error)), error
        return
    assert result.is_error, result.content
    assert re.search(REFUSED, str(result.content)), result.content


def _ok(tool: str, args: dict[str, Any], server: Any = None) -> Any:
    from pyeye.mcp.server import mcp

    target = server if server is not None else mcp
    result = asyncio.run(target.call_tool(tool, args))
    assert not result.is_error, result.content
    return result


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A small project with a symlink ``lnk`` pointing at ``/etc``; cwd elsewhere."""
    root = tmp_path / "project"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "mod.py").write_text("def f() -> int:\n    return 1\n", encoding="utf-8")
    (root / "lnk").symlink_to("/etc", target_is_directory=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    return root


class TestA_RelativeFinalForm:
    @pytest.mark.usefixtures("project")
    def test_a_plain_relative_file_into_etc_from_root(self) -> None:
        _assert_refused(
            "resolve_at", {"file": "etc/hostname", "line": 1, "column": 0, "project_path": "/"}
        )

    def test_a_relative_file_through_a_symlink_into_etc(self, project: Path) -> None:
        _assert_refused(
            "resolve_at",
            {"file": "lnk/hostname", "line": 1, "column": 0, "project_path": project.as_posix()},
        )

    def test_a_relative_project_path_through_a_symlink(self, project: Path) -> None:
        os.chdir(project)
        _assert_refused("resolve", {"identifier": "pkg.mod.f", "project_path": "lnk"})

    def test_control_an_ordinary_relative_file_passes(self, project: Path) -> None:
        payload = _ok(
            "resolve_at",
            {"file": "pkg/mod.py", "line": 1, "column": 4, "project_path": project.as_posix()},
        ).structured_content
        assert payload["handle"] == "pkg.mod.f"


class TestB_ResolveFileForms:
    @pytest.mark.parametrize("identifier", ["/etc/hostname", "/etc/hostname:1"])
    def test_an_absolute_system_file_form(self, project: Path, identifier: str) -> None:
        _assert_refused("resolve", {"identifier": identifier, "project_path": project.as_posix()})

    @pytest.mark.parametrize("identifier", ["lnk/hostname", "lnk/hostname:1"])
    def test_a_relative_file_form_through_a_symlink(self, project: Path, identifier: str) -> None:
        _assert_refused("resolve", {"identifier": identifier, "project_path": project.as_posix()})

    def test_control_an_ordinary_file_form_passes(self, project: Path) -> None:
        payload = _ok(
            "resolve", {"identifier": "pkg/mod.py:1", "project_path": project.as_posix()}
        ).structured_content
        assert payload["handle"] == "pkg.mod.f"


def _plugin_server(project: Path) -> Any:
    from mcp.server.mcpserver import MCPServer

    from pyeye.config import ProjectConfig
    from pyeye.mcp.server import _PLUGIN_CLASSES, register_plugin_tools
    from pyeye.scope_utils import SmartScopeResolver

    server = MCPServer("final-form")
    register_plugin_tools(
        server,
        [cls(project.as_posix()) for cls in _PLUGIN_CLASSES],
        SmartScopeResolver(ProjectConfig(project.as_posix())),
    )
    return server


class TestC_PackageScope:
    @pytest.mark.parametrize("scope", ["package:/etc", "package:lnk"])
    def test_a_package_scope_into_etc(self, project: Path, scope: str) -> None:
        _assert_refused(
            "find_pydantic_models",
            {"scope": scope, "project_path": project.as_posix()},
            _plugin_server(project),
        )

    def test_control_an_ordinary_package_scope_passes(self, project: Path) -> None:
        result = _ok(
            "find_pydantic_models",
            {"scope": "package:pkg", "envelope": True, "project_path": project.as_posix()},
            _plugin_server(project),
        )
        assert "package:pkg" in json.loads(result.content[0].text)["searched"]


class TestD_ConfigurePackagesInputs:
    @pytest.mark.parametrize(
        "args",
        [
            {"namespaces": {"ns": ["/etc"]}},
            {"namespaces": {"ns": ["lnk"]}},
            {"standalone_dirs": ["/etc"]},
            {"standalone_dirs": ["lnk"]},
        ],
        ids=["namespace-abs", "namespace-symlink", "standalone-abs", "standalone-symlink"],
    )
    def test_namespace_and_standalone_inputs(self, project: Path, args: dict[str, Any]) -> None:
        _assert_refused(
            "configure_packages", {**args, "save": False, "project_path": project.as_posix()}
        )


class TestE_ConfigSourcedPaths:
    @pytest.mark.parametrize("bad", ["/etc", "lnk"])
    def test_config_entries_into_etc_are_skipped_with_a_warning(
        self, project: Path, bad: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        from pyeye.config import ProjectConfig

        good = project / "pkg"
        (project / ".pyeye.json").write_text(
            json.dumps(
                {
                    "namespaces": {"ns": [bad, good.as_posix()]},
                    "standalone": {"dirs": [bad, good.as_posix()]},
                }
            ),
            encoding="utf-8",
        )

        with caplog.at_level(logging.WARNING):
            config = ProjectConfig(project.as_posix())
            namespaces = config.get_namespaces()
            standalone = config.get_standalone_paths()

        assert namespaces == {"ns": [good.as_posix()]}
        assert standalone == [good]
        assert re.search(REFUSED, caplog.text)


class TestSymlinkedRoot:
    """macOS: /tmp -> /private/tmp. A project reached through a root symlink passes."""

    def test_a_project_under_a_symlinked_root_passes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real = tmp_path / "private" / "tmp"
        (real / "proj" / "pkg").mkdir(parents=True)
        (real / "proj" / "pkg" / "__init__.py").write_text("", encoding="utf-8")
        (real / "proj" / "pkg" / "mod.py").write_text("def f() -> int:\n    return 1\n", "utf-8")
        link = tmp_path / "tmp"
        link.symlink_to(real, target_is_directory=True)
        project = link / "proj"
        monkeypatch.chdir(tmp_path)

        payload = _ok(
            "resolve_at",
            {"file": "pkg/mod.py", "line": 1, "column": 4, "project_path": project.as_posix()},
        ).structured_content

        assert payload["handle"] == "pkg.mod.f"

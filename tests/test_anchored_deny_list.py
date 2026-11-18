"""The deny-list refuses where a path LEADS, never a directory name inside it (#939).

A spelling check matched "/etc/", "/root/", "/proc/", "/sys/" and "/dev/" anywhere
in a path, ignoring case, so a project under ``~/dev`` (or any directory named
etc, sys, proc, dev or root) could not be analysed at all. Since #856 every caller
path is checked anchored and resolved, so the ANCHORED patterns alone catch every
route to a system directory; the substring check and the two unanchored patterns
are gone, and the anchored ones ignore case.

POSIX-only: the deny-list names POSIX system directories.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.skipif(
    os.name == "nt", reason="the deny-list names POSIX system directories"
)

REFUSED = "restricted location"

#: Project parents that the substring check refused.
NAMED_LIKE_SYSTEM_DIRS = ["dev", "Dev", "srv/etc/lib", "home/u/root", "work/SYS"]


def _project(base: Path) -> Path:
    """A project with its own ``etc`` and ``sys`` packages beside ``pkg``."""
    for package in ("pkg", "etc", "sys"):
        (base / package).mkdir(parents=True)
        (base / package / "__init__.py").write_text("", encoding="utf-8")
    (base / "pkg" / "mod.py").write_text("def f() -> int:\n    return 1\n", encoding="utf-8")
    (base / "etc" / "settings.py").write_text("DEBUG = True\n", encoding="utf-8")
    (base / "sys" / "tools.py").write_text("def g() -> int:\n    return 2\n", encoding="utf-8")
    return base


def _call(tool: str, args: dict[str, Any], server: Any = None) -> Any:
    from pyeye.mcp.server import mcp

    result = asyncio.run((server or mcp).call_tool(tool, args))
    assert not result.is_error, result.content
    return result


def _refused(tool: str, args: dict[str, Any]) -> None:
    from mcp.server.mcpserver.exceptions import ToolError

    from pyeye.mcp.server import mcp

    try:
        result = asyncio.run(mcp.call_tool(tool, args))
    except ToolError as error:
        assert re.search(REFUSED, str(error)), error
        return
    assert result.is_error, result.content
    assert re.search(REFUSED, str(result.content)), result.content


@pytest.fixture(params=NAMED_LIKE_SYSTEM_DIRS)
def project(request: pytest.FixtureRequest, tmp_path: Path) -> Path:
    return _project(tmp_path / request.param / "proj")


class TestNamedLikeASystemDirIsAccepted:
    def test_resolve(self, project: Path) -> None:
        payload = _call(
            "resolve", {"identifier": "pkg.mod.f", "project_path": project.as_posix()}
        ).structured_content
        assert payload["handle"] == "pkg.mod.f"

    def test_resolve_at_in_the_projects_own_etc_and_sys(self, project: Path) -> None:
        etc = _call(
            "resolve_at",
            {"file": "etc/settings.py", "line": 1, "column": 0, "project_path": project.as_posix()},
        ).structured_content
        assert etc["handle"] == "etc.settings.DEBUG"
        # Not refused (a project's ``sys`` package may still lose to the stdlib's
        # name, which is a separate matter).
        _call(
            "resolve_at",
            {"file": "sys/tools.py", "line": 1, "column": 4, "project_path": project.as_posix()},
        )

    def test_outline(self, project: Path) -> None:
        payload = _call(
            "outline", {"handle": "etc.settings", "project_path": project.as_posix()}
        ).structured_content
        assert payload["found"] is True

    def test_configure_packages(self, project: Path) -> None:
        sibling = project.parent / "etc-lib"
        sibling.mkdir()
        payload = _call(
            "configure_packages",
            {"packages": [sibling.as_posix()], "save": False, "project_path": project.as_posix()},
        ).structured_content
        assert sibling.as_posix() in payload["packages"]

    def test_a_plugin_package_scope(self, project: Path) -> None:
        from mcp.server.mcpserver import MCPServer

        from pyeye.config import ProjectConfig
        from pyeye.mcp.server import _PLUGIN_CLASSES, register_plugin_tools
        from pyeye.scope_utils import SmartScopeResolver

        server = MCPServer("anchored-deny-list")
        register_plugin_tools(
            server,
            [cls(project.as_posix()) for cls in _PLUGIN_CLASSES],
            SmartScopeResolver(ProjectConfig(project.as_posix())),
        )
        result = _call(
            "find_pydantic_models",
            {"scope": "package:etc", "envelope": True, "project_path": project.as_posix()},
            server,
        )
        assert "package:etc" in json.loads(result.content[0].text)["searched"]


class TestEveryRouteToASystemDirIsStillRefused:
    @pytest.fixture
    def proj(self, tmp_path: Path) -> Path:
        return _project(tmp_path / "proj")

    def test_a_climb(self, proj: Path) -> None:
        _refused(
            "resolve_at",
            {
                "file": "../" * 40 + "etc/passwd",
                "line": 1,
                "column": 0,
                "project_path": proj.as_posix(),
            },
        )

    def test_a_relative_path_from_the_root(self) -> None:
        _refused("resolve_at", {"file": "etc/passwd", "line": 1, "column": 0, "project_path": "/"})

    def test_a_symlink_into_etc(self, proj: Path) -> None:
        (proj / "lnk").symlink_to("/etc", target_is_directory=True)
        _refused(
            "resolve_at",
            {"file": "lnk/passwd", "line": 1, "column": 0, "project_path": proj.as_posix()},
        )

    def test_upper_case(self, proj: Path) -> None:
        """A case-insensitive macOS volume reads /ETC/passwd as /etc/passwd."""
        _refused(
            "resolve_at",
            {"file": "/ETC/passwd", "line": 1, "column": 0, "project_path": proj.as_posix()},
        )

    @pytest.mark.parametrize("form", ["/private/etc/hosts", "/PRIVATE/ETC/hosts", "/private/etc"])
    def test_the_macos_resolved_form(self, form: str) -> None:
        """Simulated macOS: /etc resolves to /private/etc, which is refused in any case."""
        from pyeye.exceptions import ValidationError
        from pyeye.validation import PathValidator

        with pytest.raises(ValidationError, match=REFUSED):
            PathValidator._check_targets([form])

    def test_a_relative_path_without_a_root_is_anchored_on_the_cwd(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No root given: checked where the OS would put it, never only as written."""
        from pyeye.exceptions import ValidationError
        from pyeye.validation import PathValidator

        monkeypatch.chdir("/")
        with pytest.raises(ValidationError, match=REFUSED):
            PathValidator.validate_path("etc/passwd")


class TestSymlinkThenDotDot:
    """#949 review: ``l_tmp/../etc`` with ``l_tmp`` -> ``/tmp`` is ``/etc`` on disk.

    The OS follows the symlink before ``..``; collapsing ``..`` lexically first
    gave ``<proj>/etc``, which passed, and the tool then read ``/etc``. The
    removed substring check used to mask it for deeper paths (``…/etc/x``);
    ``proj/l_tmp/../etc`` itself already passed before #939.
    """

    @pytest.fixture
    def proj(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        proj = _project(tmp_path / "proj")
        (proj / "l_tmp").symlink_to("/tmp", target_is_directory=True)
        monkeypatch.chdir(tmp_path)  # the reviewer's set-up: cwd at proj's parent
        return proj

    @pytest.mark.usefixtures("proj")
    @pytest.mark.parametrize("tail", ["etc", "proc/self"])
    def test_a_relative_project_path(self, tail: str) -> None:
        for tool, args in [
            ("resolve", {"identifier": "sitecustomize"}),
            ("outline", {"handle": "sitecustomize"}),
        ]:
            _refused(tool, {**args, "project_path": f"proj/l_tmp/../{tail}"})

    def test_an_absolute_project_path(self, proj: Path) -> None:
        _refused("resolve", {"identifier": "x", "project_path": f"{proj.as_posix()}/l_tmp/../etc"})

    @pytest.mark.parametrize("file", ["l_tmp/../etc/hostname", "l_tmp/../etc/hostname:1"])
    def test_a_resolve_file_form(self, proj: Path, file: str) -> None:
        _refused("resolve", {"identifier": file, "project_path": proj.as_posix()})

    def test_a_resolve_at_file(self, proj: Path) -> None:
        _refused(
            "resolve_at",
            {
                "file": "l_tmp/../etc/hostname",
                "line": 1,
                "column": 0,
                "project_path": proj.as_posix(),
            },
        )

    @pytest.mark.parametrize(
        "args",
        [
            {"packages": ["l_tmp/../etc"]},
            {"standalone_dirs": ["l_tmp/../etc"]},
            {"namespaces": {"ns": ["l_tmp/../etc"]}},
        ],
        ids=["packages", "standalone", "namespace"],
    )
    def test_configure_packages_lists(self, proj: Path, args: dict[str, Any]) -> None:
        _refused("configure_packages", {**args, "save": False, "project_path": proj.as_posix()})

    def test_check_forms_resolves_the_raw_join(self, proj: Path) -> None:
        from pyeye.path_utils import normalize_path
        from pyeye.validation import PathValidator

        resolved, forms = PathValidator.check_forms(Path("l_tmp/../etc"), proj)

        assert resolved == normalize_path("/etc")
        assert normalize_path("/etc").as_posix() in forms

    def test_control_a_symlink_without_dot_dot_still_works(self, proj: Path) -> None:
        """``l_tmp/x`` really is /tmp/x: allowed, as before."""
        _call(
            "resolve_at",
            {"file": "pkg/mod.py", "line": 1, "column": 4, "project_path": proj.as_posix()},
        )

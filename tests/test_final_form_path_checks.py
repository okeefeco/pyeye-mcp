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

#: The validator's refusals: the given spelling, the checked target, or a glob
#: with ``..`` in configure_packages.
REFUSED = "suspicious component|restricted location|may not contain '\\.\\.'"


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


class TestReviewNamespaceSubPart:
    """#901 review 1: ``namespace:ns./etc`` joined an absolute sub-part onto the base."""

    @pytest.fixture
    def ns_project(self, project: Path) -> Path:
        repo = project.parent / "ns-repo"
        (repo / "ns").mkdir(parents=True)
        (project / ".pyeye.json").write_text(
            json.dumps({"namespaces": {"ns": [repo.as_posix()]}}), encoding="utf-8"
        )
        return project

    @pytest.mark.parametrize("scope", ["namespace:ns./etc", "namespace:ns.a/b", "namespace:ns..x"])
    def test_a_non_identifier_sub_part_is_refused(self, ns_project: Path, scope: str) -> None:
        from pyeye.exceptions import ValidationError
        from pyeye.scope_utils import ScopeLayout, resolve_scope_paths

        layout = ScopeLayout.from_parts(
            ns_project, namespace_paths={"ns": [ns_project.parent / "ns-repo"]}
        )

        with pytest.raises(ValidationError, match="sub-namespace must be a dotted Python name"):
            resolve_scope_paths(scope, layout)

    def test_end_to_end_the_tool_refuses_it(self, ns_project: Path) -> None:
        from mcp.server.mcpserver.exceptions import ToolError

        with pytest.raises(ToolError, match="sub-namespace"):
            asyncio.run(
                _plugin_server(ns_project).call_tool(
                    "find_pydantic_models",
                    {"scope": "namespace:ns./etc", "project_path": ns_project.as_posix()},
                )
            )

    def test_through_a_scope_alias_too(self, ns_project: Path) -> None:
        from mcp.server.mcpserver.exceptions import ToolError

        config = json.loads((ns_project / ".pyeye.json").read_text(encoding="utf-8"))
        config["scope_aliases"] = {"sneaky": "namespace:ns./etc"}
        (ns_project / ".pyeye.json").write_text(json.dumps(config), encoding="utf-8")

        with pytest.raises(ToolError, match="sub-namespace"):
            asyncio.run(
                _plugin_server(ns_project).call_tool(
                    "find_pydantic_models",
                    {"scope": "sneaky", "project_path": ns_project.as_posix()},
                )
            )

    def test_every_scope_path_is_checked_whatever_produced_it(self, project: Path) -> None:
        """A layout that already holds a restricted directory (however it got there) is refused."""
        from pyeye.exceptions import ValidationError
        from pyeye.scope_utils import ScopeLayout, resolve_scope_paths

        layout = ScopeLayout.from_parts(project, additional_paths=[Path("/etc")])

        with pytest.raises(ValidationError, match="Invalid scope 'packages'"):
            resolve_scope_paths("packages", layout)

    def test_control_a_real_sub_namespace_passes(self, ns_project: Path) -> None:
        from pyeye.scope_utils import ScopeLayout, resolve_scope_paths

        (ns_project.parent / "ns-repo" / "ns" / "sub").mkdir()
        layout = ScopeLayout.from_parts(
            ns_project, namespace_paths={"ns": [ns_project.parent / "ns-repo"]}
        )

        assert resolve_scope_paths("namespace:ns.sub", layout) == {
            ns_project.parent / "ns-repo" / "ns" / "sub"
        }


class TestReviewMacOSDirectory:
    """#901 review 2: on macOS a directory resolving to /private/etc itself passed."""

    @pytest.mark.parametrize("form", ["/private/etc", "/private/etc/", "/private/etc/hosts"])
    def test_the_macos_resolved_form_is_refused(self, form: str) -> None:
        from pyeye.exceptions import ValidationError
        from pyeye.validation import PathValidator

        with pytest.raises(ValidationError, match="restricted location"):
            PathValidator._check_targets([form])

    @pytest.mark.parametrize(
        "form", ["/home/u/repos/etc", "/home/u/repos/root", "/srv/private/etc-tools"]
    )
    def test_an_ordinary_directory_named_like_one_passes(self, form: str) -> None:
        from pyeye.validation import PathValidator

        PathValidator._check_targets([form])

    def test_a_symlink_to_etc_resolving_as_on_macos_is_refused(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Simulate macOS: the resolver turns /etc into /private/etc."""
        from pyeye import validation
        from pyeye.exceptions import ValidationError

        real = validation.normalize_path

        def macos(path: Any) -> Path:
            resolved = real(path)
            text = resolved.as_posix()
            return (
                Path("/private" + text) if text == "/etc" or text.startswith("/etc/") else resolved
            )

        monkeypatch.setattr(validation, "normalize_path", macos)

        with pytest.raises(ValidationError, match="restricted location"):
            validation.PathValidator.validate_final("lnk", project)  # the directory itself


class TestReviewConfigurePackagesFinalForm:
    """#901 review 3: entries were checked before ~ expansion and the config's normalisation."""

    @pytest.mark.parametrize(
        "args",
        [
            {"packages": ["~root"]},
            {"standalone_dirs": ["~root"]},
            {"namespaces": {"ns": ["~root"]}},
            {"packages": ["l_tmp/../etc"]},
        ],
        ids=["tilde-package", "tilde-standalone", "tilde-namespace", "symlink-then-dotdot"],
    )
    def test_refused_and_nothing_is_written(self, project: Path, args: dict[str, Any]) -> None:
        if "~root" in json.dumps(args) and Path("~root").expanduser() == Path("~root"):
            pytest.skip("no 'root' user to expand ~root here")
        # As in the review: l_tmp -> /tmp, so l_tmp/../etc is /etc on disk.
        (project / "l_tmp").symlink_to("/tmp", target_is_directory=True)
        before = (project / ".pyeye.json").exists()

        _assert_refused(
            "configure_packages", {**args, "save": True, "project_path": project.as_posix()}
        )

        assert (project / ".pyeye.json").exists() is before

    def test_symlink_then_dot_dot_resolves_through_the_symlink(self, tmp_path: Path) -> None:
        """``l_tmp/../etc``: the OS follows l_tmp first, so the final form is NOT <root>/etc."""
        from pyeye.exceptions import ValidationError
        from pyeye.validation import PathValidator

        root = tmp_path / "proj"
        root.mkdir()
        (root / "l_root").symlink_to("/", target_is_directory=True)
        (root / "l_root").resolve()  # sanity: a working link

        with pytest.raises(ValidationError, match="restricted location"):
            PathValidator.validate_final("l_root/../etc", root)


class TestReviewConfigGlobs:
    """#901 re-review: glob entries were checked in pattern form, so they were saved."""

    @pytest.mark.parametrize(
        "args",
        [
            {"packages": ["l_t*/../etc"]},
            {"namespaces": {"n5": ["l_t*/../etc"]}},
            {"standalone_dirs": ["l_t*/../etc"]},
            {"packages": ["/e*"]},
            {"namespaces": {"n6": ["/e?c"]}},
        ],
        ids=["dotdot-package", "dotdot-namespace", "dotdot-standalone", "star-etc", "qmark-etc"],
    )
    def test_refused_and_nothing_is_written(self, project: Path, args: dict[str, Any]) -> None:
        (project / "l_tmp").symlink_to("/tmp", target_is_directory=True)

        _assert_refused(
            "configure_packages", {**args, "save": True, "project_path": project.as_posix()}
        )

        assert not (project / ".pyeye.json").exists()

    def test_a_glob_with_dot_dot_is_refused_outright(self, project: Path) -> None:
        from mcp.server.mcpserver.exceptions import ToolError

        from pyeye.mcp.server import mcp

        with pytest.raises(ToolError, match="may not contain '..'"):
            asyncio.run(
                mcp.call_tool(
                    "configure_packages",
                    {"packages": ["lib*/../x"], "save": True, "project_path": project.as_posix()},
                )
            )

    def test_control_a_glob_over_ordinary_dirs_is_saved(self, project: Path) -> None:
        for name in ("a", "b"):
            (project / "libs" / name).mkdir(parents=True)

        _ok(
            "configure_packages",
            {"packages": ["libs/*"], "save": True, "project_path": project.as_posix()},
        )

        saved = json.loads((project / ".pyeye.json").read_text(encoding="utf-8"))
        assert saved["packages"] == ["libs/*"]

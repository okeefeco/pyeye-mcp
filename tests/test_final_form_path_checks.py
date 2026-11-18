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
REFUSED = "restricted location|may not contain '\\.\\.'"


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
        if "~root" in json.dumps(args):
            home = Path("~root").expanduser()
            if home == Path("~root"):
                pytest.skip("no 'root' user to expand ~root here")
            # Follow the policy, not Linux: on macOS ~root is /var/root, which the
            # deny-list doesn't name (whether it should is #909's question).
            from pyeye.exceptions import ValidationError
            from pyeye.validation import PathValidator

            try:
                PathValidator.validate_scan_root(home, project)
            except ValidationError:
                pass
            else:
                pytest.skip(f"~root expands to {home.as_posix()}, not restricted here")
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


class TestRulingAncestorScanRoots:
    """A directory-scan root may not be an ANCESTOR of a restricted one (#856 ruling).

    "/" (and "/private" on macOS) would walk into /etc. project_path and
    single-file inputs are unchanged (Q1); only the SCAN from such a root is refused.
    """

    def test_the_ancestors_derive_from_the_anchored_patterns_only(self) -> None:
        from pyeye import validation

        assert "/etc" in validation._RESTRICTED_DIRS
        assert "/private/etc" in validation._RESTRICTED_DIRS
        # The unanchored "/etc/" and "/root/" name no fixed directory.
        assert all(d.startswith("/") and "^" not in d for d in validation._RESTRICTED_DIRS)
        # /boot, /run/secrets, /var/run/secrets, /var/root and /private/var/root (#909)
        # add /run, /var, /var/run and /private/var. Credential stores add none.
        assert {
            "/",
            "/private",
            "/private/var",
            "/private/var/run",
            "/run",
            "/var",
            "/var/run",
        } == (validation._RESTRICTED_ANCESTORS)

    @pytest.mark.parametrize("scope", ["package:/", "package:root_lnk"])
    def test_a_package_scope_at_an_ancestor(self, project: Path, scope: str) -> None:
        (project / "root_lnk").symlink_to("/", target_is_directory=True)
        _assert_refused(
            "find_pydantic_models",
            {"scope": scope, "project_path": project.as_posix()},
            _plugin_server(project),
        )

    @pytest.mark.parametrize(
        "args",
        [{"namespaces": {"ns": ["/"]}}, {"packages": ["/"]}, {"standalone_dirs": ["/"]}],
        ids=["namespace", "package", "standalone"],
    )
    def test_configure_packages_refuses_an_ancestor(
        self, project: Path, args: dict[str, Any]
    ) -> None:
        _assert_refused(
            "configure_packages", {**args, "save": False, "project_path": project.as_posix()}
        )

    def test_config_entries_at_an_ancestor_are_skipped_with_a_warning(
        self, project: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        from pyeye.config import ProjectConfig

        good = project / "pkg"
        (project / ".pyeye.json").write_text(
            json.dumps(
                {"namespaces": {"ns": ["/", good.as_posix()]}, "standalone": {"dirs": ["/"]}}
            ),
            encoding="utf-8",
        )
        with caplog.at_level(logging.WARNING):
            config = ProjectConfig(project.as_posix())
            assert config.get_namespaces() == {"ns": [good.as_posix()]}
            assert config.get_standalone_paths() == []
        assert "ancestor of a restricted location" in caplog.text

    def test_project_path_root_with_scope_main_is_refused(self, project: Path) -> None:
        _assert_refused(
            "find_pydantic_models",
            {"scope": "main", "project_path": "/"},
            _plugin_server(project),
        )

    def test_project_path_root_with_a_single_file_is_unchanged(self, project: Path) -> None:
        mod = project / "pkg" / "mod.py"
        payload = _ok(
            "resolve_at", {"file": mod.as_posix(), "line": 1, "column": 4, "project_path": "/"}
        ).structured_content
        # Not refused (Q1). Whether it resolves is a separate matter: from "/"
        # the file's module path runs through tmp dirs that aren't dotted names.
        assert payload["file"] == mod.as_posix()
        assert payload.get("reason") != "invalid_input"

    def test_no_watcher_is_started_on_an_ancestor(self) -> None:
        from pyeye.project_manager import ProjectManager

        manager = ProjectManager(max_projects=2)
        try:
            manager._watch(Path("/"), Path("/"))
            assert manager.watchers == {}
        finally:
            manager.cleanup_all()


class TestRulingWalksPrune:
    """Every directory walk prunes restricted directories, whatever route reaches them."""

    def test_a_walk_rooted_through_a_symlinked_parent_yields_nothing(self, tmp_path: Path) -> None:
        from pyeye.async_utils import filtered_rglob, pruned_rglob

        (tmp_path / "via").symlink_to("/", target_is_directory=True)
        root = tmp_path / "via" / "etc"  # lexically under tmp_path; really /etc
        assert filtered_rglob("*", root) == []
        assert pruned_rglob("*", root) == []

    def test_a_restricted_dir_below_the_root_is_pruned_by_its_resolved_form(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from pyeye import validation
        from pyeye.async_utils import filtered_rglob, pruned_rglob

        real = tmp_path / "real"
        (real / "secret").mkdir(parents=True)
        (real / "secret" / "x.py").write_text("", encoding="utf-8")
        (real / "ok.py").write_text("", encoding="utf-8")
        (tmp_path / "proj").mkdir()
        link = tmp_path / "proj" / "link"
        link.symlink_to(real, target_is_directory=True)
        # Stand in for /etc: a restricted dir only its RESOLVED form names.
        restricted = (real / "secret").resolve().as_posix()
        monkeypatch.setattr(validation, "_RESTRICTED_DIRS", (restricted,))

        for walk in (filtered_rglob, pruned_rglob):
            found = {p.name for p in walk("*.py", link)}
            assert found == {"ok.py"}, walk.__name__

    def test_pruned_rglob_finds_what_rglob_finds(self, tmp_path: Path) -> None:
        """Rerouting the template and site-packages walks excludes nothing new."""
        from pyeye.async_utils import pruned_rglob

        tpl = tmp_path / "templates"
        for sub in ["", "build", "node_modules", ".venv", "__pycache__", "a/b", "wt"]:
            (tpl / sub).mkdir(parents=True, exist_ok=True)
            (tpl / sub / "page.html").write_text("", encoding="utf-8")
        (tpl / "wt" / ".git").write_text("gitdir: /x/.git/worktrees/wt\n", encoding="utf-8")
        (tpl / "a" / ".git").mkdir()

        assert set(pruned_rglob("*.html", tpl)) == set(tpl.rglob("*.html"))

    def test_venv_site_packages_discovery_still_works(self, tmp_path: Path) -> None:
        from pyeye.config import ProjectConfig

        site = tmp_path / "proj" / ".venv" / "lib" / "python3.12" / "site-packages"
        site.mkdir(parents=True)
        config = ProjectConfig((tmp_path / "proj").as_posix())

        assert site.as_posix() in [Path(p).as_posix() for p in config._discover_venv_packages()]

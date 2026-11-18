"""A config entry the path check rejects is disclosed, never silently dropped (#898).

Under #856 a ``.pyeye.json`` namespace, standalone or package path that fails the
final-form check is skipped with a warning. Without disclosure it simply
vanished from the configured scopes, so results silently omitted a package the
user configured: unknown written as absent (#568). Now:

- its scope is listed in ``unsearched_scopes`` (it can't be fully searched);
- the plugin envelope and ``configure_packages`` carry ``rejected_paths``:
  ``{scope, path, reason: "rejected_path", detail}`` per rejected entry, ALWAYS
  present (``[]`` when none, a measured empty, never omitted);
- a ``package:`` path that merely doesn't exist stays an unsearched scope with no
  ``rejected_paths`` entry (#842): missing and rejected stay distinct.

POSIX-only: the deny-list names POSIX system directories.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.skipif(
    os.name == "nt", reason="the deny-list names POSIX system directories"
)

MODEL = "from pydantic import BaseModel\n\n\nclass {name}(BaseModel):\n    x: int\n"


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A project with good namespace/standalone/package entries next to rejected ones."""
    root = tmp_path / "project"
    (root / "app").mkdir(parents=True)
    (root / "app" / "__init__.py").write_text("", encoding="utf-8")
    (root / "app" / "main_models.py").write_text(MODEL.format(name="Main"), encoding="utf-8")
    (root / "lnk").symlink_to("/etc", target_is_directory=True)
    good_ns = tmp_path / "ns-repo"
    (good_ns / "ns").mkdir(parents=True)
    (good_ns / "ns" / "models.py").write_text(MODEL.format(name="NsModel"), encoding="utf-8")
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "tool.py").write_text(MODEL.format(name="Script"), encoding="utf-8")
    (root / ".pyeye.json").write_text(
        json.dumps(
            {
                "namespaces": {"ns": ["lnk", good_ns.as_posix()]},
                "standalone": {"dirs": ["/etc", scripts.as_posix()]},
            }
        ),
        encoding="utf-8",
    )
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    return root


def _envelope(project: Path, scope: Any) -> dict[str, Any]:
    from mcp.server.mcpserver import MCPServer

    from pyeye.config import ProjectConfig
    from pyeye.mcp.server import _PLUGIN_CLASSES, _apply_plugin_paths, register_plugin_tools
    from pyeye.scope_utils import SmartScopeResolver

    config = ProjectConfig(project.as_posix())
    plugins = [cls(project.as_posix()) for cls in _PLUGIN_CLASSES]
    for plugin in plugins:
        _apply_plugin_paths(plugin, config)  # as initialize_plugins does
    server = MCPServer("rejected-config")
    register_plugin_tools(server, plugins, SmartScopeResolver(config))
    result = asyncio.run(
        server.call_tool(
            "find_pydantic_models",
            {"scope": scope, "envelope": True, "project_path": project.as_posix()},
        )
    )
    assert not result.is_error, result.content
    payload = json.loads(result.content[0].text)
    assert isinstance(payload, dict)
    return payload


def _rejected(payload: dict[str, Any]) -> set[tuple[str, str, str]]:
    return {(r["scope"], r["path"], r["reason"]) for r in payload["rejected_paths"]}


class TestEnvelope:
    def test_the_key_is_always_present_in_order(self, project: Path) -> None:
        payload = _envelope(project, "all")

        assert list(payload) == [
            "scope",
            "searched",
            "unsearched_scopes",
            "rejected_paths",
            "results",
            "unplaced_classes",  # find_pydantic_models' own key, after the shared ones (#921)
        ]

    def test_rejected_entries_are_disclosed_with_a_reason(self, project: Path) -> None:
        payload = _envelope(project, "all")

        assert _rejected(payload) == {
            ("namespace:ns", "lnk", "rejected_path"),
            ("standalone", "/etc", "rejected_path"),
        }
        assert all("restricted location" in r["detail"] for r in payload["rejected_paths"])

    def test_a_scope_with_a_rejected_path_is_unsearched_never_searched(self, project: Path) -> None:
        payload = _envelope(project, "all")

        for scope in ("namespace:ns", "standalone"):
            assert scope in payload["unsearched_scopes"]
            assert scope not in payload["searched"]

    def test_the_good_entries_are_still_searched(self, project: Path) -> None:
        names = {m["name"] for m in _envelope(project, "all")["results"]}

        assert {"Main", "NsModel", "Script"} <= names

    def test_a_clean_config_gives_an_empty_list(self, tmp_path: Path) -> None:
        root = tmp_path / "clean"
        (root / "app").mkdir(parents=True)
        (root / "app" / "m.py").write_text(MODEL.format(name="Main"), encoding="utf-8")

        payload = _envelope(root, "all")

        assert payload["rejected_paths"] == []

    def test_a_missing_package_scope_is_unsearched_not_rejected(self, project: Path) -> None:
        payload = _envelope(project, "package:not/here")

        assert "package:not/here" in payload["unsearched_scopes"]
        assert ("package:not/here",) not in {(r["scope"],) for r in payload["rejected_paths"]}


def test_configure_packages_discloses_rejected_entries(project: Path) -> None:
    from pyeye.mcp.server import mcp

    result = asyncio.run(
        mcp.call_tool("configure_packages", {"save": False, "project_path": project.as_posix()})
    )

    assert not result.is_error, result.content
    payload = result.structured_content
    assert isinstance(payload, dict)
    assert _rejected(payload) == {
        ("namespace:ns", "lnk", "rejected_path"),
        ("standalone", "/etc", "rejected_path"),
    }


def test_rejected_package_entries_are_disclosed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``packages`` entries were already skipped before #856; they're disclosed too."""
    root = tmp_path / "project"
    (root / "app").mkdir(parents=True)
    (root / "app" / "m.py").write_text(MODEL.format(name="Main"), encoding="utf-8")
    (root / ".pyeye.json").write_text(json.dumps({"packages": ["/etc"]}), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    payload = _envelope(root, "all")

    assert ("packages", "/etc", "rejected_path") in _rejected(payload)
    assert "packages" in payload["unsearched_scopes"]


def test_an_ancestor_entry_is_disclosed_too(tmp_path: Path) -> None:
    """A "/" entry (an ancestor of /etc) is refused under #856's ruling, and disclosed."""
    from pyeye.config import ProjectConfig

    root = tmp_path / "project"
    root.mkdir()
    (root / ".pyeye.json").write_text(
        json.dumps({"namespaces": {"ns": ["/"]}, "standalone": {"dirs": ["/"]}}), encoding="utf-8"
    )

    rejected = ProjectConfig(root.as_posix()).rejected_paths()

    assert {(r["scope"], r["path"]) for r in rejected} == {
        ("namespace:ns", "/"),
        ("standalone", "/"),
    }
    assert all("ancestor of a restricted location" in r["detail"] for r in rejected)


def test_a_glob_with_a_refused_match_is_skipped_whole_and_disclosed(tmp_path: Path) -> None:
    from pyeye.config import ProjectConfig

    root = tmp_path / "project"
    (root / "libs" / "ok").mkdir(parents=True)
    (root / "libs" / "bad").symlink_to("/etc", target_is_directory=True)
    (root / ".pyeye.json").write_text(json.dumps({"packages": ["libs/*"]}), encoding="utf-8")
    config = ProjectConfig(root.as_posix())

    assert (root / "libs" / "ok").as_posix() not in config.get_package_paths()
    assert [(r["scope"], r["path"]) for r in config.rejected_paths()] == [("packages", "libs/*")]


def test_the_getters_skip_exactly_what_is_disclosed(project: Path) -> None:
    """One source (#898): every refused entry is disclosed, and every disclosed one is skipped."""
    from pyeye.config import ProjectConfig

    config = ProjectConfig(project.as_posix())
    disclosed = {(r["scope"], r["path"]) for r in config.rejected_paths()}

    raw = json.loads((project / ".pyeye.json").read_text(encoding="utf-8"))
    kept_ns = set(config.get_namespaces()["ns"])
    kept_standalone = {p.as_posix() for p in config.get_standalone_paths()}
    skipped = {
        ("namespace:ns", p)
        for p in raw["namespaces"]["ns"]
        if config._normalise_config_path(p) not in kept_ns
    } | {
        ("standalone", p)
        for p in raw["standalone"]["dirs"]
        if config._standalone_dir(p).as_posix() not in kept_standalone
    }
    assert skipped == disclosed


def test_a_rejected_scope_is_unsearched_whatever_was_asked(project: Path) -> None:
    payload = _envelope(project, "main")

    assert {"namespace:ns", "standalone"} <= set(payload["unsearched_scopes"])
    assert _rejected(payload)  # disclosed on every call, not only for scope="all"


def test_configure_packages_gives_an_empty_list_for_a_clean_config(tmp_path: Path) -> None:
    from pyeye.mcp.server import mcp

    root = tmp_path / "clean"
    (root / "app").mkdir(parents=True)
    result = asyncio.run(
        mcp.call_tool("configure_packages", {"save": False, "project_path": root.as_posix()})
    )

    assert not result.is_error, result.content
    assert result.structured_content["rejected_paths"] == []


class TestNeverAnEmptyListForAnUnfinishedCheck:
    """``rejected_paths`` present means the check ran and is trusted (#898 contract).

    When the check can't complete, the response errors or omits the key; it
    never reports ``[]``, which reads as a measured "none refused".
    """

    @pytest.fixture
    def broken(self, tmp_path: Path) -> Path:
        """A project whose ``.pyeye.json`` can't be parsed: its entries are unknown."""
        root = tmp_path / "broken"
        (root / "app").mkdir(parents=True)
        (root / "app" / "m.py").write_text(MODEL.format(name="Main"), encoding="utf-8")
        (root / ".pyeye.json").write_text('{"packages": ["/etc",', encoding="utf-8")
        return root

    def test_a_config_that_failed_to_load_is_not_a_measured_none(self, broken: Path) -> None:
        from pyeye.config import ProjectConfig

        config = ProjectConfig(broken.as_posix())

        assert config.load_errors
        assert config.rejected_paths() is None

    def test_the_envelope_omits_the_key(self, broken: Path) -> None:
        payload = _envelope(broken, "all")

        assert "rejected_paths" not in payload
        assert list(payload) == [
            "scope",
            "searched",
            "unsearched_scopes",
            "results",
            "unplaced_classes",  # find_pydantic_models' own key (#921)
        ]

    def test_configure_packages_omits_the_key(self, broken: Path) -> None:
        from pyeye.mcp.server import mcp

        result = asyncio.run(
            mcp.call_tool("configure_packages", {"save": False, "project_path": broken.as_posix()})
        )

        assert not result.is_error, result.content
        assert "rejected_paths" not in result.structured_content

    def test_a_plugin_never_configured_omits_the_key(self, tmp_path: Path) -> None:
        from mcp.server.mcpserver import MCPServer

        from pyeye.mcp.server import _PLUGIN_CLASSES, register_plugin_tools

        root = tmp_path / "bare"
        (root / "app").mkdir(parents=True)
        server = MCPServer("unconfigured")
        register_plugin_tools(server, [cls(root.as_posix()) for cls in _PLUGIN_CLASSES], None)
        result = asyncio.run(
            server.call_tool(
                "find_pydantic_models",
                {"scope": "main", "envelope": True, "project_path": root.as_posix()},
            )
        )

        assert "rejected_paths" not in json.loads(result.content[0].text)

    def test_a_check_that_raises_part_way_is_an_error(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """configure_packages errors rather than report what it saw so far."""
        from pyeye.config import ProjectConfig
        from pyeye.mcp.server import mcp

        calls = iter(range(100))

        def flaky(*_args: object) -> str | None:
            if next(calls) == 1:
                raise RuntimeError("check interrupted")
            return None

        monkeypatch.setattr(ProjectConfig, "_path_refusal", flaky)
        try:
            result = asyncio.run(
                mcp.call_tool(
                    "configure_packages", {"save": False, "project_path": project.as_posix()}
                )
            )
        except Exception as error:  # the server raised: an error, as required
            assert "configure_packages" in str(error) or "check interrupted" in str(error)
            return
        assert result.is_error, result.structured_content
        assert "check interrupted" in str(result.content)

    def test_a_failed_reapply_leaves_not_measured_never_the_old_list(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from pyeye.config import ProjectConfig
        from pyeye.mcp.server import _apply_plugin_paths
        from pyeye.plugins.pydantic import PydanticPlugin

        plugin = PydanticPlugin(project.as_posix())
        _apply_plugin_paths(plugin, ProjectConfig(project.as_posix()))
        assert plugin.rejected_paths  # measured: the fixture refuses two entries

        def interrupted(*_args: object) -> None:
            raise RuntimeError("check interrupted")

        monkeypatch.setattr(ProjectConfig, "rejected_paths", interrupted)
        with pytest.raises(RuntimeError):
            _apply_plugin_paths(plugin, ProjectConfig(project.as_posix()))

        assert plugin.rejected_paths is None

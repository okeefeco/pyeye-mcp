"""A glob in a ``namespaces`` entry expands to its sorted matches (#872).

``get_namespaces()`` only normalised each entry, so ``"co": ["~/repos/co-*"]``
mapped the namespace to the literal pattern, a directory that doesn't exist:
``namespace:co`` searched nothing, while the same matches reached the analysis
as plain packages. Namespaces and packages now share one expansion
(``ProjectConfig._expand_glob``), so the two can't disagree:

- matches are sorted (a namespace's order is its precedence, #419);
- only ``*`` makes a glob, so a literal ``?`` or ``[`` keeps its meaning;
- a glob with a refused match is skipped whole (#856);
- a glob that matches nothing leaves the namespace configured with no
  directories, so its scope is reported unsearched, never silently absent (#842).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

import pytest

from pyeye.config import ProjectConfig

MODEL = "from pydantic import BaseModel\n\n\nclass {name}(BaseModel):\n    x: int\n"


def _repos(tmp_path: Path, *names: str) -> Path:
    """``repos/<name>/co/models.py`` per name, created in the order given."""
    repos = tmp_path / "repos"
    for name in names:
        pkg = repos / name / "co"
        pkg.mkdir(parents=True)
        (pkg / "models.py").write_text(MODEL.format(name=name.title().replace("-", "")))
    return repos


def _config(tmp_path: Path, namespaces: dict[str, list[str]], **extra: Any) -> ProjectConfig:
    proj = tmp_path / "proj"
    (proj / "app").mkdir(parents=True, exist_ok=True)
    (proj / ".pyeye.json").write_text(
        json.dumps({"namespaces": namespaces, **extra}), encoding="utf-8"
    )
    return ProjectConfig(proj.as_posix())


class TestExpansion:
    def test_a_glob_entry_maps_to_its_matches(self, tmp_path: Path) -> None:
        repos = _repos(tmp_path, "co-a", "co-b")

        config = _config(tmp_path, {"co": [f"{repos.as_posix()}/co-*"]})

        assert config.get_namespaces() == {
            "co": [(repos / "co-a").as_posix(), (repos / "co-b").as_posix()]
        }

    def test_matches_are_sorted_whatever_the_filesystem_order(self, tmp_path: Path) -> None:
        repos = _repos(tmp_path, "co-c", "co-a", "co-b")

        dirs = _config(tmp_path, {"co": [f"{repos.as_posix()}/co-*"]}).get_namespaces()["co"]

        assert dirs == sorted(dirs)
        assert len(dirs) == 3

    def test_package_glob_matches_are_sorted_too(self, tmp_path: Path) -> None:
        repos = _repos(tmp_path, "co-c", "co-a", "co-b")

        paths = _config(tmp_path, {}, packages=[f"{repos.as_posix()}/co-*"]).get_package_paths()

        assert paths[1:] == sorted(paths[1:])

    def test_namespaces_and_package_paths_agree(self, tmp_path: Path) -> None:
        repos = _repos(tmp_path, "co-a", "co-b")
        config = _config(tmp_path, {"co": [f"{repos.as_posix()}/co-*"]})

        assert set(config.get_namespaces()["co"]) <= set(config.get_package_paths())

    def test_relative_and_explicit_entries_are_unchanged(self, tmp_path: Path) -> None:
        repos = _repos(tmp_path, "co-a")

        config = _config(tmp_path, {"co": ["../repos/co-a"]})

        assert config.get_namespaces() == {"co": [(repos / "co-a").as_posix()]}

    @pytest.mark.parametrize(
        ("name", "as_glob_matches"),
        [
            ("co[1]", "co1"),
            pytest.param(
                "co?",
                "cox",
                marks=pytest.mark.skipif(
                    os.name == "nt", reason="Windows forbids '?' in file names"
                ),
            ),
        ],
        ids=["brackets", "question-mark"],
    )
    def test_question_mark_and_brackets_are_literal(
        self, tmp_path: Path, name: str, as_glob_matches: str
    ) -> None:
        """Only ``*`` expands: a path containing ``?`` or ``[`` keeps its meaning."""
        literal = tmp_path / "repos" / name
        literal.mkdir(parents=True)
        (tmp_path / "repos" / as_glob_matches).mkdir()  # what *name* would match as a glob

        config = _config(tmp_path, {"co": [literal.as_posix()]})

        assert config.get_namespaces() == {"co": [literal.as_posix()]}


class TestNoMatch:
    def test_the_namespace_stays_configured_with_no_dirs(self, tmp_path: Path) -> None:
        config = _config(tmp_path, {"co": [f"{tmp_path.as_posix()}/nothing-*"]})

        assert config.get_namespaces() == {"co": []}

    def test_its_scope_is_reported_unsearched(self, tmp_path: Path) -> None:
        config = _config(tmp_path, {"co": [f"{tmp_path.as_posix()}/nothing-*"]})

        payload = _envelope(config, "all")

        assert "namespace:co" in payload["unsearched_scopes"]
        assert "namespace:co" not in payload["searched"]


@pytest.mark.skipif(os.name == "nt", reason="the deny-list names POSIX system directories")
def test_a_glob_with_a_refused_match_is_skipped_whole(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    repos = _repos(tmp_path, "co-a")
    (repos / "co-z").symlink_to("/etc", target_is_directory=True)

    with caplog.at_level(logging.WARNING):
        config = _config(tmp_path, {"co": [f"{repos.as_posix()}/co-*"]})
        namespaces = config.get_namespaces()

    assert namespaces == {"co": []}
    assert "restricted location" in caplog.text


def _envelope(config: ProjectConfig, scope: str) -> dict[str, Any]:
    from mcp.server.mcpserver import MCPServer

    from pyeye.mcp.server import _PLUGIN_CLASSES, _apply_plugin_paths, register_plugin_tools
    from pyeye.scope_utils import SmartScopeResolver

    project = config.project_path.as_posix()
    plugins = [cls(project) for cls in _PLUGIN_CLASSES]
    for plugin in plugins:
        _apply_plugin_paths(plugin, config)  # as initialize_plugins does
    server = MCPServer("namespace-globs")
    register_plugin_tools(server, plugins, SmartScopeResolver(config))
    result = asyncio.run(
        server.call_tool(
            "find_pydantic_models", {"scope": scope, "envelope": True, "project_path": project}
        )
    )
    assert not result.is_error, result.content
    payload = json.loads(result.content[0].text)
    assert isinstance(payload, dict)
    return payload


def test_a_namespace_scope_from_a_glob_finds_the_matches(tmp_path: Path) -> None:
    """End to end: before #872, ``namespace:co`` searched the literal pattern: nothing."""
    repos = _repos(tmp_path, "co-a", "co-b")
    config = _config(tmp_path, {"co": [f"{repos.as_posix()}/co-*"]})

    payload = _envelope(config, "namespace:co")

    assert {m["name"] for m in payload["results"]} == {"CoA", "CoB"}
    assert payload["searched"] == ["namespace:co"]

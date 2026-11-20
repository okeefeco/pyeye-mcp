"""``configure_packages(save=True)`` writes only the project's explicit config (#1038).

It used to dump the whole merged config to ``.pyeye.json``, so a save froze
re-derived packages (sibling discovery, the ``src/`` layout, ``[tool.pyright]
extraPaths``, build-backend layouts) into the project's file, and copied in the
user's global config and the local ``.pyeye.override.json``.

Now a save writes the project config file's own content, plus this call's
entries and the session's unsaved ones (#953). The response's always-present
``discovered`` lists each package pyeye added on its own, and why.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest


def _configure(proj: Path, **args: Any) -> dict[str, Any]:
    from pyeye.mcp.server import mcp

    result = asyncio.run(
        mcp.call_tool("configure_packages", {**args, "project_path": proj.as_posix()})
    )
    assert not result.is_error, result.content
    payload = result.structured_content
    assert isinstance(payload, dict)
    return payload


def _saved(proj: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((proj / ".pyeye.json").read_text(encoding="utf-8"))
    return data


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """No real global config: each test writes its own when it needs one."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    return home


@pytest.fixture
def parent(tmp_path: Path) -> Path:
    """A project with siblings: two that discovery picks up, and a library to configure."""
    root = tmp_path / "parent"
    (root / "proj" / "app").mkdir(parents=True)
    (root / "proj" / "app" / "__init__.py").write_text("", encoding="utf-8")
    (root / "unrelated1").mkdir()
    (root / "unrelated1" / "script.py").write_text("x = 1\n", encoding="utf-8")
    (root / "unrelated2").mkdir()
    (root / "unrelated2" / "setup.py").write_text("", encoding="utf-8")
    (root / "lib" / "mylib").mkdir(parents=True)
    (root / "lib" / "mylib" / "__init__.py").write_text("", encoding="utf-8")
    return root


class TestSaveWritesOnlyExplicitConfig:
    def test_discovered_siblings_are_not_saved(self, parent: Path) -> None:
        proj, lib = parent / "proj", (parent / "lib").as_posix()

        _configure(proj, packages=[lib], save=True)

        assert _saved(proj) == {"packages": [lib]}

    def test_a_src_layout_is_not_saved(self, tmp_path: Path) -> None:
        proj = tmp_path / "solo" / "proj"
        (proj / "src" / "pkg").mkdir(parents=True)
        (proj / "src" / "pkg" / "__init__.py").write_text("", encoding="utf-8")
        lib = tmp_path / "elsewhere" / "lib"
        lib.mkdir(parents=True)

        _configure(proj, packages=[lib.as_posix()], save=True)

        assert _saved(proj) == {"packages": [lib.as_posix()]}

    def test_pyright_and_build_backend_paths_are_not_saved(self, tmp_path: Path) -> None:
        proj = tmp_path / "solo" / "proj"
        (proj / "typings").mkdir(parents=True)
        (proj / "lib").mkdir()
        (proj / "pyproject.toml").write_text(
            '[tool.pyright]\nextraPaths = ["typings"]\n',
            encoding="utf-8",
        )
        extra = tmp_path / "elsewhere" / "extra"
        extra.mkdir(parents=True)

        _configure(proj, packages=[extra.as_posix()], save=True)

        assert _saved(proj) == {"packages": [extra.as_posix()]}

    def test_the_global_config_is_not_copied_in(
        self, parent: Path, _isolated_home: Path, tmp_path: Path
    ) -> None:
        shared = tmp_path / "shared-lib"
        shared.mkdir()
        (_isolated_home / ".pyeye.json").write_text(
            json.dumps({"packages": [shared.as_posix()], "scope_aliases": {"x": ["main"]}}),
            encoding="utf-8",
        )
        proj, lib = parent / "proj", (parent / "lib").as_posix()

        _configure(proj, packages=[lib], save=True)

        assert _saved(proj) == {"packages": [lib]}

    def test_the_local_override_is_not_copied_in(self, parent: Path, tmp_path: Path) -> None:
        local = tmp_path / "local-checkout"
        local.mkdir()
        proj, lib = parent / "proj", (parent / "lib").as_posix()
        (proj / ".pyeye.override.json").write_text(
            json.dumps({"packages": [local.as_posix()]}), encoding="utf-8"
        )

        _configure(proj, packages=[lib], save=True)

        assert _saved(proj) == {"packages": [lib]}

    def test_the_project_files_own_content_is_kept(self, parent: Path) -> None:
        proj, lib = parent / "proj", (parent / "lib").as_posix()
        (proj / ".pyeye.json").write_text(
            json.dumps({"packages": ["../unrelated1"], "scope_defaults": {"methods": {}}}),
            encoding="utf-8",
        )

        _configure(proj, packages=[lib], save=True)

        assert _saved(proj) == {
            "packages": ["../unrelated1", lib],
            "scope_defaults": {"methods": {}},
        }

    def test_a_pyproject_tool_section_carries_over(self, tmp_path: Path) -> None:
        """As before, a save writes .pyeye.json; the project's own [tool.pyeye] goes with it."""
        proj = tmp_path / "solo" / "proj"
        proj.mkdir(parents=True)
        (proj / "pyproject.toml").write_text(
            '[tool.pyeye]\nscope_aliases = { mine = ["main"] }\n', encoding="utf-8"
        )
        lib = tmp_path / "elsewhere" / "lib"
        lib.mkdir(parents=True)

        _configure(proj, packages=[lib.as_posix()], save=True)

        assert _saved(proj) == {"scope_aliases": {"mine": ["main"]}, "packages": [lib.as_posix()]}

    def test_unsaved_entries_are_still_persisted(self, parent: Path, tmp_path: Path) -> None:
        """#953 unchanged: a save writes the session's unsaved entries too."""
        proj, lib = parent / "proj", (parent / "lib").as_posix()
        other = tmp_path / "other"
        other.mkdir()
        _configure(proj, packages=[other.as_posix()], save=False)

        _configure(proj, packages=[lib], save=True)

        assert _saved(proj) == {"packages": [other.as_posix(), lib]}


class TestDiscovered:
    def test_siblings_are_listed_with_why(self, parent: Path) -> None:
        response = _configure(parent / "proj")

        assert response["discovered"] == [
            {"path": (parent / "unrelated1").as_posix(), "reason": "sibling"},
            {"path": (parent / "unrelated2").as_posix(), "reason": "sibling"},
        ]

    def test_a_src_layout_is_listed(self, tmp_path: Path) -> None:
        proj = tmp_path / "solo" / "proj"
        (proj / "src" / "pkg").mkdir(parents=True)
        (proj / "src" / "pkg" / "__init__.py").write_text("", encoding="utf-8")

        response = _configure(proj)

        assert response["discovered"] == [
            {"path": (proj / "src").resolve().as_posix(), "reason": "src_layout"}
        ]

    def test_pyright_extra_paths_are_listed(self, tmp_path: Path) -> None:
        proj = tmp_path / "solo" / "proj"
        (proj / "typings").mkdir(parents=True)
        (proj / "pyproject.toml").write_text(
            '[tool.pyright]\nextraPaths = ["typings"]\n', encoding="utf-8"
        )

        response = _configure(proj)

        assert response["discovered"] == [
            {"path": (proj / "typings").resolve().as_posix(), "reason": "pyright_extra_paths"}
        ]

    def test_a_build_backend_layout_is_listed(self, tmp_path: Path) -> None:
        proj = tmp_path / "solo" / "proj"
        (proj / "lib").mkdir(parents=True)
        (proj / "pyproject.toml").write_text(
            '[tool.setuptools.packages.find]\nwhere = ["lib"]\n', encoding="utf-8"
        )

        response = _configure(proj)

        assert response["discovered"] == [
            {"path": (proj / "lib").resolve().as_posix(), "reason": "build_backend_layout"}
        ]

    def test_it_is_empty_when_packages_are_configured(self, parent: Path) -> None:
        proj, lib = parent / "proj", (parent / "lib").as_posix()
        _configure(proj, packages=[lib], save=True)

        assert _configure(proj)["discovered"] == []

    def test_every_discovered_path_is_a_package(self, parent: Path) -> None:
        """What's listed is what is analysed: each one is in ``packages`` too."""
        response = _configure(parent / "proj")

        assert {d["path"] for d in response["discovered"]} <= set(response["packages"])

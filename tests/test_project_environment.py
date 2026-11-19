"""The project's Python environment is found and read statically (#993).

Isolated installs (the Claude Code plugin, ``uvx``, ``uv tool``) run pyeye outside
the project's environment. Before #993, a ``src/`` project there resolved none of
its third-party packages, and every project's imports could resolve against
PYEYE's own dependencies instead. The maintainer's ruling:

- precedence: config ``environment`` (path | false) -> an in-project venv
  (``.venv``, ``venv``, ``env`` with ``pyvenv.cfg``; one level up for a
  root-is-package project) -> ``VIRTUAL_ENV`` / ``CONDA_PREFIX`` unless it is
  pyeye's own -> none;
- read statically, never running the environment's interpreter: its
  ``site-packages`` and the ``.pth`` plain-path lines (import lines skipped);
- pyeye's own site-packages never on Jedi's path, venv or not;
- disclosure: ``configure_packages``' ``environment``, a once-per-project warning,
  and a not-found note for third-party names when none was found.

A venv here is a ``pyvenv.cfg`` and a ``site-packages`` directory: nothing reads
or runs an interpreter, which is the point.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

import pytest

from pyeye import environment as env_module
from pyeye.environment import discover, site_paths

PYTHON = f"python{sys.version_info.major}.{sys.version_info.minor}"


def _venv(path: Path, *, version: str | None = None, windows: bool = False) -> Path:
    """A virtualenv on disk with ``fakelib`` installed; returns its site-packages."""
    path.mkdir(parents=True, exist_ok=True)
    cfg = "home = /usr/bin\n" + (f"version = {version}.1\n" if version else "")
    (path / "pyvenv.cfg").write_text(cfg, encoding="utf-8")
    site = path / "Lib" / "site-packages" if windows else path / "lib" / PYTHON / "site-packages"
    (site / "fakelib").mkdir(parents=True)
    (site / "fakelib" / "__init__.py").write_text("def helper() -> int:\n    return 1\n")
    return site


def _project(root: Path, *, layout: str = "src") -> Path:
    pkg = root / "src" / "app" if layout == "src" else root / "app"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "main.py").write_text("from fakelib import helper\n", encoding="utf-8")
    return root


@pytest.fixture(autouse=True)
def _no_activation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests set VIRTUAL_ENV / CONDA_PREFIX themselves; the runner's must not leak in."""
    for var in env_module.ACTIVATION_VARS:
        monkeypatch.delenv(var, raising=False)
    env_module._WARNED.clear()


def _call(tool: str, **args: Any) -> dict[str, Any]:
    from pyeye.mcp.server import mcp

    result = asyncio.run(mcp.call_tool(tool, args))
    assert not result.is_error, result.content
    payload = result.structured_content
    assert isinstance(payload, dict)
    return payload


class TestPrecedence:
    @pytest.mark.parametrize("name", ["venv", "env", ".venv"])
    def test_an_in_project_venv(self, tmp_path: Path, name: str) -> None:
        _venv(tmp_path / name)

        found = discover(tmp_path)

        assert (found.path, found.source) == ((tmp_path / name).resolve(), "project")

    def test_dot_venv_is_tried_first(self, tmp_path: Path) -> None:
        _venv(tmp_path / "venv")
        _venv(tmp_path / ".venv")

        assert discover(tmp_path).path == (tmp_path / ".venv").resolve()

    def test_a_directory_without_pyvenv_cfg_is_not_a_venv(self, tmp_path: Path) -> None:
        (tmp_path / ".venv" / "lib").mkdir(parents=True)

        assert discover(tmp_path).source == "none"

    def test_a_root_is_package_project_looks_one_level_up(self, tmp_path: Path) -> None:
        _venv(tmp_path / ".venv")
        pkg = tmp_path / "mypkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("", encoding="utf-8")

        assert discover(pkg).path == (tmp_path / ".venv").resolve()

    def test_config_wins_over_an_in_project_venv(self, tmp_path: Path) -> None:
        _venv(tmp_path / ".venv")
        _venv(tmp_path / "elsewhere" / "env")

        found = discover(tmp_path, "elsewhere/env")

        assert (found.path, found.source) == ((tmp_path / "elsewhere" / "env").resolve(), "config")

    def test_config_false_opts_out(self, tmp_path: Path) -> None:
        _venv(tmp_path / ".venv")

        found = discover(tmp_path, False)

        assert (found.path, found.source, found.site_paths) == (None, "config", ())

    def test_a_refused_config_path_is_skipped_with_a_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        if sys.platform == "win32":
            pytest.skip("the deny-list names POSIX system directories (#867)")
        _venv(tmp_path / ".venv")

        with caplog.at_level(logging.WARNING):
            found = discover(tmp_path, "/etc")

        assert found.source == "project"  # falls through to discovery
        assert "restricted location" in caplog.text

    def test_an_in_project_venv_beats_an_activated_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The ruling's one deviation: one server answers for many projects (#665)."""
        _venv(tmp_path / "proj" / ".venv")
        _venv(tmp_path / "poetry-cache" / "proj-abc")
        monkeypatch.setenv("VIRTUAL_ENV", (tmp_path / "poetry-cache" / "proj-abc").as_posix())

        assert discover(tmp_path / "proj").source == "project"

    @pytest.mark.parametrize("var", ["VIRTUAL_ENV", "CONDA_PREFIX"])
    def test_an_activated_environment_outside_the_project(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, var: str
    ) -> None:
        """Poetry, Pipenv, Hatch or conda environments live outside the project."""
        (tmp_path / "proj").mkdir()
        outside = tmp_path / "poetry-cache" / "proj-abc"
        _venv(outside)
        monkeypatch.setenv(var, outside.as_posix())

        found = discover(tmp_path / "proj")

        assert (found.path, found.source) == (outside.resolve(), var)

    def test_pyeyes_own_environment_is_never_the_projects(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Under the plugin, ``uv run`` sets VIRTUAL_ENV to pyeye's own environment."""
        monkeypatch.setenv("VIRTUAL_ENV", sys.prefix)

        assert discover(tmp_path).source == "none"


class TestStaticReading:
    def test_posix_site_packages(self, tmp_path: Path) -> None:
        site = _venv(tmp_path / ".venv")

        assert site_paths(tmp_path / ".venv") == [site.resolve().as_posix()]

    def test_windows_site_packages(self, tmp_path: Path) -> None:
        site = _venv(tmp_path / ".venv", windows=True)

        assert site_paths(tmp_path / ".venv") == [site.resolve().as_posix()]

    def test_the_pyvenv_cfg_version_is_preferred(self, tmp_path: Path) -> None:
        venv = tmp_path / ".venv"
        _venv(venv, version="3.11")
        other = venv / "lib" / "python3.11" / "site-packages"
        other.mkdir(parents=True)

        assert site_paths(venv) == [other.resolve().as_posix()]

    def test_pth_plain_lines_are_added_and_import_lines_never_run(self, tmp_path: Path) -> None:
        site = _venv(tmp_path / ".venv")
        editable = tmp_path / "editable-src"
        editable.mkdir()
        marker = tmp_path / "ran"
        (site / "a_editable.pth").write_text(
            f"# a comment\n{editable.as_posix()}\n\nmissing-dir\n"
            f"import pathlib; pathlib.Path({marker.as_posix()!r}).touch()\n",
            encoding="utf-8",
        )

        paths = site_paths(tmp_path / ".venv")

        assert paths == [site.resolve().as_posix(), editable.resolve().as_posix()]
        assert not marker.exists()  # the import line was skipped, not executed


class TestJedi:
    def test_jedi_runs_pyeyes_interpreter_whatever_is_activated(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Jedi's default follows VIRTUAL_ENV and would run that environment's Python."""
        from pyeye._jedi_project import make_project, own_environment

        _venv(tmp_path / "activated")
        monkeypatch.setenv("VIRTUAL_ENV", (tmp_path / "activated").as_posix())

        project = make_project(tmp_path)

        assert project.get_environment() is own_environment()

    @pytest.mark.parametrize("layout", ["src", "flat"])
    def test_third_party_resolves_external_in_both_layouts(
        self, tmp_path: Path, layout: str
    ) -> None:
        proj = _project(tmp_path / "proj", layout=layout)
        _venv(proj / ".venv")

        resolved = _call("resolve", identifier="fakelib.helper", project_path=proj.as_posix())
        imports = _call("expand", handle="app.main", edge="imports", project_path=proj.as_posix())

        assert (resolved["handle"], resolved["scope"]) == ("fakelib.helper", "external")
        assert [(s["handle"], s["scope"]) for s in imports["stubs"]] == [
            ("fakelib.helper", "external")
        ]

    def test_pyeyes_own_dependencies_never_resolve_for_the_project(self, tmp_path: Path) -> None:
        """pydantic is pyeye's dependency, not this project's: it must not resolve."""
        proj = _project(tmp_path / "proj")
        _venv(proj / ".venv")

        resolved = _call("resolve", identifier="pydantic.BaseModel", project_path=proj.as_posix())

        assert resolved["found"] is False

    def test_the_venv_is_not_a_configured_package(self, tmp_path: Path) -> None:
        """A flat project listed site-packages as a package before #993."""
        proj = _project(tmp_path / "proj", layout="flat")
        site = _venv(proj / ".venv")

        packages = _call("configure_packages", save=False, project_path=proj.as_posix())["packages"]

        assert site.resolve().as_posix() not in packages

    def test_the_environment_joins_the_layout_key(self, tmp_path: Path) -> None:
        from pyeye.analyzers.jedi_analyzer import JediAnalyzer
        from pyeye.project_layout import layout_key

        proj = _project(tmp_path / "proj")
        before = layout_key(JediAnalyzer(proj.as_posix()))
        _venv(proj / ".venv")

        assert layout_key(JediAnalyzer(proj.as_posix())) != before


class TestDisclosure:
    def test_configure_packages_reports_the_environment(self, tmp_path: Path) -> None:
        proj = _project(tmp_path / "proj")
        _venv(proj / ".venv")

        environment = _call("configure_packages", save=False, project_path=proj.as_posix())[
            "environment"
        ]

        assert environment == {"path": (proj / ".venv").resolve().as_posix(), "source": "project"}

    def test_it_is_present_with_no_environment(self, tmp_path: Path) -> None:
        proj = _project(tmp_path / "proj")

        environment = _call("configure_packages", save=False, project_path=proj.as_posix())[
            "environment"
        ]

        assert environment == {"path": None, "source": "none"}

    def test_a_third_party_miss_says_no_environment_was_found(self, tmp_path: Path) -> None:
        proj = _project(tmp_path / "proj")
        p = proj.as_posix()

        for payload in (
            _call("resolve", identifier="fakelib.helper", project_path=p),
            _call("inspect", handle="fakelib.helper", project_path=p),
        ):
            assert payload["found"] is False
            assert env_module.NO_ENVIRONMENT_NOTE in payload["detail"]

    @pytest.mark.parametrize("name", ["app.nothing_here", "json.not_there"])
    def test_a_project_or_stdlib_miss_carries_no_such_note(self, tmp_path: Path, name: str) -> None:
        proj = _project(tmp_path / "proj")

        payload = _call("resolve", identifier=name, project_path=proj.as_posix())

        assert payload["found"] is False
        assert env_module.NO_ENVIRONMENT_NOTE not in payload["detail"]

    def test_with_an_environment_a_miss_carries_no_such_note(self, tmp_path: Path) -> None:
        proj = _project(tmp_path / "proj")
        _venv(proj / ".venv")

        payload = _call("resolve", identifier="notinstalled.thing", project_path=proj.as_posix())

        assert env_module.NO_ENVIRONMENT_NOTE not in payload["detail"]

    def test_the_warning_is_logged_once_per_project(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        from pyeye.project_manager import ProjectManager

        proj = _project(tmp_path / "proj")
        manager = ProjectManager(max_projects=2)
        try:
            with caplog.at_level(logging.WARNING):
                manager.get_analyzer(proj.as_posix())
                manager.invalidate_analyzer(proj.as_posix())
                manager.get_analyzer(proj.as_posix())
        finally:
            manager.cleanup_all()

        assert caplog.text.count("No Python environment found") == 1

    def test_the_config_key_is_a_documented_config_key(self) -> None:
        from pyeye.config import CONFIG_KEYS

        assert "environment" in CONFIG_KEYS
        assert json.dumps(CONFIG_KEYS)

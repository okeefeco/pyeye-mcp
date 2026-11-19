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
import os
import sys
from collections.abc import Iterator
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


_POSIX_ONLY = pytest.mark.skipif(sys.platform == "win32", reason="the deny-list is POSIX forms")


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """The server's own home (``Path.home()``) at a tmp dir: its credential stores are refused."""
    from pyeye import validation

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    validation._credential_pattern.cache_clear()
    yield home
    monkeypatch.undo()
    validation._credential_pattern.cache_clear()


class TestPathChecks:
    """A repository can ship its own venv, so its import roots are path-checked (#993)."""

    @_POSIX_ONLY
    @pytest.mark.parametrize("line", ["/etc", "/", "/proc/self"])
    def test_a_pth_line_into_a_restricted_dir_is_dropped(
        self, tmp_path: Path, line: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        site = _venv(tmp_path / ".venv")
        (site / "evil.pth").write_text(f"{line}\n", encoding="utf-8")

        with caplog.at_level(logging.WARNING, logger="pyeye.environment"):
            paths = site_paths(tmp_path / ".venv")

        assert paths == [site.resolve().as_posix()]
        assert "Skipping .pth path" in caplog.text

    @_POSIX_ONLY
    def test_a_pth_line_climbing_with_dotdot_is_dropped(self, tmp_path: Path) -> None:
        site = _venv(tmp_path / ".venv")
        climb = "../" * (len(site.resolve().parts) + 2)
        (site / "evil.pth").write_text(f"{climb}etc\n{climb}\n", encoding="utf-8")

        assert site_paths(tmp_path / ".venv") == [site.resolve().as_posix()]

    @_POSIX_ONLY
    def test_a_pth_line_into_a_home_credential_store_is_dropped(
        self, tmp_path: Path, fake_home: Path
    ) -> None:
        (fake_home / ".ssh").mkdir()
        site = _venv(tmp_path / ".venv")
        (site / "evil.pth").write_text(f"{(fake_home / '.ssh').as_posix()}\n", encoding="utf-8")

        assert site_paths(tmp_path / ".venv") == [site.resolve().as_posix()]

    @_POSIX_ONLY
    def test_a_site_packages_symlinked_into_etc_is_dropped_unread(self, tmp_path: Path) -> None:
        venv = tmp_path / ".venv"
        venv.mkdir()
        (venv / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
        (venv / "lib" / PYTHON).mkdir(parents=True)
        (venv / "lib" / PYTHON / "site-packages").symlink_to("/etc", target_is_directory=True)

        assert site_paths(venv) == []
        assert discover(tmp_path).site_paths == ()

    def test_an_ordinary_pth_target_outside_the_project_is_kept(self, tmp_path: Path) -> None:
        site = _venv(tmp_path / "proj" / ".venv")
        elsewhere = tmp_path / "shared-src"
        elsewhere.mkdir()
        (site / "ok.pth").write_text(f"{elsewhere.as_posix()}\n", encoding="utf-8")

        assert site_paths(tmp_path / "proj" / ".venv")[-1] == elsewhere.resolve().as_posix()


class TestCandidateChecks:
    """The environment directory ITSELF is checked, from every source (#993 review)."""

    @_POSIX_ONLY
    def test_an_in_project_venv_symlinked_into_a_credential_store_is_refused(
        self, tmp_path: Path, fake_home: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The reviewer's case C: resolve found a module inside ``~/.ssh/venv``."""
        store_venv = fake_home / ".ssh" / "venv"
        _venv(store_venv)
        (tmp_path / "proj").mkdir()
        (tmp_path / "proj" / ".venv").symlink_to(store_venv, target_is_directory=True)

        with caplog.at_level(logging.WARNING, logger="pyeye.environment"):
            found = discover(tmp_path / "proj")

        assert (found.source, found.path, found.site_paths) == ("none", None, ())
        assert "Skipping project environment" in caplog.text

    @_POSIX_ONLY
    def test_a_refused_in_project_venv_falls_through_to_an_activated_one(
        self, tmp_path: Path, fake_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _venv(fake_home / ".aws" / "venv")
        (tmp_path / "proj").mkdir()
        (tmp_path / "proj" / ".venv").symlink_to(fake_home / ".aws" / "venv")
        _venv(tmp_path / "activated")
        monkeypatch.setenv("VIRTUAL_ENV", (tmp_path / "activated").as_posix())

        assert discover(tmp_path / "proj").source == "VIRTUAL_ENV"

    @_POSIX_ONLY
    @pytest.mark.parametrize("var", ["VIRTUAL_ENV", "CONDA_PREFIX"])
    @pytest.mark.parametrize("value", ["/etc", "/", "/proc/self"])
    def test_an_activation_variable_naming_a_restricted_dir_is_refused(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
        var: str,
        value: str,
    ) -> None:
        monkeypatch.setenv(var, value)

        with caplog.at_level(logging.WARNING, logger="pyeye.environment"):
            found = discover(tmp_path)

        assert (found.source, found.site_paths) == ("none", ())
        assert f"Skipping {var} environment" in caplog.text

    @_POSIX_ONLY
    def test_an_activated_environment_whose_site_packages_is_restricted_reads_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        conda = tmp_path / "conda-env"
        (conda / "lib" / PYTHON).mkdir(parents=True)
        (conda / "lib" / PYTHON / "site-packages").symlink_to("/etc", target_is_directory=True)
        monkeypatch.setenv("CONDA_PREFIX", conda.as_posix())

        found = discover(tmp_path)

        assert (found.source, found.site_paths) == ("CONDA_PREFIX", ())


class TestBounds:
    """A repository's ``.pth`` files can't make building the analyzer slow (#993 review)."""

    def test_lines_are_deduplicated_before_the_per_file_cap(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(env_module, "MAX_PTH_LINES", 2)
        site = _venv(tmp_path / ".venv")
        a, b, c = (tmp_path / n for n in "abc")
        for d in (a, b, c):
            d.mkdir()
        repeated = f"{a.as_posix()}\n" * 5000
        (site / "big.pth").write_text(
            f"{repeated}{b.as_posix()}\n{c.as_posix()}\n", encoding="utf-8"
        )

        assert site_paths(tmp_path / ".venv")[1:] == [
            a.resolve().as_posix(),
            b.resolve().as_posix(),
        ]

    def test_a_pth_file_is_read_only_up_to_the_byte_cap(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        site = _venv(tmp_path / ".venv")
        first, later = tmp_path / "first", tmp_path / "later"
        first.mkdir()
        later.mkdir()
        head = f"{first.as_posix()}\n"
        (site / "big.pth").write_text(
            head + "#" * 100 + f"\n{later.as_posix()}\n", encoding="utf-8"
        )
        monkeypatch.setattr(env_module, "MAX_PTH_BYTES", len(head.encode()))

        with caplog.at_level(logging.WARNING, logger="pyeye.environment"):
            paths = site_paths(tmp_path / ".venv")

        assert paths[1:] == [first.resolve().as_posix()]
        assert "bytes; reading only the start" in caplog.text

    def test_the_environment_has_a_total_cap(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setattr(env_module, "MAX_SITE_PATHS", 3)
        site = _venv(tmp_path / ".venv")
        for i in range(5):
            (tmp_path / f"d{i}").mkdir()
            (site / f"p{i}.pth").write_text(
                f"{(tmp_path / f'd{i}').as_posix()}\n", encoding="utf-8"
            )

        with caplog.at_level(logging.WARNING, logger="pyeye.environment"):
            paths = site_paths(tmp_path / ".venv")

        # The cap counts roots that exist, site-packages included.
        assert paths[1:] == [(tmp_path / f"d{i}").resolve().as_posix() for i in range(2)]
        assert "import roots; reading no further" in caplog.text

    def test_a_junk_pth_cannot_starve_a_later_files_real_entries(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Only roots that exist count toward MAX_SITE_PATHS (#993 re-review)."""
        monkeypatch.setattr(env_module, "MAX_SITE_PATHS", 2)
        site = _venv(tmp_path / ".venv")
        junk = "".join(f"{(tmp_path / f'missing{k}').as_posix()}\n" for k in range(50))
        (site / "a_junk.pth").write_text(junk, encoding="utf-8")
        (tmp_path / "real").mkdir()
        (site / "z_real.pth").write_text(f"{(tmp_path / 'real').as_posix()}\n", encoding="utf-8")

        assert site_paths(tmp_path / ".venv") == [
            site.resolve().as_posix(),
            (tmp_path / "real").resolve().as_posix(),
        ]

    def test_lookups_have_a_ceiling_found_or_not(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Many files of paths that don't exist can't make lookups unbounded."""
        monkeypatch.setattr(env_module, "MAX_PTH_LOOKUPS", 10)
        site = _venv(tmp_path / ".venv")
        for i in range(20):
            missing = "".join(f"{(tmp_path / f'missing{i}-{k}').as_posix()}\n" for k in range(4))
            (site / f"p{i:02}.pth").write_text(missing, encoding="utf-8")
        (tmp_path / "late").mkdir()
        (site / "zz.pth").write_text(f"{(tmp_path / 'late').as_posix()}\n", encoding="utf-8")
        looked_up: list[Path] = []
        real_is_dir = Path.is_dir

        def counting_is_dir(self: Path) -> bool:
            looked_up.append(self)
            return real_is_dir(self)

        monkeypatch.setattr(Path, "is_dir", counting_is_dir)
        with caplog.at_level(logging.WARNING, logger="pyeye.environment"):
            paths = site_paths(tmp_path / ".venv")

        assert paths == [site.resolve().as_posix()]  # zz.pth was never reached
        assert sum("missing" in p.name for p in looked_up) == 10
        assert "looked up; reading no further" in caplog.text

    def test_an_unchanged_pth_file_is_not_read_again(self, tmp_path: Path) -> None:
        site = _venv(tmp_path / ".venv")
        target = tmp_path / "editable"
        target.mkdir()
        pth = site / "e.pth"
        pth.write_text(f"{target.as_posix()}\n", encoding="utf-8")
        site_paths(tmp_path / ".venv")
        misses = env_module._pth_paths.cache_info().misses

        site_paths(tmp_path / ".venv")
        assert env_module._pth_paths.cache_info().misses == misses

        other = tmp_path / "other-editable"
        other.mkdir()
        pth.write_text(f"{target.as_posix()}\n{other.as_posix()}\n", encoding="utf-8")
        assert site_paths(tmp_path / ".venv")[-1] == other.resolve().as_posix()


@_POSIX_ONLY
class TestParentLookup:
    """A root-is-package project's parent is searched only when no one else could plant there."""

    @staticmethod
    def _package_under(parent: Path) -> Path:
        _venv(parent / ".venv")
        pkg = parent / "mypkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        return pkg

    def test_a_world_writable_parent_is_not_searched(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        shared = tmp_path / "shared"
        shared.mkdir()
        pkg = self._package_under(shared)
        shared.chmod(0o1777)  # the sticky /tmp case
        try:
            with caplog.at_level(logging.WARNING, logger="pyeye.environment"):
                found = discover(pkg)
        finally:
            shared.chmod(0o755)

        assert found.source == "none"
        assert "group- or world-writable, or owned by another user" in caplog.text

    def test_a_group_writable_parent_is_not_searched(self, tmp_path: Path) -> None:
        shared = tmp_path / "team"
        shared.mkdir()
        pkg = self._package_under(shared)
        shared.chmod(0o775)
        try:
            found = discover(pkg)
        finally:
            shared.chmod(0o755)

        assert found.source == "none"

    def test_a_parent_owned_by_another_user_is_not_searched(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pkg = self._package_under(tmp_path)
        real_uid = os.getuid()
        monkeypatch.setattr(env_module.os, "getuid", lambda: real_uid + 1)

        assert discover(pkg).source == "none"

    def test_the_package_root_itself_is_still_searched(self, tmp_path: Path) -> None:
        shared = tmp_path / "shared"
        shared.mkdir()
        pkg = self._package_under(shared)
        _venv(pkg / ".venv")
        shared.chmod(0o1777)
        try:
            found = discover(pkg)
        finally:
            shared.chmod(0o755)

        assert found.path == pkg / ".venv"


class TestSpelling:
    """``environment.path`` is in the caller's spelling, as other paths are (#717)."""

    @_POSIX_ONLY
    def test_an_in_project_venv_under_a_symlinked_root(self, tmp_path: Path) -> None:
        real = tmp_path / "real"
        site = _venv(real / ".venv")
        link = tmp_path / "link"
        link.symlink_to(real, target_is_directory=True)

        found = discover(link)

        assert found.as_response()["path"] == (link / ".venv").as_posix()
        assert found.site_paths == (site.resolve().as_posix(),)  # Jedi's form stays resolved

    @_POSIX_ONLY
    def test_a_configured_and_an_activated_environment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _venv(tmp_path / "real-env")
        (tmp_path / "env-link").symlink_to(tmp_path / "real-env", target_is_directory=True)
        (tmp_path / "proj").mkdir()

        configured = discover(tmp_path / "proj", "../env-link")
        monkeypatch.setenv("VIRTUAL_ENV", (tmp_path / "env-link").as_posix())
        activated = discover(tmp_path / "proj")

        assert configured.path == tmp_path / "env-link"
        assert activated.path == tmp_path / "env-link"


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

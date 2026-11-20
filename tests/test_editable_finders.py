"""Editable installs that use an import-hook ``.pth`` are read statically (#1035 part 1).

Measured per build backend (#1035): most editable installs write a plain path
to a ``.pth`` file, which #993 reads. Three write an import line instead, and
#993 skips those, because pyeye never runs the environment's code:

- setuptools with a flat layout: ``import __editable___<n>_finder; ...install()``,
  whose module holds ``MAPPING: dict[str, str] = {...}`` and ``NAMESPACES``;
- hatchling ``dev-mode-exact`` and pdm-backend ``editable-backend = "editables"``:
  ``import _editable_impl_<n>``, whose module calls ``F.map_module(name, path)``.

pyeye now reads those targets from the module's text: only ``M.py`` in the SAME
site-packages directory, not a symlink, under the size cap, parsed with ``ast``
and never imported, and only the two literal shapes (plain str / list / dict).
Every target is path-checked and counts toward the existing bounds.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from pyeye import environment as env_module
from pyeye.environment import site_paths

PYTHON = f"python{sys.version_info.major}.{sys.version_info.minor}"
_POSIX_ONLY = pytest.mark.skipif(sys.platform == "win32", reason="POSIX paths and symlinks")


def _site(tmp_path: Path) -> Path:
    venv = tmp_path / ".venv"
    site = venv / "lib" / PYTHON / "site-packages"
    site.mkdir(parents=True)
    (venv / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
    return site


def _flat_project(tmp_path: Path, name: str = "flatpkg") -> Path:
    project = tmp_path / "work" / name
    (project / name).mkdir(parents=True)
    (project / name / "__init__.py").write_text("X = 1\n", encoding="utf-8")
    return project


def _setuptools_finder(site: Path, mapping: str, namespaces: str = "{}") -> None:
    """A finder shaped exactly as setuptools writes one (measured, #1035)."""
    name = "__editable___flatpkg_0_1_finder"
    (site / "__editable__.flatpkg-0.1.pth").write_text(
        f"import {name}; {name}.install()", encoding="utf-8"
    )
    (site / f"{name}.py").write_text(
        "import sys\n"
        "from importlib.machinery import ModuleSpec, PathFinder\n"
        "\n"
        f"MAPPING: dict[str, str] = {mapping}\n"
        f"NAMESPACES: dict[str, list[str]] = {namespaces}\n"
        "PATH_PLACEHOLDER = '__editable__.flatpkg-0.1.finder' + \".__path_hook__\"\n"
        "\n"
        "def install():\n"
        "    pass\n",
        encoding="utf-8",
    )


def _editables_finder(site: Path, calls: str) -> None:
    """An ``editables`` redirector, as hatchling and pdm-backend write one (measured)."""
    (site / "_editable_impl_flatpkg.pth").write_text("import _editable_impl_flatpkg", "utf-8")
    (site / "_editable_impl_flatpkg.py").write_text(
        "from editables.redirector import RedirectingFinder as F\nF.install()\n" + calls,
        encoding="utf-8",
    )


@pytest.fixture(autouse=True)
def _fresh_cache() -> None:
    env_module._pth_paths.cache_clear()


class TestRecovered:
    def test_a_setuptools_flat_layout_finder(self, tmp_path: Path) -> None:
        site, project = _site(tmp_path), _flat_project(tmp_path)
        _setuptools_finder(site, f"{{'flatpkg': {str((project / 'flatpkg').as_posix())!r}}}")

        assert site_paths(tmp_path / ".venv") == [
            site.resolve().as_posix(),
            project.resolve().as_posix(),
        ]

    def test_setuptools_namespaces(self, tmp_path: Path) -> None:
        site = _site(tmp_path)
        portion = tmp_path / "work" / "nsrepo"
        (portion / "acme" / "tools").mkdir(parents=True)
        _setuptools_finder(site, "{}", f"{{'acme': [{str((portion / 'acme').as_posix())!r}]}}")

        assert site_paths(tmp_path / ".venv")[1:] == [portion.resolve().as_posix()]

    def test_an_editables_redirector(self, tmp_path: Path) -> None:
        site, project = _site(tmp_path), _flat_project(tmp_path)
        module = tmp_path / "work" / "single.py"
        module.write_text("Y = 2\n", encoding="utf-8")
        _editables_finder(
            site,
            f"F.map_module('flatpkg', {str((project / 'flatpkg' / '__init__.py').as_posix())!r})\n"
            f"F.map_module('single', {str(module.as_posix())!r})\n",
        )

        assert site_paths(tmp_path / ".venv")[1:] == [
            project.resolve().as_posix(),
            (tmp_path / "work").resolve().as_posix(),
        ]

    def test_jedi_resolves_the_installed_package(self, tmp_path: Path) -> None:
        """End to end: the project's imports of the editable package resolve."""
        import asyncio

        from pyeye.mcp.server import mcp

        project = _flat_project(tmp_path)
        app = tmp_path / "app"
        app.mkdir()
        (app / "main.py").write_text("from flatpkg import X\n", encoding="utf-8")
        site = _site(app)
        _setuptools_finder(site, f"{{'flatpkg': {str((project / 'flatpkg').as_posix())!r}}}")

        result = asyncio.run(
            mcp.call_tool("resolve", {"identifier": "flatpkg.X", "project_path": app.as_posix()})
        )

        assert result.structured_content["found"] is True, result.structured_content


class TestNeverRun:
    def test_the_finder_is_parsed_not_imported(self, tmp_path: Path) -> None:
        site, project = _site(tmp_path), _flat_project(tmp_path)
        marker = tmp_path / "ran"
        _setuptools_finder(site, f"{{'flatpkg': {str((project / 'flatpkg').as_posix())!r}}}")
        finder = next(site.glob("__editable___*.py"))
        finder.write_text(
            f"import pathlib; pathlib.Path({str(marker.as_posix())!r}).touch()\n"
            + finder.read_text(encoding="utf-8"),
            encoding="utf-8",
        )

        site_paths(tmp_path / ".venv")

        assert not marker.exists()
        assert "__editable___flatpkg_0_1_finder" not in sys.modules


class TestHostile:
    @pytest.mark.parametrize(
        "mapping",
        [
            "{'flatpkg': f'{PREFIX}/flatpkg'}",  # an f-string
            "{'flatpkg': PREFIX}",  # a name
            "{'flatpkg': '/x' + '/flatpkg'}",  # an expression
            "dict(flatpkg='/x/flatpkg')",  # a call
            "{**OTHER}",  # a splat
        ],
    )
    def test_only_plain_literals_are_read(self, tmp_path: Path, mapping: str) -> None:
        site = _site(tmp_path)
        portion = tmp_path / "work" / "nsrepo"
        (portion / "acme").mkdir(parents=True)
        # A valid NAMESPACES beside the bad MAPPING: the reader is live, and
        # only the non-literal statement is ignored.
        _setuptools_finder(site, mapping, f"{{'acme': [{str((portion / 'acme').as_posix())!r}]}}")

        assert site_paths(tmp_path / ".venv") == [
            site.resolve().as_posix(),
            portion.resolve().as_posix(),
        ]

    @pytest.mark.parametrize(
        "call",
        [
            "F.map_module(NAME, '/x/flatpkg/__init__.py')\n",
            "F.map_module('flatpkg', PATH)\n",
            "F.map_module('flatpkg', '/x/flatpkg/__init__.py', extra=1)\n",
            "F.map_module(*ARGS)\n",
        ],
    )
    def test_only_plain_map_module_calls_are_read(self, tmp_path: Path, call: str) -> None:
        site, project = _site(tmp_path), _flat_project(tmp_path)
        good = (
            f"F.map_module('flatpkg', {str((project / 'flatpkg' / '__init__.py').as_posix())!r})\n"
        )
        _editables_finder(site, call + good)

        assert site_paths(tmp_path / ".venv") == [
            site.resolve().as_posix(),
            project.resolve().as_posix(),
        ]

    def test_a_finder_over_the_size_cap_is_not_read(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        site, project = _site(tmp_path), _flat_project(tmp_path)
        _setuptools_finder(site, f"{{'flatpkg': {str((project / 'flatpkg').as_posix())!r}}}")
        monkeypatch.setattr(env_module, "MAX_PTH_BYTES", 64)

        assert site_paths(tmp_path / ".venv") == [site.resolve().as_posix()]

    def test_a_deeply_nested_finder_is_not_a_crash(self, tmp_path: Path) -> None:
        site = _site(tmp_path)
        depth = 200_000
        _setuptools_finder(site, "{'flatpkg': " + "[" * depth + "'/x'" + "]" * depth + "}")

        assert site_paths(tmp_path / ".venv") == [site.resolve().as_posix()]

    @_POSIX_ONLY
    def test_a_target_in_a_restricted_directory_is_dropped(self, tmp_path: Path) -> None:
        site, project = _site(tmp_path), _flat_project(tmp_path)
        good = str((project / "flatpkg").as_posix())
        _setuptools_finder(site, f"{{'etcpkg': '/etc/etcpkg', 'etc': '/etc', 'flatpkg': {good!r}}}")

        assert site_paths(tmp_path / ".venv") == [
            site.resolve().as_posix(),
            project.resolve().as_posix(),
        ]

    @_POSIX_ONLY
    def test_a_target_in_a_credential_store_is_dropped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from pyeye import validation

        home = tmp_path / "home"
        (home / ".ssh" / "keys").mkdir(parents=True)
        monkeypatch.setattr(Path, "home", lambda: home)
        validation._credential_pattern.cache_clear()
        try:
            site, project = _site(tmp_path), _flat_project(tmp_path)
            keys, good = (home / ".ssh" / "keys").as_posix(), (project / "flatpkg").as_posix()
            _setuptools_finder(site, f"{{'keys': {keys!r}, 'flatpkg': {good!r}}}")

            assert site_paths(tmp_path / ".venv") == [
                site.resolve().as_posix(),
                project.resolve().as_posix(),
            ]
        finally:
            monkeypatch.undo()
            validation._credential_pattern.cache_clear()

    @_POSIX_ONLY
    def test_a_symlinked_finder_is_not_read(self, tmp_path: Path) -> None:
        site, project = _site(tmp_path), _flat_project(tmp_path)
        real = tmp_path / "elsewhere" / "finder.py"
        real.parent.mkdir()
        real.write_text(
            f"MAPPING = {{'flatpkg': {str((project / 'flatpkg').as_posix())!r}}}\n",
            encoding="utf-8",
        )
        (site / "__editable__.flatpkg-0.1.pth").write_text(
            "import __editable___flatpkg_0_1_finder", encoding="utf-8"
        )
        (site / "__editable___flatpkg_0_1_finder.py").symlink_to(real)

        assert site_paths(tmp_path / ".venv") == [site.resolve().as_posix()]

    @pytest.mark.parametrize(
        "line",
        ["import os", "import pkg.finder", "import ../evil", "import a, b; a.install()"],
    )
    def test_only_a_module_beside_the_pth_file_is_read(self, tmp_path: Path, line: str) -> None:
        """A dotted, relative or absent module is never looked up elsewhere."""
        site = _site(tmp_path)
        (site / "x.pth").write_text(line, encoding="utf-8")

        assert site_paths(tmp_path / ".venv") == [site.resolve().as_posix()]

    def test_finder_targets_count_toward_the_lookup_ceiling(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        site = _site(tmp_path)
        monkeypatch.setattr(env_module, "MAX_PTH_LINES", 3)
        mapping = ", ".join(f"'p{i}': '/nowhere/p{i}'" for i in range(50))
        _setuptools_finder(site, "{" + mapping + "}")
        looked_up: list[Path] = []
        real_is_dir = Path.is_dir

        def counting(self: Path) -> bool:
            looked_up.append(self)
            return real_is_dir(self)

        monkeypatch.setattr(Path, "is_dir", counting)
        site_paths(tmp_path / ".venv")

        assert sum("nowhere" in p.as_posix() for p in looked_up) <= 3

    def test_a_mapped_name_that_does_not_match_its_directory_is_skipped(
        self, tmp_path: Path
    ) -> None:
        """``{'flatpkg': '/x/other'}`` can't be expressed as a sys.path root."""
        site = _site(tmp_path)
        project = _flat_project(tmp_path, "goodpkg")
        other = tmp_path / "work" / "other"
        other.mkdir(parents=True)
        good = (project / "goodpkg").as_posix()
        _setuptools_finder(site, f"{{'flatpkg': {other.as_posix()!r}, 'goodpkg': {good!r}}}")

        assert site_paths(tmp_path / ".venv") == [
            site.resolve().as_posix(),
            project.resolve().as_posix(),
        ]

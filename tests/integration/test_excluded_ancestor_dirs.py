"""Exclusion rules apply only *below* the scan root, never to its ancestors (#515).

Directory-name exclusions (virtual envs, caches, build artifacts) are meant to
skip non-project directories *inside* a project. Three places instead tested the
name against every component of the *absolute* path. A project that merely
lives under a directory with one of those names was silently mis-scanned:

* ``rglob_async`` (``EXCLUDED_DIRS``) found **zero** files under e.g.
  ``~/dev/build/myproject`` or a CI workspace mounted at ``/build``.
* ``JediAnalyzer._discover_standalone_files`` did the same for standalone
  script directories.
* ``scope._has_build_artifact_segment`` matched ``.tox`` / ``__pycache__`` /
  ``*.egg-info`` anywhere, so every file of a project under ``.tox/`` was
  classified ``external``.

The existing suite never caught this because pytest's ``tmp_path`` lives under
``/tmp/pytest-of-*/``, which never collides with an excluded name.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.async_utils import rglob_async
from pyeye.scope import _has_build_artifact_segment, classify_scope

# Ancestor names that used to empty or misclassify a whole project.
_SCAN_ANCESTORS = ["build", "dist", "env", "venv", ".venv", "node_modules", ".tox", "pkg.egg-info"]
_SCOPE_ANCESTORS = [".tox", "__pycache__", "pkg.egg-info"]


def _make_project(base: Path) -> Path:
    """Create ``base/myproject`` with a source file and an excluded subdirectory."""
    proj = base / "myproject"
    (proj / "pkg").mkdir(parents=True)
    (proj / "app.py").write_text("")
    (proj / "pkg" / "__init__.py").write_text("")
    (proj / "pkg" / "core.py").write_text("")
    (proj / ".venv" / "lib").mkdir(parents=True)
    (proj / ".venv" / "lib" / "site.py").write_text("")
    (proj / "build").mkdir()
    (proj / "build" / "generated.py").write_text("")
    return proj


def _rel(paths: list[Path], root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in paths}


class TestRglobAsyncAncestors:
    """``rglob_async`` ignores excluded names above the scan root."""

    @pytest.mark.parametrize("ancestor", _SCAN_ANCESTORS)
    async def test_project_under_excluded_ancestor_scans_normally(self, tmp_path, ancestor):
        proj = _make_project(tmp_path / ancestor)

        found = _rel(await rglob_async("*.py", proj), proj)

        assert found == {"app.py", "pkg/__init__.py", "pkg/core.py"}

    async def test_excluded_dirs_inside_project_still_excluded(self, tmp_path):
        """Regression guard: the in-project exclusions are unchanged."""
        proj = _make_project(tmp_path)

        found = _rel(await rglob_async("*.py", proj), proj)

        assert ".venv/lib/site.py" not in found
        assert "build/generated.py" not in found

    async def test_scan_root_itself_named_build_returns_its_files(self, tmp_path):
        """Pointing the scan at a directory named ``build`` means scan it."""
        root = tmp_path / "build"
        root.mkdir()
        (root / "tool.py").write_text("")

        assert _rel(await rglob_async("*.py", root), root) == {"tool.py"}

    async def test_relative_scan_root(self, tmp_path, monkeypatch):
        """A relative scan root yields relative paths; filtering still works."""
        _make_project(tmp_path / "build")
        monkeypatch.chdir(tmp_path / "build")

        found = await rglob_async("*.py", Path("myproject"))

        assert {p.as_posix() for p in found} == {
            "myproject/app.py",
            "myproject/pkg/__init__.py",
            "myproject/pkg/core.py",
        }


class TestStandaloneDiscoveryAncestors:
    """Standalone script discovery ignores excluded names above the script dir."""

    @pytest.mark.parametrize("ancestor", ["build", "dist", "env", "venv", ".venv", ".tox"])
    async def test_standalone_dir_under_excluded_ancestor(self, tmp_path, ancestor):
        proj = tmp_path / ancestor / "myproject"
        scripts = proj / "scripts"
        (scripts / "build").mkdir(parents=True)
        (scripts / "tool.py").write_text("")
        (scripts / "build" / "generated.py").write_text("")
        analyzer = JediAnalyzer(str(proj))
        analyzer.set_standalone_paths([scripts])

        found = _rel(await analyzer._discover_standalone_files(), scripts)

        assert found == {"tool.py"}  # excluded subdir below the script dir still skipped


class TestScopeAncestors:
    """Build-artifact classification ignores names above the project root."""

    @pytest.mark.parametrize("ancestor", _SCOPE_ANCESTORS)
    def test_project_file_under_artifact_ancestor_is_project(self, tmp_path, ancestor):
        proj = _make_project(tmp_path / ancestor)

        assert classify_scope(proj / "pkg" / "core.py", JediAnalyzer(str(proj))) == "project"

    @pytest.mark.parametrize("ancestor", _SCOPE_ANCESTORS)
    def test_artifacts_inside_project_still_external(self, tmp_path, ancestor):
        """Regression guard: artifacts below the root are still recognised."""
        proj = _make_project(tmp_path / ancestor)
        analyzer = JediAnalyzer(str(proj))

        assert classify_scope(proj / "pkg" / "__pycache__" / "core.pyc", analyzer) == "external"
        assert classify_scope(proj / ".tox" / "py311" / "x.py", analyzer) == "external"
        assert classify_scope(proj / "build" / "generated.py", analyzer) == "external"

    def test_helper_checks_only_segments_below_root(self):
        root = Path("/ci/.tox/proj")
        assert _has_build_artifact_segment(root / "src" / "m.py", root) is False
        assert _has_build_artifact_segment(root / "src" / "__pycache__" / "m.pyc", root) is True

    def test_helper_without_root_still_matches_anywhere(self):
        """Callers without a project root keep the old anywhere-matching."""
        assert _has_build_artifact_segment(Path("/ci/.tox/proj/src/m.py")) is True

    def test_helper_path_outside_root_checks_whole_path(self):
        """A path not under the root has no 'below root' part; check all of it."""
        root = Path("/work/proj")
        assert _has_build_artifact_segment(Path("/elsewhere/.tox/lib/m.py"), root) is True

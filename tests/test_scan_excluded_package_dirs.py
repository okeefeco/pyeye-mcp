"""A real package named like an excluded directory is scanned (#1104).

``filtered_rglob`` pruned any directory NAMED in ``constants.EXCLUDED_DIRS``
(``env``, ``build``, ``dist``…), even a package. On Poetry 2.5.2 that dropped 22
modules (``poetry/utils/env/``, ``poetry/console/commands/env/``) from every
whole-tree scan, silently: a measured-empty answer for something never
measured. A directory that holds ``__init__.py`` or ``__init__.pyi`` is a
package, so it is scanned whatever its name. A real venv named ``env`` (it
holds ``pyvenv.cfg``, never ``__init__.py``) is still pruned.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pyeye.async_utils import filtered_rglob
from pyeye.project_layout import iter_module_files

PACKAGES = ("env", "build", "dist", "venv")


@pytest.fixture
def project(tmp_path: Path) -> Path:
    files = {
        "pkg/__init__.py": "",
        "pkg/base.py": "class Base:\n    pass\n",
        # Real packages with excluded names, the Poetry shape.
        **{f"pkg/{name}/__init__.py": "" for name in PACKAGES},
        **{
            f"pkg/{name}/mod.py": f"from pkg.base import Base\n\n\nclass In{name.title()}(Base):\n    pass\n"
            for name in PACKAGES
        },
        # A PEP 420 namespace package named like a build dir: no __init__ at all.
        "pkg/ns/build/mod.py": "X = 1\n",
        # A real venv named env: pyvenv.cfg, site-packages, no __init__.py.
        "env/pyvenv.cfg": "home = /usr/bin\nversion = 3.12.3\n",
        "env/lib/python3.12/site-packages/thirdparty/__init__.py": "",
        "env/lib/python3.12/site-packages/thirdparty/mod.py": "X = 1\n",
        # A setuptools build tree: build/ itself is not a package.
        "build/lib/pkg/__init__.py": "",
        "build/lib/pkg/base.py": "class Base:\n    pass\n",
        "dist/pkg-1.0.tar.gz": "",
    }
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text, encoding="utf-8")
    return tmp_path


def _rel(paths: list[Path], root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in paths}


class TestFilteredRglob:
    @pytest.mark.parametrize("name", PACKAGES)
    def test_a_package_with_an_excluded_name_is_scanned(self, project: Path, name: str) -> None:
        found = _rel(filtered_rglob("*.py", project), project)

        assert f"pkg/{name}/mod.py" in found
        assert f"pkg/{name}/__init__.py" in found

    def test_a_stub_only_package_counts_as_a_package(self, project: Path) -> None:
        """``__init__.pyi`` marks a package too (a stub-only package, #933)."""
        (project / "pkg/dist/__init__.py").rename(project / "pkg/dist/__init__.pyi")

        found = _rel(filtered_rglob(("*.py", "*.pyi"), project), project)

        assert "pkg/dist/mod.py" in found

    def test_a_venv_named_env_is_still_pruned(self, project: Path) -> None:
        found = _rel(filtered_rglob("*.py", project), project)

        assert not any(p.startswith("env/") for p in found), found

    def test_a_build_tree_without_an_init_is_still_pruned(self, project: Path) -> None:
        """setuptools' ``build/lib/pkg/`` would duplicate every project symbol."""
        found = _rel(filtered_rglob("*.py", project), project)

        assert not any(p.startswith("build/") for p in found), found

    def test_a_namespace_package_named_like_a_build_dir_stays_excluded(self, project: Path) -> None:
        """The documented limit: with no ``__init__``, a name alone can't tell a package
        from a build tree, and admitting it would re-admit ``build/lib`` duplicates."""
        found = _rel(filtered_rglob("*.py", project), project)

        assert "pkg/ns/build/mod.py" not in found


class TestTheWatcher:
    """An edit under such a package must invalidate the caches like any other (#1104).

    The watcher kept its own copy of the excluded names, so scanning the package
    without watching it would serve stale answers after an edit.
    """

    @pytest.fixture
    def watcher(self, project: Path):  # type: ignore[no-untyped-def]
        from pyeye.cache import CodebaseWatcher

        return CodebaseWatcher(project.as_posix())

    @pytest.mark.parametrize("name", PACKAGES)
    def test_an_edit_under_such_a_package_is_recorded(
        self, watcher, project: Path, name: str  # type: ignore[no-untyped-def]
    ) -> None:
        assert watcher._record((project / f"pkg/{name}/mod.py").as_posix(), False) is True

    def test_an_edit_inside_a_venv_is_still_ignored(
        self, watcher, project: Path  # type: ignore[no-untyped-def]
    ) -> None:
        path = project / "env/lib/python3.12/site-packages/thirdparty/mod.py"

        assert watcher._record(path.as_posix(), False) is False

    def test_an_edit_inside_a_build_tree_is_still_ignored(
        self, watcher, project: Path  # type: ignore[no-untyped-def]
    ) -> None:
        assert watcher._record((project / "build/lib/pkg/base.py").as_posix(), False) is False


class TestEveryWholeTreeScan:
    def test_iter_module_files(self, project: Path) -> None:
        found = _rel(iter_module_files(project), project)

        assert {f"pkg/{name}/mod.py" for name in PACKAGES} <= found
        assert not any(p.startswith(("env/", "build/")) for p in found)

    @pytest.mark.asyncio
    async def test_imported_by_sees_importers_under_such_packages(self, project: Path) -> None:
        from pyeye.analyzers.jedi_analyzer import JediAnalyzer
        from pyeye.mcp.operations.expand import expand

        result = await expand("pkg.base", "imported_by", JediAnalyzer(project.as_posix()))

        handles = {s["handle"] for s in result["stubs"]}
        assert {f"pkg.{name}.mod" for name in PACKAGES} <= handles, handles

    @pytest.mark.asyncio
    async def test_subclasses_sees_classes_under_such_packages(self, project: Path) -> None:
        from pyeye.analyzers import project_graph
        from pyeye.analyzers.jedi_analyzer import JediAnalyzer
        from pyeye.mcp.operations.expand import expand

        project_graph.invalidate()
        result = await expand(
            "pkg.base.Base", "subclasses", JediAnalyzer(project.as_posix()), max_stubs=None
        )

        handles = {s["handle"] for s in result["stubs"]}
        assert {f"pkg.{name}.mod.In{name.title()}" for name in PACKAGES} <= handles, handles


class TestVenvsByMarker:
    """Q2 (ruled): any directory holding ``pyvenv.cfg`` is a venv, whatever its name."""

    @pytest.mark.parametrize("venv", [".direnv/python-3.12", "myvenv", "py312"])
    def test_a_venv_with_any_name_is_pruned(self, project: Path, venv: str) -> None:
        (project / venv / "lib/site-packages/other").mkdir(parents=True)
        (project / venv / "pyvenv.cfg").write_text("version = 3.12\n", encoding="utf-8")
        (project / venv / "lib/site-packages/other/__init__.py").write_text("", encoding="utf-8")

        found = _rel(filtered_rglob("*.py", project), project)

        assert not any(p.startswith(f"{venv}/") for p in found), found

    def test_a_venv_beats_the_package_rule(self, project: Path) -> None:
        """A directory holding both is a venv: a venv's root is never a package."""
        (project / "pkg/env/pyvenv.cfg").write_text("version = 3.12\n", encoding="utf-8")

        found = _rel(filtered_rglob("*.py", project), project)

        assert not any(p.startswith("pkg/env/") for p in found), found

    def test_the_watcher_ignores_a_venv_with_any_name(self, project: Path) -> None:
        from pyeye.cache import CodebaseWatcher

        (project / "myvenv/lib").mkdir(parents=True)
        (project / "myvenv/pyvenv.cfg").write_text("version = 3.12\n", encoding="utf-8")
        watcher = CodebaseWatcher(project.as_posix())

        assert watcher._record((project / "myvenv/lib/x.py").as_posix(), False) is False


class TestScopeClassification:
    """Q4 (ruled): a top-level ``build``/``dist`` PACKAGE is project, not build output."""

    @pytest.mark.parametrize("name", ["build", "dist"])
    def test_a_top_level_package_is_project(self, tmp_path: Path, name: str) -> None:
        from pyeye.scope import _has_build_artifact_segment

        (tmp_path / name).mkdir()
        (tmp_path / name / "__init__.py").write_text("", encoding="utf-8")

        assert _has_build_artifact_segment(tmp_path / name / "mod.py", tmp_path) is False

    @pytest.mark.parametrize("name", ["build", "dist"])
    def test_a_top_level_build_dir_is_still_external(self, tmp_path: Path, name: str) -> None:
        from pyeye.scope import _has_build_artifact_segment

        (tmp_path / name / "lib").mkdir(parents=True)

        assert _has_build_artifact_segment(tmp_path / name / "lib" / "mod.py", tmp_path) is True


class TestTheCeilingStatesTheLimit:
    """Q1's limit is disclosed, not silent (ruled): in the ceilings of the scan edges."""

    @pytest.mark.parametrize("edge", ["subclasses", "imported_by"])
    def test_the_scan_edges_ceiling_names_the_limit(self, edge: str) -> None:
        from pyeye.mcp.operations.edges import CEILING_MEANINGS, EDGE_CEILINGS

        meaning = CEILING_MEANINGS[EDGE_CEILINGS[edge]]

        assert "pyvenv.cfg" in meaning
        assert "namespace package" in meaning and "#1104" in meaning

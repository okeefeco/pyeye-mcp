"""Excluded directory names match case-insensitively, through one shared predicate (#1116).

The maintainer's ruling on #1104's follow-up: scope classification already
case-folded ``Build/`` and ``DIST/``, but the scan's excluded-directory match
was exact. So on macOS and Windows a ``Build/`` or ``Env/`` tree was scanned.
Now:

- the scan's excluded DIRECTORY-name match is case-insensitive, and the scan
  and scope share one name predicate, ``project_layout.dir_name_matches``;
- #1104's package rule still wins, and ``pyvenv.cfg`` still prunes;
- only directory exclusion changes: module, class and handle names keep their
  case.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pyeye import project_layout, scope
from pyeye.async_utils import filtered_rglob
from pyeye.project_layout import dir_name_matches, excluded_name, iter_module_files

CASED = ("Build", "DIST", "Env", ".VENV", "__PYCACHE__", "Foo.EGG-INFO")


def _rel(paths: list[Path], root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in paths}


@pytest.fixture
def project(tmp_path: Path) -> Path:
    files = {"pkg/__init__.py": "", "pkg/keep.py": "X = 1\n"}
    for name in CASED:
        files[f"{name}/stray.py"] = "X = 1\n"  # not a package: pruned
        files[f"pkg/{name}/stray.py"] = "X = 1\n"  # nested, still not a package
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text, encoding="utf-8")
    return tmp_path


class TestThePredicate:
    @pytest.mark.parametrize("name", [*CASED, "build", "dist", "env", ".venv", "node_modules"])
    def test_excluded_names_match_whatever_their_case(self, name: str) -> None:
        assert excluded_name(name)

    @pytest.mark.parametrize("name", ["builder", "distro", "environment", "my_env", "Builds"])
    def test_other_names_do_not(self, name: str) -> None:
        assert not excluded_name(name)

    def test_a_suffix_pattern_folds_too(self) -> None:
        assert dir_name_matches("Pkg.Egg-Info", ("*.egg-info",))
        assert not dir_name_matches("egg-info-tools", ("*.egg-info",))

    def test_scope_calls_the_same_predicate(self) -> None:
        """One name predicate for scan and scope (#1116)."""
        assert scope.dir_name_matches is project_layout.dir_name_matches


class TestTheScan:
    def test_cased_excluded_dirs_are_pruned(self, project: Path) -> None:
        found = _rel(filtered_rglob("*.py", project), project)

        assert found == {"pkg/__init__.py", "pkg/keep.py"}, found

    @pytest.mark.parametrize("name", ["Build", "DIST", "Env", ".VENV"])
    def test_the_package_rule_still_wins(self, project: Path, name: str) -> None:
        (project / f"pkg/{name}/__init__.py").write_text("", encoding="utf-8")

        found = _rel(filtered_rglob("*.py", project), project)

        assert f"pkg/{name}/stray.py" in found

    def test_pyvenv_cfg_still_prunes_a_cased_package_name(self, project: Path) -> None:
        (project / "pkg/Env/__init__.py").write_text("", encoding="utf-8")
        (project / "pkg/Env/pyvenv.cfg").write_text("version = 3.12\n", encoding="utf-8")

        found = _rel(filtered_rglob("*.py", project), project)

        assert not any(p.startswith("pkg/Env/") for p in found), found

    def test_module_names_keep_their_case(self, project: Path) -> None:
        """Only directory exclusion folds case; a module file keeps its spelling."""
        (project / "pkg/Env/__init__.py").write_text("", encoding="utf-8")
        (project / "pkg/Mixed_Case.py").write_text("X = 1\n", encoding="utf-8")

        found = _rel(iter_module_files(project), project)

        assert {"pkg/Env/stray.py", "pkg/Mixed_Case.py"} <= found


class TestTheWatcher:
    @pytest.mark.parametrize("name", ["Build", "DIST", "Env", ".VENV"])
    def test_an_edit_under_a_cased_excluded_dir_is_ignored(self, project: Path, name: str) -> None:
        from pyeye.cache import CodebaseWatcher

        watcher = CodebaseWatcher(project.as_posix())

        assert watcher._record((project / f"{name}/stray.py").as_posix(), False) is False

    def test_an_edit_under_a_cased_package_is_recorded(self, project: Path) -> None:
        from pyeye.cache import CodebaseWatcher

        (project / "pkg/Build/__init__.py").write_text("", encoding="utf-8")
        watcher = CodebaseWatcher(project.as_posix())

        assert watcher._record((project / "pkg/Build/stray.py").as_posix(), False) is True

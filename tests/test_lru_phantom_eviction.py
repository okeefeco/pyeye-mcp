"""LRU eviction never drops the project being registered (#784).

``invalidate_analyzer`` used to remove a project from ``access_order`` even when
it was still registered (in ``dependencies``, which ``configure_packages`` and a
config's ``packages`` create). ``_evict_if_needed`` counts registered projects
and analyzers together, but can only evict what ``access_order`` lists, so such
a project became an unevictable phantom. Once phantoms filled ``max_projects``,
eviction popped entries until the count fit, which in the end meant the project
just registered. Inside ``get_analyzer`` that was the very project being built:
its packages were dropped and its analyzer got no package paths, so models and
names in a configured package silently vanished.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from pyeye.path_utils import normalize_path
from pyeye.project_manager import ProjectManager

_MAX = 3


def _configured_project(root: Path, name: str) -> tuple[Path, Path]:
    """A project whose ``.pyeye.json`` lists one extra package."""
    project = root / name
    extra = root / f"{name}_extra"
    (project / "app").mkdir(parents=True)
    (project / "app" / "mod.py").write_text("X = 1\n", encoding="utf-8")
    (extra / "pkg").mkdir(parents=True)
    (extra / "pkg" / "lib.py").write_text("Y = 2\n", encoding="utf-8")
    (project / ".pyeye.json").write_text(
        json.dumps({"packages": [extra.as_posix()]}), encoding="utf-8"
    )
    return project, extra


@pytest.fixture
def manager() -> Iterator[ProjectManager]:
    m = ProjectManager(max_projects=_MAX)
    yield m
    m.cleanup_all()


def _counted(m: ProjectManager) -> set[Path]:
    return set(m.dependencies) | set(m.analyzers)


def test_invalidating_a_registered_project_keeps_it_evictable(
    manager: ProjectManager, tmp_path: Path
) -> None:
    project, _extra = _configured_project(tmp_path, "p0")
    manager.get_analyzer(project.as_posix())
    key = normalize_path(project)
    assert key in manager.dependencies

    manager.invalidate_analyzer(project.as_posix())

    assert key in manager.dependencies  # still registered, so still counted
    assert key in manager.access_order  # and still evictable


def test_invalidating_an_analyzer_only_project_drops_its_entry(
    manager: ProjectManager, tmp_path: Path
) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    manager.get_analyzer(plain.as_posix())

    manager.invalidate_analyzer(plain.as_posix())

    assert normalize_path(plain) not in manager.access_order  # no longer counted


def test_the_project_being_built_keeps_its_package_paths_after_phantoms(
    manager: ProjectManager, tmp_path: Path
) -> None:
    """The #784 scenario: fill the budget with invalidated configured projects."""
    for i in range(_MAX):
        project, _extra = _configured_project(tmp_path, f"old{i}")
        manager.get_analyzer(project.as_posix())
        manager.invalidate_analyzer(project.as_posix())

    new, extra = _configured_project(tmp_path, "new")
    analyzer = manager.get_analyzer(new.as_posix())

    key = normalize_path(new)
    assert key in manager.dependencies, "the project being built was evicted"
    assert normalize_path(extra) in {normalize_path(p) for p in analyzer.additional_paths}
    assert key in manager.analyzers
    # Every counted project is still evictable, and the budget holds.
    assert _counted(manager) <= set(manager.access_order)
    assert len(_counted(manager)) <= _MAX


def test_eviction_skips_a_stale_entry(manager: ProjectManager, tmp_path: Path) -> None:
    """Defensive: an access_order entry nobody counts lowers nothing, so it is skipped."""
    stale = normalize_path(tmp_path / "gone")
    manager.access_order.insert(0, stale)
    keep: list[Path] = []
    for i in range(_MAX + 1):
        project, _extra = _configured_project(tmp_path, f"p{i}")
        manager.get_analyzer(project.as_posix())
        keep.append(normalize_path(project))

    assert stale not in manager.access_order
    assert keep[-1] in manager.dependencies  # the newest survives
    assert len(_counted(manager)) <= _MAX

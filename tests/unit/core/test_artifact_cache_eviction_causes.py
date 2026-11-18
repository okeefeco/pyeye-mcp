"""The artifact cache counts evictions by cause (#401).

``cap_evictions`` are entries dropped to stay under the caps: cap pressure, the
signal to raise ``PYEYE_ARTIFACT_CACHE_MAX_ENTRIES`` or
``PYEYE_SCRIPT_CACHE_MAX_ENTRIES``. ``stale_evictions`` are entries dropped
because their file changed or was invalidated: healthy churn on an edited repo.
``evictions`` stays the total, so the existing key and series keep their meaning.
"""

from __future__ import annotations

import os
from pathlib import Path

import jedi
import pytest

from pyeye._jedi_project import make_project
from pyeye.file_artifact_cache import FileArtifactCache


@pytest.fixture
def files(tmp_path: Path) -> list[Path]:
    paths = []
    for i in range(5):
        path = tmp_path / f"m{i}.py"
        path.write_text(f"X{i} = {i}\n", encoding="utf-8")
        paths.append(path)
    return paths


@pytest.fixture
def project(tmp_path: Path) -> jedi.Project:
    return make_project(tmp_path)


def _causes(cache: FileArtifactCache) -> tuple[int, int]:
    stats = cache.stats()
    assert stats["evictions"] == stats["cap_evictions"] + stats["stale_evictions"]
    return stats["cap_evictions"], stats["stale_evictions"]


def _touch(path: Path) -> None:
    """Change *path* so its cache key (mtime and size) no longer matches."""
    path.write_text(path.read_text(encoding="utf-8") + "Y = 1\n", encoding="utf-8")
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))


class TestCapPressure:
    def test_the_combined_cap_counts_as_cap(self, files: list[Path]) -> None:
        cache = FileArtifactCache(ast_max_entries=2)
        for path in files:
            cache.get_ast(path)

        assert _causes(cache) == (3, 0)

    def test_the_script_cap_counts_as_cap(self, files: list[Path], project: jedi.Project) -> None:
        cache = FileArtifactCache(ast_max_entries=100, script_max_entries=2)
        for path in files:
            cache.get_script(path, project)

        assert _causes(cache) == (3, 0)


class TestStaleness:
    def test_a_changed_file_counts_as_stale(self, files: list[Path], project: jedi.Project) -> None:
        cache = FileArtifactCache(ast_max_entries=100)
        cache.get_ast(files[0])
        cache.get_script(files[0], project)
        _touch(files[0])
        cache.get_ast(files[0])
        cache.get_script(files[0], project)

        assert _causes(cache) == (0, 2)

    def test_invalidating_a_path_counts_as_stale(
        self, files: list[Path], project: jedi.Project
    ) -> None:
        cache = FileArtifactCache(ast_max_entries=100)
        cache.get_ast(files[0])
        cache.get_script(files[0], project)
        cache.invalidate(files[0])

        assert _causes(cache) == (0, 2)

    def test_a_clear_counts_as_stale_by_its_size(self, files: list[Path]) -> None:
        cache = FileArtifactCache(ast_max_entries=100)
        for path in files[:3]:
            cache.get_ast(path)
        cache.invalidate_all()

        assert _causes(cache) == (0, 3)


def test_the_total_is_the_sum_across_both_causes(files: list[Path]) -> None:
    cache = FileArtifactCache(ast_max_entries=2)
    for path in files:
        cache.get_ast(path)
    cache.invalidate(files[-1])

    stats = cache.stats()
    assert (stats["cap_evictions"], stats["stale_evictions"], stats["evictions"]) == (3, 1, 4)
    assert set(stats) == {"hits", "misses", "evictions", "cap_evictions", "stale_evictions"}

"""Scripts have their own LRU cap inside the combined artifact cap (#713).

Each cached ``jedi.Script`` owns a Jedi inference state that keeps every module
it inferred alive, parse trees included, whatever parso's own cache holds. So
bounding parso alone barely moved pyeye's memory: in #713's measurement, live
parse trees stayed at about 1,170 with parso capped at 600, until Scripts were
capped too. ``PYEYE_SCRIPT_CACHE_MAX_ENTRIES`` is that cap.
"""

from __future__ import annotations

from pathlib import Path

import jedi
import pytest

from pyeye import (
    file_artifact_cache,
    settings as settings_mod,
)
from pyeye._jedi_project import make_project
from pyeye.file_artifact_cache import FileArtifactCache
from pyeye.settings import PerformanceSettings


@pytest.fixture
def files(tmp_path: Path) -> list[Path]:
    paths = []
    for i in range(5):
        path = tmp_path / f"m{i}.py"
        path.write_text(f"VALUE_{i} = {i}\n")
        paths.append(path)
    return paths


@pytest.fixture
def project(tmp_path: Path) -> jedi.Project:
    return make_project(tmp_path)


class TestScriptCap:
    def test_scripts_never_exceed_their_cap(self, files: list[Path], project: jedi.Project) -> None:
        cache = FileArtifactCache(ast_max_entries=100, script_max_entries=2)
        for path in files:
            cache.get_script(path, project)
            assert len(cache._script_store) <= 2

    def test_the_least_recently_used_script_goes_first(
        self, files: list[Path], project: jedi.Project
    ) -> None:
        cache = FileArtifactCache(ast_max_entries=100, script_max_entries=2)
        first = cache.get_script(files[0], project)
        cache.get_script(files[1], project)
        assert cache.get_script(files[0], project) is first  # a hit refreshes it

        cache.get_script(files[2], project)  # evicts files[1], not files[0]

        kept = {key[0] for key in cache._script_store}
        assert kept == {files[0].resolve().as_posix(), files[2].resolve().as_posix()}
        assert cache.get_script(files[0], project) is first

    def test_an_evicted_script_is_rebuilt_on_demand(
        self, files: list[Path], project: jedi.Project
    ) -> None:
        cache = FileArtifactCache(ast_max_entries=100, script_max_entries=1)
        before = cache.get_script(files[0], project)
        cache.get_script(files[1], project)

        again = cache.get_script(files[0], project)

        assert again is not before
        assert [n.name for n in again.get_names()] == ["VALUE_0"]
        assert cache.stats()["evictions"] >= 2

    def test_asts_are_not_limited_by_the_script_cap(
        self, files: list[Path], project: jedi.Project
    ) -> None:
        cache = FileArtifactCache(ast_max_entries=100, script_max_entries=1)
        for path in files:
            cache.get_ast(path)
            cache.get_script(path, project)

        assert len(cache._ast_store) == len(files)
        assert len(cache._script_store) == 1

    def test_the_combined_cap_still_applies(self, files: list[Path], project: jedi.Project) -> None:
        cache = FileArtifactCache(ast_max_entries=3, script_max_entries=10)
        for path in files:
            cache.get_ast(path)
            cache.get_script(path, project)

        assert len(cache._ast_store) + len(cache._script_store) <= 3


class TestSetting:
    def test_default_and_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("PYEYE_SCRIPT_CACHE_MAX_ENTRIES", raising=False)
        assert PerformanceSettings().script_cache_max_entries == 200
        monkeypatch.setenv("PYEYE_SCRIPT_CACHE_MAX_ENTRIES", "25")
        assert PerformanceSettings().script_cache_max_entries == 25

    def test_cache_takes_its_default_from_settings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings_mod.settings, "script_cache_max_entries", 42)
        assert file_artifact_cache.FileArtifactCache()._script_max_entries == 42

    def test_an_explicit_cap_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings_mod.settings, "script_cache_max_entries", 42)
        assert FileArtifactCache(script_max_entries=7)._script_max_entries == 7

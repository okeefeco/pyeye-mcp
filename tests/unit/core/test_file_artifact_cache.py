"""Failing tests for the file artifact cache (Task 1.1 TDD).

The module under test, ``pyeye.file_artifact_cache``, does not exist yet.
Every test in this file is expected to fail until Task 1.2 provides the
implementation.  Each test imports the module at call time so failures appear
as individual ERRORS rather than a whole-file skip.

Contracts verified:
  (a) Repeated reads of the same file return the identical cached object (cache hit).
  (b) Modifying a file's mtime forces a fresh read (cache miss).
  (c) LRU eviction kicks in once the AST/Script entry count exceeds the cap.
  (d) Byte cap is enforced for source text; old entries are evicted when exceeded.
  (e) Concurrent access from multiple asyncio tasks is safe and returns consistent results.
  (f) Explicit invalidation of a path drops the cache entry, causing a fresh load on
      the next access.
"""

from __future__ import annotations

import ast
import asyncio
import importlib
import os
from pathlib import Path

import jedi
import pytest

# --------------------------------------------------------------------------- #
# Module-level import probe (informative, not the primary failure mechanism)   #
# --------------------------------------------------------------------------- #


def _import_cache_module():
    """Import pyeye.file_artifact_cache, raising ImportError if absent."""
    return importlib.import_module("pyeye.file_artifact_cache")


def _get_cache_class():
    """Return the FileArtifactCache class from the not-yet-implemented module."""
    mod = _import_cache_module()
    return mod.FileArtifactCache


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


def _write_py(path: Path, content: str) -> None:
    """Write *content* to *path*, ensuring it ends with a newline."""
    path.write_text(content if content.endswith("\n") else content + "\n", encoding="utf-8")


def _bump_mtime(path: Path) -> None:
    """Advance the file's mtime by 1 second so the cache sees a change."""
    stat = path.stat()
    new_mtime = stat.st_mtime + 1.0
    os.utime(path, (new_mtime, new_mtime))


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #


@pytest.fixture()
def py_file(tmp_path: Path) -> Path:
    """A simple, valid Python file written to a temp location."""
    f = tmp_path / "sample.py"
    _write_py(f, "x = 1\ny = x + 2\n")
    return f


@pytest.fixture()
def jedi_project(tmp_path: Path) -> jedi.Project:
    """A real jedi.Project rooted at the temp directory."""
    return jedi.Project(path=tmp_path)


@pytest.fixture()
def small_cache():
    """A FileArtifactCache with tiny caps so eviction is easy to trigger.

    ast_max_entries=2 means the third distinct file should evict the LRU.
    file_max_bytes=200 is smaller than three typical ~100-byte Python sources.
    """
    cls = _get_cache_class()
    return cls(ast_max_entries=2, file_max_bytes=200)


@pytest.fixture()
def default_cache():
    """A FileArtifactCache with default (large) caps."""
    cls = _get_cache_class()
    return cls()


# --------------------------------------------------------------------------- #
# (a) Cache hit — identical object returned on repeated access                #
# --------------------------------------------------------------------------- #


class TestCacheHit:
    """Repeated access to the same unchanged file returns the cached object."""

    def test_get_source_returns_same_object_on_second_call(
        self, py_file: Path, default_cache
    ) -> None:
        """get_source() called twice on the same file must return the *same* str instance.

        Identity (``is``) rather than equality (``==``) proves the result came from
        the cache and was not re-read from disk.
        """
        first = default_cache.get_source(py_file)
        second = default_cache.get_source(py_file)
        assert first is second, (
            "Expected get_source() to return the identical cached object on the second "
            "call, but got two different objects (likely a cache miss or copy)."
        )

    def test_get_ast_returns_same_object_on_second_call(self, py_file: Path, default_cache) -> None:
        """get_ast() called twice on the same file must return the *same* ast.Module instance."""
        first = default_cache.get_ast(py_file)
        second = default_cache.get_ast(py_file)
        assert isinstance(first, ast.Module)
        assert first is second, (
            "Expected get_ast() to return the identical cached ast.Module on the second "
            "call, but got two different objects."
        )

    def test_get_script_returns_same_object_on_second_call(
        self, py_file: Path, jedi_project: jedi.Project, default_cache
    ) -> None:
        """get_script() called twice must return the *same* jedi.Script instance."""
        first = default_cache.get_script(py_file, jedi_project)
        second = default_cache.get_script(py_file, jedi_project)
        assert isinstance(first, jedi.Script)
        assert first is second, (
            "Expected get_script() to return the identical cached jedi.Script on the "
            "second call, but got two different objects."
        )

    def test_stats_records_hit_after_second_call(self, py_file: Path, default_cache) -> None:
        """stats() must report at least one hit after a cache-warm second call."""
        default_cache.get_source(py_file)  # cold — miss
        default_cache.get_source(py_file)  # warm — hit
        stats = default_cache.stats()
        assert (
            stats["hits"] >= 1
        ), f"Expected at least one cache hit recorded in stats, got: {stats}"


# --------------------------------------------------------------------------- #
# (a2) Multi-project isolation — Script keying must include project_id        #
# --------------------------------------------------------------------------- #


class TestMultiProjectIsolation:
    """get_script() must key on (path, mtime_ns, project_id), not just (path, mtime_ns).

    Without project isolation a cache hit for project_a could be returned for
    project_b, producing wrong completions when the same file is analysed
    under multiple jedi.Project roots (e.g. multi-root workspaces, Task 1.5).
    """

    def test_different_projects_get_different_script_objects(
        self, tmp_path: Path, default_cache
    ) -> None:
        """Two distinct jedi.Project instances must not share cached Script objects.

        Even when the source file is identical, the Script is project-specific
        because Jedi resolves imports relative to the project root.  The cache
        key must therefore include the project identifier so each project gets
        its own entry.
        """
        source_file = tmp_path / "shared.py"
        _write_py(source_file, "import os\nresult = os.getcwd()\n")

        # Two projects rooted at different paths
        project_a = jedi.Project(path=tmp_path)
        project_b_root = tmp_path / "subproject"
        project_b_root.mkdir()
        project_b = jedi.Project(path=project_b_root)

        script_a = default_cache.get_script(source_file, project_a)
        script_b = default_cache.get_script(source_file, project_b)

        assert script_a is not script_b, (
            "Expected get_script() to return distinct Script objects for different "
            "jedi.Project instances, but got the same object.  The cache key must "
            "include the project identifier (e.g. project path or id), not just the "
            "file path and mtime."
        )

    def test_same_project_still_hits_cache(self, tmp_path: Path, default_cache) -> None:
        """Calling get_script() twice with the same project must return the cached object."""
        source_file = tmp_path / "cached.py"
        _write_py(source_file, "VALUE = 42\n")

        project = jedi.Project(path=tmp_path)

        first = default_cache.get_script(source_file, project)
        second = default_cache.get_script(source_file, project)

        assert first is second, (
            "Expected get_script() to return the identical cached Script on the second "
            "call with the same project, but got two different objects (cache miss)."
        )


# --------------------------------------------------------------------------- #
# (b) mtime change — cache must not serve stale content                       #
# --------------------------------------------------------------------------- #


class TestMtimeMiss:
    """When a file's mtime advances the next access must produce a fresh artifact."""

    def test_get_source_returns_new_content_after_mtime_change(
        self, py_file: Path, default_cache
    ) -> None:
        """After writing new content and bumping mtime, get_source() must return the new text."""
        original = default_cache.get_source(py_file)

        _write_py(py_file, "z = 999\n")
        _bump_mtime(py_file)

        fresh = default_cache.get_source(py_file)
        assert fresh != original, (
            "Expected get_source() to detect the mtime change and return the new file "
            "content, but it returned the old cached text."
        )
        assert "z = 999" in fresh

    def test_stats_records_miss_after_mtime_change(self, py_file: Path, default_cache) -> None:
        """stats() must show a miss (not a hit) after the mtime advances."""
        default_cache.get_source(py_file)  # first call — populates cache
        _write_py(py_file, "a = 'changed'\n")
        _bump_mtime(py_file)

        misses_before = default_cache.stats()["misses"]
        default_cache.get_source(py_file)  # should be a cache miss
        misses_after = default_cache.stats()["misses"]

        assert misses_after > misses_before, (
            "Expected the stats miss counter to increase after an mtime change forced a "
            "cache miss, but it did not change."
        )

    def test_get_ast_reflects_new_source_after_mtime_change(
        self, py_file: Path, default_cache
    ) -> None:
        """The AST returned after an mtime change must reflect the updated source."""
        default_cache.get_ast(py_file)

        new_source = "def hello(): return 42\n"
        _write_py(py_file, new_source)
        _bump_mtime(py_file)

        fresh_ast = default_cache.get_ast(py_file)
        func_names = [
            node.name for node in ast.walk(fresh_ast) if isinstance(node, ast.FunctionDef)
        ]
        assert "hello" in func_names, (
            "Expected the post-mtime-change AST to contain the new FunctionDef 'hello', "
            "but it was absent — the cache likely served the old AST."
        )


# --------------------------------------------------------------------------- #
# (c) LRU eviction — AST/Script count cap                                    #
# --------------------------------------------------------------------------- #


class TestLruEviction:
    """When more files are loaded than ast_max_entries, the least-recently used is evicted."""

    def test_first_entry_evicted_after_cap_exceeded(self, tmp_path: Path, small_cache) -> None:
        """With ast_max_entries=2, loading a third file must evict the LRU.

        Access order: load file0, load file1, touch file0 (makes file1 LRU),
        then load file2 → file1 is evicted.  Re-accessing file1 must be a miss.
        """
        files = []
        for i in range(3):
            f = tmp_path / f"mod{i}.py"
            _write_py(f, f"VALUE_{i} = {i}\n")
            files.append(f)

        # Load files 0 and 1 — fills the cache (cap=2)
        small_cache.get_ast(files[0])
        small_cache.get_ast(files[1])

        hits_before = small_cache.stats()["hits"]
        # Touch file 0 to make it most-recently-used; file1 becomes LRU
        small_cache.get_ast(files[0])
        assert small_cache.stats()["hits"] > hits_before, "file 0 should still be cached"

        # Load file 2 — must evict LRU (file1)
        small_cache.get_ast(files[2])

        # Re-accessing file1 must be a miss
        misses_before = small_cache.stats()["misses"]
        small_cache.get_ast(files[1])
        misses_after = small_cache.stats()["misses"]
        assert misses_after > misses_before, (
            "Expected a cache miss when accessing the evicted (LRU) entry, but the "
            "stats miss counter did not increase.  Either LRU eviction is not "
            "implemented or the eviction order is wrong."
        )

    def test_eviction_count_increases_with_overflow(self, tmp_path: Path, small_cache) -> None:
        """stats()['evictions'] must be > 0 once more files are loaded than ast_max_entries."""
        for i in range(4):  # cap is 2, so 4 loads must cause at least 2 evictions
            f = tmp_path / f"ev{i}.py"
            _write_py(f, f"N = {i}\n")
            small_cache.get_ast(f)

        evictions = small_cache.stats().get("evictions", 0)
        assert evictions >= 2, (
            f"Expected at least 2 evictions after loading 4 files into a cap-2 cache, "
            f"but stats reported {evictions} evictions."
        )


# --------------------------------------------------------------------------- #
# (d) Byte cap — source text cache size limit                                 #
# --------------------------------------------------------------------------- #


class TestByteCap:
    """Source text cache must not grow beyond file_max_bytes."""

    def test_source_cache_evicts_when_byte_cap_exceeded(self, tmp_path: Path, small_cache) -> None:
        """Loading sources that together exceed file_max_bytes=200 must trigger eviction.

        Three files of ~100 bytes each.  After all three are loaded the first
        should have been evicted.  Re-accessing it must produce a miss, not a hit.
        """
        files = []
        for i in range(3):
            f = tmp_path / f"big{i}.py"
            # ~100-byte content; three together exceed the 200-byte cap
            content = f"# padding {'x' * 80}\nX{i} = {i}\n"
            _write_py(f, content)
            files.append(f)

        small_cache.get_source(files[0])
        small_cache.get_source(files[1])
        small_cache.get_source(files[2])  # should trigger eviction of files[0]

        misses_before = small_cache.stats()["misses"]
        small_cache.get_source(files[0])  # expect a miss — evicted due to byte cap
        misses_after = small_cache.stats()["misses"]

        assert misses_after > misses_before, (
            "Expected a cache miss when re-accessing the first source file after the "
            "byte cap was exceeded and eviction should have occurred."
        )

    def test_total_cached_bytes_stays_within_cap(self, tmp_path: Path, small_cache) -> None:
        """stats()['cached_bytes'] must never exceed file_max_bytes after many loads."""
        for i in range(5):
            f = tmp_path / f"cap{i}.py"
            content = f"# {'y' * 80}\nV{i} = {i}\n"
            _write_py(f, content)
            small_cache.get_source(f)

        cached_bytes = small_cache.stats().get("cached_bytes", 0)
        assert cached_bytes <= 200, (
            f"Expected cached_bytes to stay within the 200-byte cap, but it was "
            f"{cached_bytes}.  Byte-cap eviction may not be implemented."
        )


# --------------------------------------------------------------------------- #
# (e) Concurrent async access — no races, consistent results                  #
# --------------------------------------------------------------------------- #


class TestConcurrentAccess:
    """Concurrent asyncio tasks must all get the same result without exceptions."""

    def test_concurrent_get_source_returns_consistent_results(
        self, py_file: Path, default_cache
    ) -> None:
        """N concurrent executor tasks calling get_source() must all receive the same content."""

        async def _run() -> list[str]:
            loop = asyncio.get_running_loop()
            futures = [
                loop.run_in_executor(None, default_cache.get_source, py_file) for _ in range(20)
            ]
            return await asyncio.gather(*futures)

        results = asyncio.run(_run())
        assert len(results) == 20
        unique = set(results)
        assert len(unique) == 1, (
            f"Expected all 20 concurrent get_source() calls to return identical "
            f"content, but got {len(unique)} distinct values."
        )

    def test_concurrent_get_source_on_different_files_does_not_raise(
        self, tmp_path: Path, default_cache
    ) -> None:
        """Concurrent tasks on different files must complete without exceptions."""
        files = []
        for i in range(10):
            f = tmp_path / f"concurrent{i}.py"
            _write_py(f, f"C{i} = {i}\n")
            files.append(f)

        async def _fetch_all() -> list[str]:
            loop = asyncio.get_running_loop()
            futures = [loop.run_in_executor(None, default_cache.get_source, f) for f in files]
            return await asyncio.gather(*futures)

        results = asyncio.run(_fetch_all())
        assert len(results) == 10
        assert all(isinstance(r, str) for r in results), (
            "Expected all concurrent get_source() calls to return str values without "
            "raising exceptions."
        )

    def test_concurrent_mixed_operations_leave_stats_consistent(
        self, py_file: Path, jedi_project: jedi.Project, default_cache
    ) -> None:
        """Mixing get_source, get_ast, and get_script concurrently must not corrupt stats."""

        async def _mixed() -> tuple:
            loop = asyncio.get_running_loop()
            source_fut = loop.run_in_executor(None, default_cache.get_source, py_file)
            ast_fut = loop.run_in_executor(None, default_cache.get_ast, py_file)
            script_fut = loop.run_in_executor(None, default_cache.get_script, py_file, jedi_project)
            return await asyncio.gather(source_fut, ast_fut, script_fut)

        source, tree, script = asyncio.run(_mixed())
        assert isinstance(source, str)
        assert isinstance(tree, ast.Module)
        assert isinstance(script, jedi.Script)

        stats = default_cache.stats()
        assert isinstance(stats["hits"], int)
        assert isinstance(stats["misses"], int)
        total = stats["hits"] + stats["misses"]
        assert total >= 3, (
            f"Expected at least 3 cache accesses tracked in stats (source + ast + script), "
            f"but stats shows only {total} total (hits={stats['hits']}, misses={stats['misses']})."
        )


# --------------------------------------------------------------------------- #
# (f) Explicit invalidation — entry must be dropped                           #
# --------------------------------------------------------------------------- #


class TestExplicitInvalidation:
    """invalidate(path) must evict the entry so the next access is a fresh load."""

    def test_invalidate_causes_miss_on_next_access(self, py_file: Path, default_cache) -> None:
        """After invalidate(path), get_source() must miss, not hit."""
        default_cache.get_source(py_file)  # populates cache
        default_cache.invalidate(py_file)  # evict

        misses_before = default_cache.stats()["misses"]
        default_cache.get_source(py_file)  # must be a miss
        misses_after = default_cache.stats()["misses"]

        assert misses_after > misses_before, (
            "Expected a cache miss after explicit invalidate(), but the miss counter "
            "did not increase — entry may still be in cache."
        )

    def test_invalidate_only_drops_targeted_file(self, tmp_path: Path, default_cache) -> None:
        """invalidate(path) must not evict entries for other files."""
        file_a = tmp_path / "a.py"
        file_b = tmp_path / "b.py"
        _write_py(file_a, "A = 1\n")
        _write_py(file_b, "B = 2\n")

        default_cache.get_source(file_a)
        default_cache.get_source(file_b)

        default_cache.invalidate(file_a)

        hits_before = default_cache.stats()["hits"]
        default_cache.get_source(file_b)  # file_b must still be cached → hit
        hits_after = default_cache.stats()["hits"]

        assert hits_after > hits_before, (
            "Expected file_b to remain in the cache after only file_a was invalidated, "
            "but accessing file_b produced a miss instead of a hit."
        )

    def test_invalidate_all_clears_entire_cache(self, tmp_path: Path, default_cache) -> None:
        """invalidate_all() must evict every entry so all subsequent accesses are misses."""
        files = []
        for i in range(5):
            f = tmp_path / f"ia{i}.py"
            _write_py(f, f"IA{i} = {i}\n")
            files.append(f)
            default_cache.get_source(f)

        default_cache.invalidate_all()

        misses_before = default_cache.stats()["misses"]
        for f in files:
            default_cache.get_source(f)
        misses_after = default_cache.stats()["misses"]

        assert misses_after - misses_before == len(files), (
            f"Expected {len(files)} misses after invalidate_all() cleared the cache, "
            f"but got {misses_after - misses_before} misses."
        )

    def test_invalidate_nonexistent_path_is_safe(self, tmp_path: Path, default_cache) -> None:
        """invalidate() called on a path not in the cache must be a no-op without raising."""
        ghost = tmp_path / "ghost.py"  # never written or loaded
        try:
            default_cache.invalidate(ghost)
        except Exception as exc:  # noqa: BLE001
            pytest.fail(
                f"invalidate() raised {type(exc).__name__} for a path not in the cache: {exc}"
            )

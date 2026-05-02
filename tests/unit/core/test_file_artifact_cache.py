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

    def test_invalidate_all_drops_all_three_artifact_types(
        self, tmp_path: Path, default_cache, jedi_project: jedi.Project
    ) -> None:
        """After invalidate(path), all three artifact types (source, AST, Script) must miss."""
        f = tmp_path / "triple.py"
        _write_py(f, "X = 1\n")

        default_cache.get_source(f)
        default_cache.get_ast(f)
        default_cache.get_script(f, jedi_project)

        default_cache.invalidate(f)

        misses_before = default_cache.stats()["misses"]
        default_cache.get_source(f)
        default_cache.get_ast(f)
        default_cache.get_script(f, jedi_project)
        misses_after = default_cache.stats()["misses"]

        assert misses_after - misses_before >= 3, (
            "Expected at least 3 misses after invalidate(path) to cover source, AST, "
            f"and Script artifacts, got {misses_after - misses_before} misses."
        )

    def test_invalidate_stale_script_causes_miss(
        self, tmp_path: Path, default_cache, jedi_project: jedi.Project
    ) -> None:
        """After bumping mtime, get_script() must miss (exercises _evict_stale_script)."""
        f = tmp_path / "stale_script.py"
        _write_py(f, "Y = 2\n")

        default_cache.get_script(f, jedi_project)  # warm the cache

        _write_py(f, "Y = 99\n")
        _bump_mtime(f)

        misses_before = default_cache.stats()["misses"]
        default_cache.get_script(f, jedi_project)
        misses_after = default_cache.stats()["misses"]

        assert misses_after > misses_before, (
            "Expected a cache miss for get_script() after the file's mtime advanced, "
            "but no miss was recorded — _evict_stale_script may not be working."
        )


# --------------------------------------------------------------------------- #
# (g) Module-level convenience functions — smoke tests against the singleton  #
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=False)
def reset_default_cache():
    """Reset the module-level _default_cache before and after each test.

    Keeps module-level tests isolated from each other and from class-based
    tests that use the same process-global singleton.
    """
    mod = _import_cache_module()
    mod.invalidate_all()  # clear any state left by previous tests
    yield
    mod.invalidate_all()  # clean up after this test


class TestModuleLevelHelpers:
    """Smoke tests for the module-level convenience functions (production entry points)."""

    def test_get_source_returns_source_text_and_increments_misses(
        self, tmp_path: Path, reset_default_cache  # noqa: ARG002
    ) -> None:
        """Module-level get_source() returns file contents and records a miss."""
        mod = _import_cache_module()
        f = tmp_path / "ml_source.py"
        _write_py(f, "A = 42\n")

        misses_before = mod.stats()["misses"]
        text = mod.get_source(f)
        misses_after = mod.stats()["misses"]

        assert "A = 42" in text
        assert (
            misses_after > misses_before
        ), "Expected a miss on the first module-level get_source() call."

    def test_get_source_second_call_is_a_hit(
        self, tmp_path: Path, reset_default_cache  # noqa: ARG002
    ) -> None:
        """A second module-level get_source() call on the same file must hit the cache."""
        mod = _import_cache_module()
        f = tmp_path / "ml_hit.py"
        _write_py(f, "B = 7\n")

        first = mod.get_source(f)
        hits_before = mod.stats()["hits"]
        second = mod.get_source(f)
        hits_after = mod.stats()["hits"]

        assert first is second, "Expected identity-same object on cache hit."
        assert (
            hits_after > hits_before
        ), "Expected a hit on the second module-level get_source() call."

    def test_module_invalidate_causes_miss(
        self, tmp_path: Path, reset_default_cache  # noqa: ARG002
    ) -> None:
        """Module-level invalidate(path) causes the next get_source() to miss."""
        mod = _import_cache_module()
        f = tmp_path / "ml_inv.py"
        _write_py(f, "C = 3\n")

        mod.get_source(f)  # populate
        mod.invalidate(f)

        misses_before = mod.stats()["misses"]
        mod.get_source(f)
        misses_after = mod.stats()["misses"]

        assert (
            misses_after > misses_before
        ), "Expected a miss after module-level invalidate(), but the miss counter did not increase."

    def test_module_invalidate_all_clears_cache(
        self, tmp_path: Path, reset_default_cache  # noqa: ARG002
    ) -> None:
        """Module-level invalidate_all() causes subsequent accesses to miss."""
        mod = _import_cache_module()
        files = []
        for i in range(3):
            f = tmp_path / f"ml_ia{i}.py"
            _write_py(f, f"D{i} = {i}\n")
            files.append(f)
            mod.get_source(f)

        mod.invalidate_all()

        misses_before = mod.stats()["misses"]
        for f in files:
            mod.get_source(f)
        misses_after = mod.stats()["misses"]

        assert misses_after - misses_before == len(files), (
            f"Expected {len(files)} misses after module-level invalidate_all(), "
            f"but got {misses_after - misses_before}."
        )

    def test_module_invalidate_all_increments_evictions(
        self, tmp_path: Path, reset_default_cache  # noqa: ARG002
    ) -> None:
        """invalidate_all() must increment evictions by the count of cleared items."""
        mod = _import_cache_module()
        f1 = tmp_path / "ev1.py"
        f2 = tmp_path / "ev2.py"
        _write_py(f1, "E1 = 1\n")
        _write_py(f2, "E2 = 2\n")

        mod.get_source(f1)
        mod.get_source(f2)

        evictions_before = mod.stats()["evictions"]
        mod.invalidate_all()
        evictions_after = mod.stats()["evictions"]

        # At minimum 2 source entries were cleared
        assert evictions_after - evictions_before >= 2, (
            f"Expected evictions to increase by at least 2 after invalidate_all() cleared "
            f"2 source entries, but delta was {evictions_after - evictions_before}."
        )

    def test_module_get_ast_returns_ast_module(
        self, tmp_path: Path, reset_default_cache  # noqa: ARG002
    ) -> None:
        """Module-level get_ast() returns a parsed AST."""
        import ast as ast_module

        mod = _import_cache_module()
        f = tmp_path / "ml_ast.py"
        _write_py(f, "Z = 99\n")

        tree = mod.get_ast(f)
        assert isinstance(
            tree, ast_module.Module
        ), f"Expected module-level get_ast() to return an ast.Module, got {type(tree)}"

    def test_module_get_script_returns_jedi_script(
        self, tmp_path: Path, reset_default_cache  # noqa: ARG002
    ) -> None:
        """Module-level get_script() returns a jedi.Script."""
        mod = _import_cache_module()
        f = tmp_path / "ml_script.py"
        _write_py(f, "W = 0\n")
        project = jedi.Project(path=tmp_path)

        script = mod.get_script(f, project)
        assert isinstance(
            script, jedi.Script
        ), f"Expected module-level get_script() to return a jedi.Script, got {type(script)}"


# --------------------------------------------------------------------------- #
# (h) AST-cap eviction branches — script-only and both-stores paths           #
# --------------------------------------------------------------------------- #


class TestAstCapEvictionBranches:
    """Cover the script-only and both-stores eviction branches in _enforce_ast_cap."""

    def test_script_only_eviction_when_ast_store_empty(
        self, tmp_path: Path, jedi_project: jedi.Project
    ) -> None:
        """When only Script entries exist (no AST entries), LRU eviction evicts a Script."""
        cls = _get_cache_class()
        # Cap of 1 script entry so the second load triggers eviction
        cache = cls(ast_max_entries=1, file_max_bytes=100_000_000)

        f1 = tmp_path / "s1.py"
        f2 = tmp_path / "s2.py"
        _write_py(f1, "S1 = 1\n")
        _write_py(f2, "S2 = 2\n")

        # Populate only script store (not AST store)
        cache.get_script(f1, jedi_project)  # fills the cap
        cache.get_script(f2, jedi_project)  # must evict f1's script

        # f1 should have been evicted — accessing it must be a miss
        misses_before = cache.stats()["misses"]
        cache.get_script(f1, jedi_project)
        misses_after = cache.stats()["misses"]

        assert misses_after > misses_before, (
            "Expected a cache miss for the evicted Script entry when only the Script "
            "store was populated and the cap was exceeded."
        )
        assert cache.stats()["evictions"] >= 1

    def test_both_stores_eviction_prefers_ast(
        self, tmp_path: Path, jedi_project: jedi.Project
    ) -> None:
        """When both AST and Script stores are non-empty, eviction removes from AST store first."""
        cls = _get_cache_class()
        # Cap of 2: load 1 AST + 1 Script = at cap; load one more AST to trigger eviction
        cache = cls(ast_max_entries=2, file_max_bytes=100_000_000)

        f1 = tmp_path / "b1.py"
        f2 = tmp_path / "b2.py"
        f3 = tmp_path / "b3.py"
        _write_py(f1, "B1 = 1\n")
        _write_py(f2, "B2 = 2\n")
        _write_py(f3, "B3 = 3\n")

        # Fill: 1 AST + 1 Script = 2 entries (at cap)
        cache.get_ast(f1)
        cache.get_script(f2, jedi_project)

        # Add a third entry — both stores are non-empty, should evict AST first
        cache.get_ast(f3)

        # f1's AST should have been evicted (AST-biased policy)
        misses_before = cache.stats()["misses"]
        cache.get_ast(f1)
        misses_after = cache.stats()["misses"]

        assert misses_after > misses_before, (
            "Expected f1's AST to be evicted (AST-biased policy) when both stores were "
            "non-empty and the cap was exceeded."
        )
        # The Script entry for f2 should still be cached (hit)
        hits_before = cache.stats()["hits"]
        cache.get_script(f2, jedi_project)
        hits_after = cache.stats()["hits"]
        assert (
            hits_after > hits_before
        ), "Expected f2's Script to remain cached after AST-biased eviction."

"""Failing tests for analyzer instance caching in ProjectManager.

These tests were written BEFORE the fix (Task 1.4) to pin the desired contract.
They are expected to fail against the current implementation where
``ProjectManager.get_analyzer()`` constructs a fresh ``JediAnalyzer`` on every
call.

Contracts verified:
  (a) Two ``get_analyzer`` calls with the same ``project_path`` return the same
      ``JediAnalyzer`` instance (identity, not equality).
  (b) Two ``get_analyzer`` calls with different paths return different instances.
  (c) ``cleanup_all`` evicts cached analyzers — a call after cleanup returns a
      different instance than the one returned before cleanup.
  (d) The cached analyzer's ``scoped_cache`` is the same object across calls
      (proxy: proves the *same* JediAnalyzer is returned, not a freshly
      constructed one with a brand-new ScopedCache).

Expected failure modes (current code):
  (a) FAILS — fresh JediAnalyzer constructed each call → different ``id()``
  (b) PASSES — different paths trivially give different instances (no regression)
  (c) PASSES trivially — no analyzer cache exists, so each call always constructs
      fresh; post-cleanup call is trivially different (both are fresh each time).
      This test pins the contract for Task 1.4 so it doesn't become a regression.
  (d) FAILS — fresh JediAnalyzer means a new ScopedCache each call → different ``id()``
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pyeye.project_manager import ProjectManager

# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #


@pytest.fixture()
def project_dir(tmp_path: Path) -> Path:
    """A minimal, empty project directory (no .pyeye.json needed)."""
    return tmp_path


@pytest.fixture()
def manager() -> ProjectManager:
    """Fresh ProjectManager — no pooling, no global singleton.

    ``max_projects=10`` is large enough that the LRU eviction policy never
    interferes with the cache-identity assertions below (each test uses at most
    two distinct paths), while still being low enough to keep fixture setup fast.
    """
    return ProjectManager(max_projects=10)


# --------------------------------------------------------------------------- #
# Tests                                                                        #
# --------------------------------------------------------------------------- #


def test_same_path_returns_same_instance(manager: ProjectManager, project_dir: Path) -> None:
    """(a) Two get_analyzer calls with the same path return the identical instance.

    Fails because current code calls ``JediAnalyzer(...)`` fresh each time.
    """
    path_str = project_dir.as_posix()

    analyzer_first = manager.get_analyzer(path_str)
    analyzer_second = manager.get_analyzer(path_str)

    assert analyzer_first is analyzer_second, (
        f"Expected the same JediAnalyzer instance on repeated calls for the same path, "
        f"but got different objects (id={id(analyzer_first)} vs id={id(analyzer_second)}). "
        "Task 1.4 must memoize analyzers by resolved project path."
    )


def test_different_paths_return_different_instances(
    manager: ProjectManager, tmp_path: Path
) -> None:
    """(b) get_analyzer with different paths returns different instances.

    This is expected to pass against current code too; it pins the contract
    so Task 1.4 doesn't accidentally share analyzers across distinct projects.
    """
    path_a = tmp_path / "project_a"
    path_b = tmp_path / "project_b"
    path_a.mkdir()
    path_b.mkdir()

    analyzer_a = manager.get_analyzer(str(path_a))
    analyzer_b = manager.get_analyzer(str(path_b))

    assert analyzer_a is not analyzer_b, (
        "Expected distinct JediAnalyzer instances for different project paths, "
        f"but got the same object (id={id(analyzer_a)})."
    )


def test_cleanup_all_evicts_analyzer_cache(manager: ProjectManager, project_dir: Path) -> None:
    """(c) cleanup_all must evict cached analyzers so the next call returns a fresh instance.

    After Task 1.4 caches analyzers, cleanup_all must also clear that cache.
    Against current code this passes trivially (every call is already fresh),
    but it is still a meaningful regression guard for Task 1.4.
    """
    path_str = project_dir.as_posix()

    analyzer_before = manager.get_analyzer(path_str)
    manager.cleanup_all()
    analyzer_after = manager.get_analyzer(path_str)

    assert analyzer_before is not analyzer_after, (
        "Expected a different JediAnalyzer instance after cleanup_all (cache must be evicted), "
        f"but got the same object (id={id(analyzer_before)}). "
        "Task 1.4 must clear the analyzer cache inside cleanup_all."
    )


def test_scoped_cache_identity_across_calls(manager: ProjectManager, project_dir: Path) -> None:
    """(d) The ScopedCache reference is identical across repeated get_analyzer calls.

    ``JediAnalyzer.__init__`` creates a fresh ``ScopedCache`` at line 68 every
    time it is constructed.  If get_analyzer returns the same JediAnalyzer
    instance (Task 1.4 goal), the scoped_cache attribute must be the same object.

    Fails because current code constructs a new JediAnalyzer (and therefore a
    new ScopedCache) on every call.
    """
    path_str = project_dir.as_posix()

    analyzer_first = manager.get_analyzer(path_str)
    cache_first = analyzer_first.scoped_cache

    analyzer_second = manager.get_analyzer(path_str)
    cache_second = analyzer_second.scoped_cache

    assert cache_first is cache_second, (
        "Expected the same ScopedCache object across repeated get_analyzer calls for the "
        f"same path (proxy for same JediAnalyzer instance), but got different objects "
        f"(id={id(cache_first)} vs id={id(cache_second)}). "
        "Task 1.4 memoization must preserve the scoped_cache reference."
    )

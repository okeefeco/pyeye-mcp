"""Performance tests for scope features."""

import asyncio
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from pycodemcp.config import ProjectConfig
from pycodemcp.scope_utils import (
    LazyNamespaceLoader,
    ScopedCache,
    SmartScopeResolver,
    parallel_search,
)
from tests.utils.performance import (
    PerformanceThresholds,
    assert_performance_threshold,
)


@pytest.mark.asyncio
class TestScopedCachePerformance:
    """Test scoped cache performance."""

    async def test_cache_hit_performance(self):
        """Test that cache hits are fast."""
        cache = ScopedCache(ttl_seconds=300)

        # Populate cache
        for i in range(100):
            cache.set(f"key_{i}", f"value_{i}", "main")
            cache.set(f"key_{i}", f"value_{i}_all", "all")

        # Measure cache hit time for 100k lookups
        start = time.time()
        for _ in range(1000):
            for i in range(100):
                value = cache.get(f"key_{i}", "main")
                assert value == f"value_{i}"
        elapsed_ms = (time.time() - start) * 1000

        # Define thresholds for 100k cache lookups
        bulk_cache_threshold = PerformanceThresholds(
            base=200.0,  # 200ms for local development
            linux_ci=400.0,  # 400ms for Linux CI
            macos_ci=800.0,  # 800ms for macOS CI
            windows_ci=800.0,  # 800ms for Windows CI
        )

        assert_performance_threshold(elapsed_ms, bulk_cache_threshold, "Cache lookups (100k ops)")

    async def test_scoped_cache_isolation(self):
        """Test that scoped caches are isolated."""
        cache = ScopedCache(ttl_seconds=300)

        # Set different values in different scopes
        cache.set("key", "main_value", "main")
        cache.set("key", "all_value", "all")
        cache.set("key", "namespace_value", "namespace:test")

        # Verify isolation
        assert cache.get("key", "main") == "main_value"
        assert cache.get("key", "all") == "all_value"
        assert cache.get("key", "namespace:test") == "namespace_value"

        # Invalidate one scope
        cache.invalidate_scope("main")

        # Check only that scope was invalidated
        assert cache.get("key", "main") is None
        assert cache.get("key", "all") == "all_value"
        assert cache.get("key", "namespace:test") == "namespace_value"

    async def test_cache_ttl_performance(self):
        """Test cache TTL expiration."""
        cache = ScopedCache(ttl_seconds=0.1)  # 100ms TTL

        cache.set("key", "value", "main")
        assert cache.get("key", "main") == "value"

        # Wait for expiration
        await asyncio.sleep(0.15)

        # Should be expired
        assert cache.get("key", "main") is None


@pytest.mark.asyncio
class TestParallelSearchPerformance:
    """Test parallel search performance."""

    async def test_parallel_vs_sequential(self, tmp_path):
        """Test that parallel search is faster than sequential."""
        # Create multiple search paths
        paths = []
        for i in range(5):
            dir_path = tmp_path / f"dir_{i}"
            dir_path.mkdir()
            for j in range(20):
                (dir_path / f"file_{j}.py").touch()
            paths.append(dir_path)

        # Mock rglob_async to add delay
        async def mock_rglob(pattern, path):
            await asyncio.sleep(0.1)  # Simulate I/O delay
            return list(path.glob(pattern))

        with patch("pycodemcp.scope_utils.rglob_async", mock_rglob):
            # Measure parallel search
            start = time.time()
            parallel_results = await parallel_search("*.py", paths, max_concurrent=5)
            parallel_time = time.time() - start

            # Measure sequential search (simulated)
            start = time.time()
            sequential_results = []
            for path in paths:
                results = await mock_rglob("*.py", path)
                sequential_results.extend(results)
            sequential_time = time.time() - start

            # Parallel should be significantly faster
            assert (
                parallel_time < sequential_time * 0.5
            ), f"Parallel ({parallel_time:.3f}s) not faster than sequential ({sequential_time:.3f}s)"

            # Results should be the same (unordered)
            assert len(parallel_results) == len(sequential_results)

    async def test_parallel_search_concurrency_limit(self):
        """Test that parallel search respects concurrency limit."""
        paths = [Path(f"/path_{i}") for i in range(20)]

        concurrent_count = 0
        max_concurrent_seen = 0

        async def mock_rglob(pattern, path):  # noqa: ARG001
            nonlocal concurrent_count, max_concurrent_seen
            concurrent_count += 1
            max_concurrent_seen = max(max_concurrent_seen, concurrent_count)
            await asyncio.sleep(0.01)
            concurrent_count -= 1
            return []

        with patch("pycodemcp.scope_utils.rglob_async", mock_rglob):
            await parallel_search("*.py", paths, max_concurrent=5)

            # Should never exceed the limit
            assert (
                max_concurrent_seen <= 5
            ), f"Exceeded concurrency limit: {max_concurrent_seen} > 5"


@pytest.mark.asyncio
class TestLazyNamespaceLoader:
    """Test lazy namespace loading performance."""

    async def test_lazy_loading_performance(self):
        """Test that namespaces are loaded on demand."""
        loader = LazyNamespaceLoader()

        namespace_paths = {
            "namespace1": [Path("/path1")],
            "namespace2": [Path("/path2")],
            "namespace3": [Path("/path3")],
        }

        load_count = 0

        async def mock_rglob(pattern, path):  # noqa: ARG001
            nonlocal load_count
            load_count += 1
            await asyncio.sleep(0.01)
            return [path / f"file_{i}.py" for i in range(10)]

        with patch("pycodemcp.scope_utils.rglob_async", mock_rglob):
            # First access should load
            files1 = await loader.get_namespace_files("namespace1", namespace_paths)
            assert load_count == 1
            assert len(files1) == 10

            # Second access should use cache
            files2 = await loader.get_namespace_files("namespace1", namespace_paths)
            assert load_count == 1  # No additional load
            assert files1 == files2

            # Different namespace should load
            files3 = await loader.get_namespace_files("namespace2", namespace_paths)
            assert load_count == 2
            assert len(files3) == 10

    async def test_lazy_loader_concurrent_access(self):
        """Test that concurrent access doesn't cause duplicate loading."""
        loader = LazyNamespaceLoader()

        namespace_paths = {
            "namespace1": [Path("/path1")],
        }

        load_count = 0

        async def mock_rglob(pattern, path):  # noqa: ARG001
            nonlocal load_count
            load_count += 1
            await asyncio.sleep(0.1)  # Simulate slow load
            return [path / f"file_{i}.py" for i in range(10)]

        with patch("pycodemcp.scope_utils.rglob_async", mock_rglob):
            # Launch multiple concurrent requests
            tasks = [loader.get_namespace_files("namespace1", namespace_paths) for _ in range(10)]
            results = await asyncio.gather(*tasks)

            # Should only load once despite concurrent access
            assert load_count == 1

            # All results should be the same
            for result in results:
                assert result == results[0]


class TestSmartScopeResolver:
    """Test smart scope resolver."""

    def test_smart_defaults(self):
        """Test method-specific smart defaults."""
        resolver = SmartScopeResolver()

        # Methods that should search everywhere
        assert resolver.get_smart_default("find_subclasses") == "all"
        assert resolver.get_smart_default("find_references") == "all"
        assert resolver.get_smart_default("analyze_dependencies") == "all"
        assert resolver.get_smart_default("find_symbol") == "all"

        # Methods that should search main only
        assert resolver.get_smart_default("list_modules") == "main"
        assert resolver.get_smart_default("list_packages") == "main"
        assert resolver.get_smart_default("find_routes") == "main"

        # Unknown method should default to "all"
        assert resolver.get_smart_default("unknown_method") == "all"

    def test_user_configured_defaults(self, tmp_path):
        """Test user-configured scope defaults."""
        config_file = tmp_path / ".pycodemcp.json"
        config_file.write_text(
            """{
            "scope_defaults": {
                "global": "namespace:custom",
                "methods": {
                    "list_modules": "all",
                    "find_routes": "namespace:api"
                }
            }
        }"""
        )

        config = ProjectConfig(str(tmp_path))
        resolver = SmartScopeResolver(config)

        # User overrides
        assert resolver.get_smart_default("list_modules") == "all"
        assert resolver.get_smart_default("find_routes") == "namespace:api"

        # Global default for unknown methods
        assert resolver.get_smart_default("unknown_method") == "namespace:custom"

        # Unmodified defaults (still uses built-in)
        assert resolver.get_smart_default("find_references") == "all"

    def test_scope_alias_resolution(self, tmp_path):
        """Test scope alias resolution."""
        config_file = tmp_path / ".pycodemcp.json"
        config_file.write_text(
            """{
            "scope_aliases": {
                "backend": ["namespace:api", "namespace:db"],
                "all-services": ["main", "backend", "namespace:workers"]
            }
        }"""
        )

        config = ProjectConfig(str(tmp_path))
        resolver = SmartScopeResolver(config)

        # Simple alias
        assert resolver.resolve_aliases("backend") == ["namespace:api", "namespace:db"]

        # Nested aliases (should not recurse infinitely)
        assert resolver.resolve_aliases("all-services") == ["main", "backend", "namespace:workers"]

        # Non-alias passthrough
        assert resolver.resolve_aliases("main") == "main"

        # List with aliases
        resolved = resolver.resolve_aliases(["main", "backend"])
        assert resolved == ["main", "namespace:api", "namespace:db"]


@pytest.mark.asyncio
class TestPerformanceBenchmarks:
    """Overall performance benchmarks."""

    async def test_large_namespace_performance(self, tmp_path):
        """Test performance with large number of namespaces."""
        # Create 50 namespace directories
        namespace_paths = {}
        for i in range(50):
            ns_name = f"namespace_{i}"
            ns_path = tmp_path / ns_name
            ns_path.mkdir()

            # Add some files to each
            for j in range(10):
                (ns_path / f"module_{j}.py").touch()

            namespace_paths[ns_name] = [ns_path]

        # Test lazy loader with many namespaces
        loader = LazyNamespaceLoader()

        start = time.time()

        # Load several namespaces
        tasks = []
        for i in range(10):
            tasks.append(loader.get_namespace_files(f"namespace_{i}", namespace_paths))

        results = await asyncio.gather(*tasks)
        elapsed = time.time() - start

        # Should complete within 2 seconds even with many namespaces
        assert elapsed < 2.0, f"Loading 10 namespaces took {elapsed:.3f}s"

        # Verify results
        for result in results:
            assert len(result) == 10

    async def test_cache_memory_efficiency(self):
        """Test that scoped cache doesn't use excessive memory."""
        cache = ScopedCache(ttl_seconds=300)

        # Add many entries across different scopes
        for scope in ["main", "all", "namespace:1", "namespace:2"]:
            for i in range(1000):
                cache.set(f"key_{i}", f"value_{i}" * 100, scope)

        # Get cache stats
        stats = cache.get_stats()

        # Should have 4 scopes
        assert stats["scope_count"] == 4

        # Each scope should have 1000 entries
        for scope_stats in stats["scopes"].values():
            assert scope_stats["entry_count"] == 1000

    async def test_parallel_search_scalability(self, tmp_path):
        """Test parallel search scales well with many paths."""
        # Create many search paths
        paths = []
        for i in range(100):
            dir_path = tmp_path / f"dir_{i}"
            dir_path.mkdir()
            (dir_path / "file.py").touch()
            paths.append(dir_path)

        start = time.time()
        results = await parallel_search("*.py", paths, max_concurrent=20)
        elapsed = time.time() - start

        # Should handle 100 paths efficiently
        assert elapsed < 1.0, f"Searching 100 paths took {elapsed:.3f}s"
        assert len(results) == 100

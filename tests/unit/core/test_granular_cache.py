"""Tests for granular cache with smart invalidation."""

import threading
import time
from pathlib import Path

import pytest

from pycodemcp.cache import CacheMetrics, GranularCache
from pycodemcp.dependency_tracker import DependencyTracker


class TestCacheMetrics:
    """Test suite for CacheMetrics."""

    def test_init(self):
        """Test metrics initialization."""
        metrics = CacheMetrics()
        assert metrics.hits == 0
        assert metrics.misses == 0
        assert metrics.invalidations == 0
        assert metrics.total_entries == 0
        assert metrics.file_invalidations == 0
        assert metrics.module_invalidations == 0
        assert metrics.cascade_invalidations == 0
        assert metrics.last_hit is None
        assert metrics.last_miss is None
        assert metrics.last_invalidation is None

    def test_hit_rate(self):
        """Test hit rate calculation."""
        metrics = CacheMetrics()

        # No data
        assert metrics.hit_rate == 0.0

        # Some hits and misses
        metrics.hits = 75
        metrics.misses = 25
        assert metrics.hit_rate == 75.0

        # All hits
        metrics.hits = 100
        metrics.misses = 0
        assert metrics.hit_rate == 100.0

        # All misses
        metrics.hits = 0
        metrics.misses = 100
        assert metrics.hit_rate == 0.0

    def test_record_hit(self):
        """Test recording cache hits."""
        metrics = CacheMetrics()

        before = time.time()
        metrics.record_hit()
        after = time.time()

        assert metrics.hits == 1
        assert before <= metrics.last_hit <= after

        # Multiple hits
        metrics.record_hit()
        metrics.record_hit()
        assert metrics.hits == 3

    def test_record_miss(self):
        """Test recording cache misses."""
        metrics = CacheMetrics()

        before = time.time()
        metrics.record_miss()
        after = time.time()

        assert metrics.misses == 1
        assert before <= metrics.last_miss <= after

        # Multiple misses
        metrics.record_miss()
        metrics.record_miss()
        assert metrics.misses == 3

    def test_record_invalidation(self):
        """Test recording cache invalidations."""
        metrics = CacheMetrics()

        before = time.time()
        metrics.record_invalidation()
        after = time.time()

        assert metrics.invalidations == 1
        assert before <= metrics.last_invalidation <= after

        # Multiple invalidations at once
        metrics.record_invalidation(5)
        assert metrics.invalidations == 6


class TestGranularCache:
    """Test suite for GranularCache."""

    @pytest.fixture
    def cache(self):
        """Create a fresh granular cache."""
        return GranularCache(ttl_seconds=300)

    def test_init(self, cache):
        """Test cache initialization."""
        assert cache.ttl == 300
        assert isinstance(cache.dependency_tracker, DependencyTracker)
        assert cache.file_cache == {}
        assert cache.module_cache == {}
        assert isinstance(cache.metrics, CacheMetrics)
        assert cache._lock is not None

    def test_get_with_metrics(self, cache):
        """Test cache get with metrics tracking."""
        # Cache miss
        result = cache.get("nonexistent")
        assert result is None
        assert cache.metrics.misses == 1
        assert cache.metrics.hits == 0

        # Cache hit
        cache.set("key1", "value1")
        result = cache.get("key1")
        assert result == "value1"
        assert cache.metrics.hits == 1
        assert cache.metrics.misses == 1

        # Another hit
        result = cache.get("key1")
        assert result == "value1"
        assert cache.metrics.hits == 2

    def test_set_with_file_association(self, cache):
        """Test cache set with file path association."""
        file_path = Path("/project/module.py")

        cache.set("key1", "value1", file_path=file_path)

        assert "key1" in cache.cache
        assert file_path.resolve() in cache.file_cache
        assert "key1" in cache.file_cache[file_path.resolve()]
        assert cache.metrics.total_entries == 1

        # Add another key for same file
        cache.set("key2", "value2", file_path=file_path)
        assert len(cache.file_cache[file_path.resolve()]) == 2
        assert cache.metrics.total_entries == 2

    def test_set_with_module_association(self, cache):
        """Test cache set with module name association."""
        cache.set("key1", "value1", module_name="module_a")

        assert "key1" in cache.cache
        assert "module_a" in cache.module_cache
        assert "key1" in cache.module_cache["module_a"]
        assert cache.metrics.total_entries == 1

        # Add another key for same module
        cache.set("key2", "value2", module_name="module_a")
        assert len(cache.module_cache["module_a"]) == 2
        assert cache.metrics.total_entries == 2

    def test_set_with_both_associations(self, cache):
        """Test cache set with both file and module associations."""
        file_path = Path("/project/module_a.py")

        cache.set("key1", "value1", file_path=file_path, module_name="module_a")

        assert "key1" in cache.cache
        assert file_path.resolve() in cache.file_cache
        assert "module_a" in cache.module_cache
        assert "key1" in cache.file_cache[file_path.resolve()]
        assert "key1" in cache.module_cache["module_a"]

    def test_invalidate_file(self, cache):
        """Test file-specific cache invalidation."""
        file1 = Path("/project/module1.py")
        file2 = Path("/project/module2.py")

        # Set up cache entries
        cache.set("key1", "value1", file_path=file1)
        cache.set("key2", "value2", file_path=file1)
        cache.set("key3", "value3", file_path=file2)
        cache.set("key4", "value4")  # No file association

        assert len(cache.cache) == 4

        # Invalidate file1
        count = cache.invalidate_file(file1)

        assert count == 2  # Only entries associated with file1
        assert "key1" not in cache.cache
        assert "key2" not in cache.cache
        assert "key3" in cache.cache
        assert "key4" in cache.cache
        assert file1.resolve() not in cache.file_cache
        assert cache.metrics.file_invalidations == 1
        assert cache.metrics.invalidations == 2
        assert cache.metrics.total_entries == 2

    def test_invalidate_file_with_dependencies(self, cache):
        """Test file invalidation with dependent modules."""
        file1 = Path("/project/core.py")
        file2 = Path("/project/utils.py")

        # Set up dependencies
        cache.dependency_tracker.add_file_mapping(file1, "core")
        cache.dependency_tracker.add_file_mapping(file2, "utils")
        cache.dependency_tracker.add_import("utils", "core")

        # Set up cache entries
        cache.set("core_data", "data1", file_path=file1, module_name="core")
        cache.set("utils_data", "data2", file_path=file2, module_name="utils")

        # Invalidate core file (should also invalidate utils)
        count = cache.invalidate_file(file1)

        assert count == 2  # Both core and utils invalidated
        assert "core_data" not in cache.cache
        assert "utils_data" not in cache.cache

    def test_invalidate_module(self, cache):
        """Test module-specific cache invalidation."""
        # Set up cache entries
        cache.set("key1", "value1", module_name="module_a")
        cache.set("key2", "value2", module_name="module_a")
        cache.set("key3", "value3", module_name="module_b")
        cache.set("key4", "value4")  # No module association

        assert len(cache.cache) == 4

        # Invalidate module_a
        count = cache.invalidate_module("module_a")

        assert count == 2
        assert "key1" not in cache.cache
        assert "key2" not in cache.cache
        assert "key3" in cache.cache
        assert "key4" in cache.cache
        assert "module_a" not in cache.module_cache
        assert cache.metrics.module_invalidations == 1
        assert cache.metrics.invalidations == 2

    def test_invalidate_dependents(self, cache):
        """Test invalidating dependent modules."""
        # Set up dependencies
        cache.dependency_tracker.add_import("module_b", "module_a")
        cache.dependency_tracker.add_import("module_c", "module_a")

        # Set up cache entries
        cache.set("key_a", "value_a", module_name="module_a")
        cache.set("key_b", "value_b", module_name="module_b")
        cache.set("key_c", "value_c", module_name="module_c")
        cache.set("key_d", "value_d", module_name="module_d")

        # Invalidate dependents of module_a
        count = cache.invalidate_dependents("module_a")

        assert count == 2  # module_b and module_c
        assert "key_a" in cache.cache  # module_a itself not invalidated
        assert "key_b" not in cache.cache
        assert "key_c" not in cache.cache
        assert "key_d" in cache.cache
        assert cache.metrics.cascade_invalidations == 1

    def test_invalidate_pattern(self, cache):
        """Test pattern-based invalidation with metrics."""
        # Set up cache entries with file and module associations
        file1 = Path("/project/test.py")
        cache.set("test_key1", "value1", file_path=file1, module_name="test")
        cache.set("test_key2", "value2", module_name="test")
        cache.set("other_key", "value3")

        assert len(cache.cache) == 3

        # Invalidate by pattern
        cache.invalidate("test")

        assert "test_key1" not in cache.cache
        assert "test_key2" not in cache.cache
        assert "other_key" in cache.cache
        assert cache.metrics.invalidations == 2
        assert cache.metrics.total_entries == 1

    def test_invalidate_all(self, cache):
        """Test invalidating all cache entries."""
        # Set up various cache entries
        file1 = Path("/project/module1.py")
        cache.set("key1", "value1", file_path=file1, module_name="module1")
        cache.set("key2", "value2", module_name="module2")
        cache.set("key3", "value3")

        # Set up some dependencies
        cache.dependency_tracker.add_import("module1", "module2")

        assert len(cache.cache) == 3
        assert len(cache.file_cache) == 1
        assert len(cache.module_cache) == 2
        assert len(cache.dependency_tracker.imports) == 1

        # Invalidate all
        cache.invalidate(None)

        assert len(cache.cache) == 0
        assert len(cache.file_cache) == 0
        assert len(cache.module_cache) == 0
        assert len(cache.dependency_tracker.imports) == 0
        assert cache.metrics.invalidations == 3
        assert cache.metrics.total_entries == 0

    def test_get_metrics(self, cache):
        """Test getting comprehensive metrics."""
        # Perform various cache operations
        cache.get("miss1")  # Miss
        cache.set("hit1", "value1", module_name="module1")
        cache.get("hit1")  # Hit
        cache.get("miss2")  # Miss

        file1 = Path("/project/module1.py")
        cache.dependency_tracker.add_file_mapping(file1, "module1")
        cache.dependency_tracker.add_import("module2", "module1")

        cache.invalidate_module("module1")

        metrics = cache.get_metrics()

        assert metrics["cache"]["hits"] == 1
        assert metrics["cache"]["misses"] == 2
        assert metrics["cache"]["hit_rate"] == "33.3%"
        assert metrics["cache"]["total_entries"] == 0  # After invalidation
        assert metrics["cache"]["invalidations"]["total"] == 1
        assert metrics["cache"]["invalidations"]["module"] == 1

        assert metrics["dependencies"]["total_modules"] == 1
        assert metrics["dependencies"]["modules_with_imports"] == 1

        assert metrics["mappings"]["files_tracked"] == 0  # After invalidation
        assert metrics["mappings"]["modules_tracked"] == 0

    def test_clear_metrics(self, cache):
        """Test resetting cache metrics."""
        # Generate some metrics
        cache.get("miss")
        cache.set("key", "value")
        cache.get("key")
        cache.invalidate_module("module")

        assert cache.metrics.hits > 0
        assert cache.metrics.misses > 0

        # Clear metrics
        cache.clear_metrics()

        assert cache.metrics.hits == 0
        assert cache.metrics.misses == 0
        assert cache.metrics.invalidations == 0
        assert cache.metrics.total_entries == 1  # Still has the "key" entry

    def test_thread_safety(self, cache):
        """Test thread-safe cache operations."""
        results = []
        errors = []

        def writer(n):
            """Thread that writes to cache."""
            try:
                for i in range(10):
                    cache.set(f"key_{n}_{i}", f"value_{n}_{i}", module_name=f"module_{n}")
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        def reader(n):
            """Thread that reads from cache."""
            try:
                for i in range(10):
                    result = cache.get(f"key_{n % 3}_{i}")
                    if result:
                        results.append(result)
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        def invalidator():
            """Thread that invalidates cache."""
            try:
                time.sleep(0.01)
                cache.invalidate_module("module_1")
                time.sleep(0.01)
                cache.invalidate_module("module_2")
            except Exception as e:
                errors.append(e)

        # Start multiple threads
        threads = []
        for i in range(3):
            threads.append(threading.Thread(target=writer, args=(i,)))
            threads.append(threading.Thread(target=reader, args=(i,)))
        threads.append(threading.Thread(target=invalidator))

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        # No errors should occur
        assert len(errors) == 0

        # Cache should be in consistent state
        assert isinstance(cache.metrics.hits, int)
        assert isinstance(cache.metrics.misses, int)
        assert len(cache.cache) >= 0

    def test_expiration_handling(self, cache):
        """Test TTL expiration with metrics."""
        # Create cache with short TTL
        cache = GranularCache(ttl_seconds=0.1)

        cache.set("key1", "value1")

        # Should hit before expiration
        assert cache.get("key1") == "value1"
        assert cache.metrics.hits == 1

        # Wait for expiration
        time.sleep(0.2)

        # Should miss after expiration
        assert cache.get("key1") is None
        assert cache.metrics.misses == 1
        assert "key1" not in cache.cache

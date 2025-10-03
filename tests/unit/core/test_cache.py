"""Tests for caching and file watching components."""

import time
from unittest.mock import Mock, patch

from watchdog.events import DirModifiedEvent, FileModifiedEvent

from pyeye.cache import CodebaseWatcher, ProjectCache


class TestCodebaseWatcher:
    """Test the CodebaseWatcher class."""

    def test_initialization(self, temp_project_dir):
        """Test watcher initialization."""
        callback = Mock()
        watcher = CodebaseWatcher(str(temp_project_dir), callback)

        assert watcher.project_path == temp_project_dir
        assert watcher.on_change_callback == callback
        assert watcher.last_change > 0
        assert watcher._observer is None

    @patch("pyeye.cache.Observer")
    def test_start_watching(self, mock_observer_class, temp_project_dir):
        """Test starting the file watcher."""
        mock_observer = Mock()
        mock_observer_class.return_value = mock_observer

        watcher = CodebaseWatcher(str(temp_project_dir))
        watcher.start()

        assert watcher._observer == mock_observer
        mock_observer.schedule.assert_called_once_with(
            watcher, str(temp_project_dir), recursive=True
        )
        mock_observer.start.assert_called_once()

    @patch("pyeye.cache.Observer")
    def test_stop_watching(self, mock_observer_class, temp_project_dir):
        """Test stopping the file watcher."""
        mock_observer = Mock()
        mock_observer_class.return_value = mock_observer

        watcher = CodebaseWatcher(str(temp_project_dir))
        watcher.start()
        watcher.stop()

        mock_observer.stop.assert_called_once()
        mock_observer.join.assert_called_once()
        assert watcher._observer is None

    def test_on_modified_python_file(self, temp_project_dir):
        """Test handling Python file modifications."""
        from pyeye.settings import settings

        callback = Mock()
        watcher = CodebaseWatcher(str(temp_project_dir), callback)

        # Create a mock file event
        event = FileModifiedEvent(str(temp_project_dir / "test.py"))
        old_time = watcher.last_change

        # Small delay to ensure time difference
        time.sleep(0.01)
        watcher.on_modified(event)

        # Wait for debounce delay with platform-specific timing
        # macOS seems to need more time for Timer threads to execute reliably
        import platform

        extra_wait = 0.5 if platform.system() == "Darwin" else 0.1
        time.sleep(settings.watcher_debounce + extra_wait)

        assert watcher.last_change > old_time
        callback.assert_called_once_with(str(temp_project_dir / "test.py"))

    def test_on_modified_ignores_non_python(self, temp_project_dir):
        """Test that non-Python files are ignored."""
        callback = Mock()
        watcher = CodebaseWatcher(str(temp_project_dir), callback)

        # Create events for non-Python files
        events = [
            FileModifiedEvent(str(temp_project_dir / "test.txt")),
            FileModifiedEvent(str(temp_project_dir / "data.json")),
            FileModifiedEvent(str(temp_project_dir / "README.md")),
        ]

        for event in events:
            watcher.on_modified(event)

        # Callback should not be called
        callback.assert_not_called()

    def test_on_modified_ignores_directories(self, temp_project_dir):
        """Test that directory modifications are ignored."""
        callback = Mock()
        watcher = CodebaseWatcher(str(temp_project_dir), callback)

        # Create a directory event
        event = DirModifiedEvent(str(temp_project_dir))
        watcher.on_modified(event)

        callback.assert_not_called()

    def test_is_stale_check(self, temp_project_dir):
        """Test checking if cache is stale."""
        watcher = CodebaseWatcher(str(temp_project_dir))

        # Cache time before last change
        old_cache_time = watcher.last_change - 1
        assert watcher.is_stale(old_cache_time) is True

        # Cache time after last change
        new_cache_time = watcher.last_change + 1
        assert watcher.is_stale(new_cache_time) is False

    @patch("pyeye.cache.Observer")
    def test_start_idempotent(self, mock_observer_class, temp_project_dir):
        """Test that starting multiple times doesn't create multiple observers."""
        mock_observer = Mock()
        mock_observer_class.return_value = mock_observer

        watcher = CodebaseWatcher(str(temp_project_dir))
        watcher.start()
        watcher.start()  # Second start should not create new observer

        # Should only be called once
        mock_observer_class.assert_called_once()

    def test_stop_without_start(self, temp_project_dir):
        """Test stopping without starting doesn't raise errors."""
        watcher = CodebaseWatcher(str(temp_project_dir))
        watcher.stop()  # Should not raise


class TestProjectCache:
    """Test the ProjectCache class."""

    def test_initialization(self):
        """Test cache initialization."""
        cache = ProjectCache(ttl_seconds=120)

        assert cache.ttl == 120
        assert len(cache.cache) == 0
        assert len(cache.timestamps) == 0

    def test_set_and_get(self):
        """Test setting and getting cache values."""
        cache = ProjectCache()

        # Set a value
        cache.set("key1", "value1")

        # Get the value
        result = cache.get("key1")
        assert result == "value1"

    def test_get_nonexistent_key(self):
        """Test getting a non-existent key returns None."""
        cache = ProjectCache()

        result = cache.get("nonexistent")
        assert result is None

    def test_ttl_expiration(self):
        """Test that cache entries expire after TTL."""
        cache = ProjectCache(ttl_seconds=0.1)  # 100ms TTL

        cache.set("key1", "value1")

        # Should be available immediately
        assert cache.get("key1") == "value1"

        # Wait for expiration
        time.sleep(0.15)

        # Should be expired
        assert cache.get("key1") is None
        assert "key1" not in cache.cache
        assert "key1" not in cache.timestamps

    def test_update_existing_key(self):
        """Test updating an existing cache key."""
        cache = ProjectCache()

        cache.set("key1", "value1")
        old_timestamp = cache.timestamps["key1"]

        time.sleep(0.01)
        cache.set("key1", "value2")

        assert cache.get("key1") == "value2"
        assert cache.timestamps["key1"] > old_timestamp

    def test_invalidate_all(self):
        """Test invalidating all cache entries."""
        cache = ProjectCache()

        # Add multiple entries
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")

        # Invalidate all
        cache.invalidate()

        assert len(cache.cache) == 0
        assert len(cache.timestamps) == 0
        assert cache.get("key1") is None
        assert cache.get("key2") is None
        assert cache.get("key3") is None

    def test_invalidate_pattern(self):
        """Test invalidating cache entries by pattern."""
        cache = ProjectCache()

        # Add entries
        cache.set("api_user_1", "user1")
        cache.set("api_user_2", "user2")
        cache.set("api_post_1", "post1")
        cache.set("other_data", "data")

        # Invalidate entries matching pattern
        cache.invalidate("api_user")

        # User entries should be gone
        assert cache.get("api_user_1") is None
        assert cache.get("api_user_2") is None

        # Other entries should remain
        assert cache.get("api_post_1") == "post1"
        assert cache.get("other_data") == "data"

    def test_multiple_ttl_values(self):
        """Test that different cache instances can have different TTLs."""
        cache1 = ProjectCache(ttl_seconds=100)
        cache2 = ProjectCache(ttl_seconds=200)

        assert cache1.ttl == 100
        assert cache2.ttl == 200

    def test_cache_complex_objects(self):
        """Test caching complex Python objects."""
        cache = ProjectCache()

        # Cache various types
        cache.set("list", [1, 2, 3])
        cache.set("dict", {"a": 1, "b": 2})
        cache.set("tuple", (1, 2, 3))
        cache.set("set", {1, 2, 3})

        assert cache.get("list") == [1, 2, 3]
        assert cache.get("dict") == {"a": 1, "b": 2}
        assert cache.get("tuple") == (1, 2, 3)
        assert cache.get("set") == {1, 2, 3}

    def test_cache_none_value(self):
        """Test caching None as a value."""
        cache = ProjectCache()

        cache.set("key", None)

        # Should return None but key should exist
        assert cache.get("key") is None
        assert "key" in cache.cache

    def test_concurrent_access(self):
        """Test that cache handles rapid concurrent-like access."""
        cache = ProjectCache()

        # Simulate rapid access
        for i in range(100):
            cache.set(f"key{i}", f"value{i}")

        # All should be retrievable
        for i in range(100):
            assert cache.get(f"key{i}") == f"value{i}"

    def test_memory_cleanup_on_expiration(self):
        """Test that expired entries are cleaned up from memory."""
        cache = ProjectCache(ttl_seconds=0.1)

        # Add many entries
        for i in range(10):
            cache.set(f"key{i}", f"value{i}" * 1000)  # Large values

        # Verify they exist
        assert len(cache.cache) == 10

        # Wait for expiration
        time.sleep(0.15)

        # Access one key to trigger cleanup
        cache.get("key0")

        # Should be cleaned up
        assert "key0" not in cache.cache
        assert "key0" not in cache.timestamps

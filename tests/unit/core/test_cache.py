"""Tests for caching and file watching components."""

import time
from unittest.mock import Mock, patch

from watchdog.events import DirModifiedEvent, FileModifiedEvent

from pyeye.cache import CodebaseWatcher


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
        # The callback receives the whole debounced batch (#617).
        callback.assert_called_once_with([str(temp_project_dir / "test.py")])

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

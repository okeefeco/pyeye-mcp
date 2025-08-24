"""Comprehensive tests for path_utils module."""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from pycodemcp.path_utils import (
    ensure_posix_path,
    normalize_path,
    path_to_key,
    paths_equal,
    to_os_path,
)


class TestNormalizePath:
    """Test normalize_path function."""

    def test_normalize_relative_path(self):
        """Test normalizing a relative path."""
        path = normalize_path("./test")
        assert path.is_absolute()
        assert isinstance(path, Path)

    def test_normalize_absolute_path(self):
        """Test normalizing an absolute path."""
        abs_path = "/tmp/test"
        path = normalize_path(abs_path)
        assert path.is_absolute()
        assert str(path).endswith("test")

    def test_normalize_path_object(self):
        """Test normalizing a Path object."""
        path_obj = Path("./test")
        path = normalize_path(path_obj)
        assert path.is_absolute()
        assert isinstance(path, Path)

    def test_normalize_with_symlink(self, tmp_path):
        """Test normalizing a path with symlinks."""
        # Create a real file
        real_file = tmp_path / "real_file.txt"
        real_file.write_text("test")

        # Create a symlink
        symlink = tmp_path / "symlink.txt"
        symlink.symlink_to(real_file)

        # Normalize should resolve symlink
        normalized = normalize_path(symlink)
        assert normalized == real_file.resolve()

    def test_normalize_home_path(self):
        """Test normalizing a path with ~ home directory."""
        # Use expanduser to handle ~ properly on all platforms
        path = normalize_path(Path("~/test").expanduser())
        assert path.is_absolute()
        # On Windows, home might be different, just check it's absolute
        assert path.is_absolute()

    def test_normalize_empty_path(self):
        """Test normalizing an empty path (current directory)."""
        path = normalize_path("")
        assert path.is_absolute()
        assert path == Path.cwd().resolve()

    def test_normalize_dot_path(self):
        """Test normalizing . (current directory)."""
        path = normalize_path(".")
        assert path.is_absolute()
        assert path == Path.cwd().resolve()

    def test_normalize_parent_path(self):
        """Test normalizing .. (parent directory)."""
        path = normalize_path("..")
        assert path.is_absolute()
        assert path == Path.cwd().parent.resolve()


class TestPathToKey:
    """Test path_to_key function."""

    def test_path_to_key_basic(self):
        """Test converting a basic path to key."""
        key = path_to_key("./test")
        assert "/" in key  # Should use POSIX format
        assert "\\" not in key  # No backslashes
        assert key.endswith("/test")

    def test_path_to_key_windows_path(self):
        """Test converting a Windows-style path."""
        # On Unix, backslashes are treated as part of the filename
        # On Windows, they would be converted to forward slashes
        key = path_to_key("test\\subdir\\file.py")
        # The key should be in POSIX format (forward slashes)
        # But on Unix, backslashes in the input are preserved as part of filename
        if os.name == "nt":
            assert "/" in key
            assert "\\" not in key
        else:
            # On Unix, backslashes are literal characters in filename
            assert "test\\subdir\\file.py" in key

    def test_path_to_key_consistency(self):
        """Test that same path produces same key."""
        key1 = path_to_key("./test/file.py")
        key2 = path_to_key("test/file.py")
        # Both should resolve to same absolute path
        assert key1 == key2

    def test_path_to_key_with_path_object(self):
        """Test converting Path object to key."""
        path_obj = Path("test/file.py")
        key = path_to_key(path_obj)
        assert "/" in key
        assert key.endswith("test/file.py")

    def test_path_to_key_special_chars(self):
        """Test path with special characters."""
        key = path_to_key("test/file with spaces.py")
        assert "file with spaces.py" in key
        assert "/" in key


class TestToOsPath:
    """Test to_os_path function."""

    def test_to_os_path_basic(self):
        """Test converting to OS-native path."""
        os_path = to_os_path("./test")
        assert isinstance(os_path, str)
        assert os.path.isabs(os_path)

    @pytest.mark.skipif(os.name != "nt", reason="Windows-specific test")
    def test_to_os_path_windows(self):
        """Test Windows path conversion."""
        os_path = to_os_path("test/subdir")
        assert "\\" in os_path  # Windows uses backslashes

    @pytest.mark.skipif(os.name == "nt", reason="Unix-specific test")
    def test_to_os_path_unix(self):
        """Test Unix path conversion."""
        os_path = to_os_path("test/subdir")
        assert "/" in os_path  # Unix uses forward slashes

    def test_to_os_path_with_path_object(self):
        """Test converting Path object to OS path."""
        path_obj = Path("test/file.py")
        os_path = to_os_path(path_obj)
        assert isinstance(os_path, str)

    def test_to_os_path_absolute(self):
        """Test converting absolute path."""
        abs_path = "/tmp/test" if os.name != "nt" else "C:\\temp\\test"
        os_path = to_os_path(abs_path)
        assert os.path.isabs(os_path)


class TestEnsurePosixPath:
    """Test ensure_posix_path function."""

    def test_ensure_posix_basic(self):
        """Test ensuring POSIX format for basic path."""
        posix = ensure_posix_path("test/file.py")
        assert "/" in posix
        assert "\\" not in posix

    def test_ensure_posix_windows_style(self):
        """Test converting Windows-style path to POSIX."""
        posix = ensure_posix_path("test\\subdir\\file.py")
        # On Unix, backslashes are literal characters, not path separators
        if os.name == "nt":
            assert "/" in posix
            assert "\\" not in posix
            assert "test/subdir/file.py" in posix
        else:
            # On Unix, backslashes are treated as part of the filename
            assert "test\\subdir\\file.py" in posix

    def test_ensure_posix_mixed_separators(self):
        """Test path with mixed separators."""
        posix = ensure_posix_path("test/subdir\\file.py")
        # On Unix, backslashes are literal, not separators
        if os.name == "nt":
            assert "/" in posix
            assert "\\" not in posix
        else:
            # Mixed separators on Unix means backslash is part of filename
            assert "test/subdir\\file.py" in posix

    def test_ensure_posix_already_posix(self):
        """Test path already in POSIX format."""
        original = "test/subdir/file.py"
        posix = ensure_posix_path(original)
        assert posix.endswith("test/subdir/file.py")

    def test_ensure_posix_empty(self):
        """Test empty path."""
        posix = ensure_posix_path("")
        assert posix == "."

    def test_ensure_posix_absolute_windows(self):
        """Test absolute Windows path."""
        posix = ensure_posix_path("C:\\Users\\test\\file.py")
        # On Unix, this is treated as a relative path with backslashes in the name
        if os.name == "nt":
            assert "/" in posix
            assert "\\" not in posix
        else:
            # On Unix, the entire string is treated as a filename
            assert "C:\\Users\\test\\file.py" in posix


class TestPathsEqual:
    """Test paths_equal function."""

    def test_paths_equal_same_path(self):
        """Test comparing identical paths."""
        assert paths_equal("test/file.py", "test/file.py")

    def test_paths_equal_different_format(self):
        """Test comparing paths with different formats."""
        assert paths_equal("./test/file.py", "test/file.py")

    def test_paths_equal_absolute_relative(self):
        """Test comparing absolute and relative paths to same location."""
        cwd = Path.cwd()
        rel_path = "test.py"
        abs_path = cwd / "test.py"
        assert paths_equal(rel_path, abs_path)

    def test_paths_not_equal(self):
        """Test comparing different paths."""
        assert not paths_equal("test/file1.py", "test/file2.py")

    def test_paths_equal_with_path_objects(self):
        """Test comparing Path objects."""
        path1 = Path("test/file.py")
        path2 = Path("./test/file.py")
        assert paths_equal(path1, path2)

    def test_paths_equal_case_sensitive(self):
        """Test case sensitivity in path comparison."""
        # This behavior depends on the filesystem
        # On case-sensitive systems, these should be different
        if os.name != "nt":  # Unix-like systems are usually case-sensitive
            assert not paths_equal("test/File.py", "test/file.py")

    def test_paths_equal_with_symlink(self, tmp_path):
        """Test comparing paths with symlinks."""
        # Create a real file
        real_file = tmp_path / "real.txt"
        real_file.write_text("test")

        # Create a symlink
        symlink = tmp_path / "link.txt"
        symlink.symlink_to(real_file)

        # They should be equal after resolution
        assert paths_equal(real_file, symlink)

    def test_paths_equal_parent_references(self):
        """Test paths with parent directory references."""
        assert paths_equal("test/../test/file.py", "test/file.py")

    def test_paths_equal_trailing_slash(self):
        """Test paths with and without trailing slashes."""
        assert paths_equal("test/dir", "test/dir/")


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_unicode_paths(self):
        """Test paths with Unicode characters."""
        unicode_path = "test/文件.py"
        key = path_to_key(unicode_path)
        assert "文件.py" in key

        posix = ensure_posix_path(unicode_path)
        assert "文件.py" in posix

    def test_very_long_path(self):
        """Test handling of very long paths."""
        long_path = "test/" + "subdir/" * 50 + "file.py"
        key = path_to_key(long_path)
        assert key.endswith("file.py")
        assert "/" in key

    def test_path_with_dots(self):
        """Test paths with multiple dots."""
        path = "test/file..py"
        key = path_to_key(path)
        assert "file..py" in key

    def test_network_path(self):
        """Test UNC/network paths."""
        if os.name == "nt":
            network_path = "\\\\server\\share\\file.py"
            posix = ensure_posix_path(network_path)
            assert "/" in posix

    @patch("pathlib.Path.resolve")
    def test_normalize_path_error_handling(self, mock_resolve):
        """Test error handling in normalize_path."""
        mock_resolve.side_effect = OSError("Permission denied")
        # normalize_path should gracefully handle errors and fall back to absolute()
        result = normalize_path("/restricted/path")
        assert result.is_absolute()
        assert str(result).endswith("/restricted/path") or str(result) == "/restricted/path"

    def test_path_with_environment_variables(self):
        """Test paths with environment variables."""
        # Set a test environment variable
        os.environ["TEST_PATH"] = "/tmp"
        path_with_var = "$TEST_PATH/file.py"
        # Note: Path doesn't expand env vars automatically
        # This tests that we handle them as literal paths
        key = path_to_key(path_with_var)
        assert key  # Should not crash

    @pytest.mark.skipif(os.name == "nt", reason="Test causes stack overflow on Windows CI")
    def test_relative_path_from_different_cwd(self):
        """Test relative paths when CWD changes."""
        original_cwd = Path.cwd()
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                os.chdir(tmpdir)
                path1 = path_to_key("test.py")

                # Create a subdirectory and change to it
                subdir = Path(tmpdir) / "subdir"
                subdir.mkdir()
                os.chdir(subdir)
                path2 = path_to_key("../test.py")

                # Both should refer to the same file
                assert path1 == path2
        finally:
            os.chdir(original_cwd)

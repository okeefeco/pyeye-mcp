"""Path utilities for consistent cross-platform path handling.

This module provides utilities to ensure paths are handled consistently
across different operating systems. The key principle is:
- Use POSIX format (forward slashes) for internal storage and keys
- Convert to OS-native format only when interfacing with the OS
"""

from pathlib import Path


def normalize_path(path: str | Path) -> Path:
    """Normalize a path to its canonical form.

    This resolves symlinks, makes the path absolute, and handles
    platform-specific quirks like /var -> /private/var on macOS.

    Args:
        path: Path to normalize

    Returns:
        Resolved absolute Path object
    """
    return Path(path).resolve()


def path_to_key(path: str | Path) -> str:
    """Convert a path to a consistent string key.

    Uses POSIX format (forward slashes) for consistency across platforms.
    This should be used for:
    - Dictionary keys
    - Storing paths in JSON/config files
    - Comparing paths as strings

    Args:
        path: Path to convert

    Returns:
        Normalized path string in POSIX format
    """
    return normalize_path(path).as_posix()


def to_os_path(path: str | Path) -> str:
    """Convert path to OS-native string format.

    Use this when:
    - Passing paths to subprocess/external tools
    - Displaying paths to users
    - Using OS-specific APIs

    Args:
        path: Path to convert

    Returns:
        OS-native path string (backslashes on Windows, forward slashes elsewhere)
    """
    return str(normalize_path(path))


def ensure_posix_path(path_str: str) -> str:
    """Ensure a path string uses POSIX format.

    Converts any path string to use forward slashes.

    Args:
        path_str: Path string that might use backslashes

    Returns:
        Path string with forward slashes
    """
    return Path(path_str).as_posix()


def paths_equal(path1: str | Path, path2: str | Path) -> bool:
    """Check if two paths refer to the same location.

    Handles platform differences and symlinks.

    Args:
        path1: First path
        path2: Second path

    Returns:
        True if paths refer to the same location
    """
    return path_to_key(path1) == path_to_key(path2)

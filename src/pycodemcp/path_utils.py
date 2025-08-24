r"""Path utilities for consistent cross-platform path handling.

This module provides utilities to ensure paths are handled consistently
across different operating systems. The key principle is:
- Use POSIX format (forward slashes) for internal storage and keys
- Convert to OS-native format only when interfacing with the OS

Examples:
    >>> from pycodemcp.path_utils import path_to_key, ensure_posix_path

    # Store paths in dictionaries
    >>> cache = {}
    >>> file_path = Path("src/plugins/flask.py")
    >>> cache[path_to_key(file_path)] = "cached_data"

    # Compare paths safely across platforms
    >>> path1 = Path("tests\\test_file.py")  # Windows style
    >>> path2 = Path("tests/test_file.py")   # Unix style
    >>> paths_equal(path1, path2)  # True on Windows

    # Store in config/JSON (always use POSIX format)
    >>> config = {"template_dir": Path("templates/admin").as_posix()}
    >>> # config["template_dir"] is always "templates/admin" on all platforms

Common Pitfalls to Avoid:
    # ❌ WRONG - Platform-dependent
    template_name = str(template_file.relative_to(template_dir))

    # ✅ CORRECT - Platform-independent
    template_name = template_file.relative_to(template_dir).as_posix()
"""

from pathlib import Path


def normalize_path(path: str | Path) -> Path:
    """Normalize a path to its canonical form.

    This makes the path absolute and resolves "." and ".." components.
    For existing files/directories, it will also resolve symlinks.
    For non-existent paths, it normalizes the path structure without
    requiring the file to exist.

    Args:
        path: Path to normalize

    Returns:
        Normalized absolute Path object
    """
    path_obj = Path(path)

    # If path is already absolute, just resolve it normally
    if path_obj.is_absolute():
        try:
            # Try to resolve symlinks if the path exists
            return path_obj.resolve()
        except (OSError, RuntimeError):
            # If resolve fails (path doesn't exist or permission issues),
            # fall back to manual normalization
            return path_obj.absolute()
    else:
        # For relative paths, make absolute first then try to resolve
        abs_path = path_obj.absolute()
        try:
            return abs_path.resolve()
        except (OSError, RuntimeError):
            # If resolve fails, return the absolute path
            return abs_path


def path_to_key(path: str | Path) -> str:
    r"""Convert a path to a consistent string key.

    Uses POSIX format (forward slashes) for consistency across platforms.
    This should be used for:
    - Dictionary keys
    - Storing paths in JSON/config files
    - Comparing paths as strings

    Args:
        path: Path to convert

    Returns:
        Normalized path string in POSIX format

    Examples:
        >>> # Use for dictionary keys
        >>> cache = {}
        >>> cache[path_to_key("src/server.py")] = analysis_result

        >>> # Works with Path objects
        >>> cache[path_to_key(Path("src/server.py"))] = analysis_result

        >>> # Consistent across platforms
        >>> path_to_key("src\\server.py")  # Windows input
        '/absolute/path/to/src/server.py'  # POSIX output
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
    r"""Ensure a path string uses POSIX format.

    Converts any path string to use forward slashes.

    Args:
        path_str: Path string that might use backslashes

    Returns:
        Path string with forward slashes

    Examples:
        >>> # Convert Windows paths to POSIX
        >>> ensure_posix_path("templates\\admin\\index.html")
        'templates/admin/index.html'

        >>> # Already POSIX paths remain unchanged
        >>> ensure_posix_path("templates/admin/index.html")
        'templates/admin/index.html'

        >>> # Use for template names (from PR #121)
        >>> template_file = Path("templates/admin/dashboard.html")
        >>> template_dir = Path("templates")
        >>> template_name = ensure_posix_path(str(template_file.relative_to(template_dir)))
        >>> # template_name is always "admin/dashboard.html"
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

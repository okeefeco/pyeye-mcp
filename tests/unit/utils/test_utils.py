"""Utility functions for cross-platform test compatibility."""

from pathlib import Path


def normalize_path(path: str | Path) -> Path:
    """Normalize a path for cross-platform comparison.

    This handles:
    - Symlink resolution (e.g., /var -> /private/var on macOS)
    - Path separator differences
    - Case sensitivity differences

    Args:
        path: Path to normalize

    Returns:
        Resolved absolute Path object
    """
    return Path(path).resolve()


def path_to_key(path: str | Path) -> str:
    """Convert a path to a consistent string key for dictionaries.

    Uses POSIX format for consistency across platforms.

    Args:
        path: Path to convert

    Returns:
        String key in POSIX format
    """
    return normalize_path(path).as_posix()


def assert_path_equal(path1: str | Path, path2: str | Path) -> None:
    """Assert two paths are equal after normalization.

    Args:
        path1: First path to compare
        path2: Second path to compare

    Raises:
        AssertionError: If paths are not equal after normalization
    """
    key1 = path_to_key(path1)
    key2 = path_to_key(path2)
    assert key1 == key2, f"{key1} != {key2}"


def assert_path_in_list(path: str | Path, path_list: list[str | Path]) -> None:
    """Assert a path exists in a list of paths after normalization.

    Args:
        path: Path to find
        path_list: List of paths to search

    Raises:
        AssertionError: If path not found in list after normalization
    """
    normalized_path = path_to_key(path)
    normalized_list = [path_to_key(p) for p in path_list]
    assert normalized_path in normalized_list, f"{normalized_path} not in {normalized_list}"


def paths_equal(path1: str | Path, path2: str | Path) -> bool:
    """Check if two paths are equal after normalization.

    Args:
        path1: First path to compare
        path2: Second path to compare

    Returns:
        True if paths are equal after normalization
    """
    return path_to_key(path1) == path_to_key(path2)


def normalize_path_list(paths: list[str | Path]) -> list[str]:
    """Normalize a list of paths to POSIX string keys.

    Args:
        paths: List of paths to normalize

    Returns:
        List of normalized path strings in POSIX format
    """
    return [path_to_key(p) for p in paths]


def assert_paths_equal_unordered(paths1: list[str | Path], paths2: list[str | Path]) -> None:
    """Assert two lists of paths contain the same paths (order-independent).

    Args:
        paths1: First list of paths
        paths2: Second list of paths

    Raises:
        AssertionError: If lists don't contain the same paths
    """
    normalized1 = set(normalize_path_list(paths1))
    normalized2 = set(normalize_path_list(paths2))
    assert normalized1 == normalized2, (
        f"Path sets differ:\nExtra in first: {normalized1 - normalized2}\n"
        f"Extra in second: {normalized2 - normalized1}"
    )


def to_os_path(path: str | Path) -> str:
    """Convert path to OS-native string format.

    Use this when passing paths to OS-specific APIs or external tools.

    Args:
        path: Path to convert

    Returns:
        OS-native path string
    """
    return str(normalize_path(path))


def assert_dict_has_path_key(dictionary: dict, path: str | Path, use_posix: bool = True) -> None:
    """Assert a dictionary contains a path as a key.

    Args:
        dictionary: Dictionary to check
        path: Path to look for
        use_posix: Whether to normalize to POSIX format

    Raises:
        AssertionError: If path key not found
    """
    key = path_to_key(path) if use_posix else str(normalize_path(path))

    assert key in dictionary, f"Key {key} not found in {list(dictionary.keys())}"

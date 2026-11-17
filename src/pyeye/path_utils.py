r"""Path utilities for consistent cross-platform path handling.

This module provides utilities to ensure paths are handled consistently
across different operating systems. The key principle is:
- Use POSIX format (forward slashes) for internal storage and keys
- Convert to OS-native format only when interfacing with the OS

Examples:
    >>> from pyeye.path_utils import path_to_key, ensure_posix_path

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

import os
from collections.abc import Iterable
from pathlib import Path, PurePath
from typing import Any, TypeVar


def dedupe_paths(paths: Iterable[str | Path], *, resolve_output: bool = False) -> list[Path]:
    """Dedupe *paths* by resolved identity, preserving first-seen order.

    Each path is keyed by ``Path(p).resolve().as_posix()`` so symlinked/relative
    duplicates collapse to one; paths that cannot be resolved (``OSError`` for a
    bad/looping path, ``ValueError`` for an embedded NUL byte) are skipped rather
    than raising.  Order follows the input — the first occurrence of each resolved
    identity wins (the highest-precedence root, for sys.path-style root lists).

    Args:
        paths: The paths to dedupe, in precedence order.
        resolve_output: When ``True`` the returned paths are the **resolved**
            forms (stable for ``==`` comparison — e.g. matching a resolved
            parent dir against project roots); when ``False`` the **original**
            ``Path`` objects are returned (preserving caller-facing paths, e.g.
            the unresolved roots scanned by the submodules enumerator).

    Returns:
        The deduped paths in first-seen order.
    """
    out: list[Path] = []
    seen: set[str] = set()
    for raw in paths:
        path = Path(raw)
        # Reject NUL explicitly: on Windows with Python 3.13, resolve() returns
        # for such a path instead of raising ValueError (#529).
        if "\x00" in path.as_posix():
            continue
        try:
            resolved = path.resolve()
        except (OSError, ValueError):
            continue
        key = resolved.as_posix()
        if key in seen:
            continue
        seen.add(key)
        out.append(resolved if resolve_output else path)
    return out


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


def relative_within(path: str | Path, parent: str | Path) -> Path | None:
    """*path* relative to *parent* if it lies inside it, else ``None`` (#714).

    Tries the two paths as spelled first, then their resolved forms, so a file
    reached through a symlinked or differently-spelled root (macOS
    ``/var`` -> ``/private/var``, a Windows 8.3 short name) still counts as
    inside. Callers keep their own spelling for display (#603); only the
    comparison resolves.

    A lexical result containing ``..`` (``root/../other/x.py``) is never
    "inside" (#668). The resolved comparison then decides.
    """
    candidate, root = Path(path), Path(parent)
    try:
        rel = candidate.relative_to(root)
    except ValueError:
        pass
    else:
        if ".." not in rel.parts:
            return rel
    try:
        rel = normalize_path(candidate).relative_to(normalize_path(root))
    except (ValueError, OSError):
        return None
    return rel if ".." not in rel.parts else None


def absolute_path(path: str | Path) -> Path:
    """*path* made absolute in the caller's spelling: no symlink resolution (#717).

    ``..`` segments are collapsed lexically and the working directory is
    prepended to a relative path, but a symlinked or short-name spelling is
    kept. This is the form to hand back to an agent, which compares it with its
    own paths (#603). Use :func:`normalize_path` to compare.
    """
    return Path(os.path.abspath(path))


_P = TypeVar("_P", bound=PurePath)


def anchor(path: str | Path, root: str | Path) -> Path:
    """*path* as the caller meant it: relative to *root*, never to the server's cwd (#842, #843).

    An absolute *path* is returned exactly as given. A relative one is joined to
    *root* and made absolute with :func:`absolute_path` (``..`` collapsed
    lexically, the caller's spelling kept, no symlink resolution, #714/#603).

    ``~`` is not expanded: this anchors a file or scope path an agent passes to
    a tool, which is not a config entry (``ProjectConfig`` expands ``~`` there).

    A Windows drive-relative path (``C:foo``) is relative to that drive's cwd,
    which is the same server-cwd trap: on *root*'s drive its drive is dropped
    and it joins *root*; on another drive it is rejected (:func:`drive_relative`).

    Raises:
        ValueError: For a drive-relative path on a drive other than *root*'s.
    """
    candidate = drive_relative(Path(path), Path(root))
    if candidate.is_absolute():
        return candidate
    return absolute_path(Path(root) / candidate)


def drive_relative(path: _P, root: PurePath) -> _P:
    """*path* without a drive-relative prefix (``C:foo`` -> ``foo``) that matches *root*'s drive.

    Pure, so it is testable with :class:`~pathlib.PureWindowsPath` anywhere.
    Any other path is returned unchanged (on POSIX a path never has a drive).

    Raises:
        ValueError: If *path* is drive-relative on a drive other than *root*'s:
            it can't be relative to *root*, and resolving it against that
            drive's cwd would depend on the server process.
    """
    if not path.drive or path.is_absolute():
        return path
    if path.drive.lower() != root.drive.lower():
        raise ValueError(
            f"{path.as_posix()!r} is relative to drive {path.drive}'s current directory, "
            f"not to the project on {root.drive or 'no drive'}: pass an absolute path "
            "or one relative to project_path"
        )
    return type(path)(*path.parts[1:])


#: Response keys whose string value is a file path, and keys holding lists of
#: file paths (``tests/test_mcp_path_boundary.py`` sweeps the tools for these).
_FILE_KEYS = frozenset({"file"})
_FILE_LIST_KEYS = frozenset({"unresolved_importers", "unparseable_files"})


def respell_under(file: str, roots: Iterable[str | Path]) -> str:
    """*file* re-spelled under the first of *roots* that contains it, POSIX (#717).

    Jedi reports files resolved, so under a symlinked root a location comes back
    as ``/real/...`` while the agent opened ``/link/...``. The containment test
    resolves both sides (:func:`relative_within`), and the answer is joined onto
    the root as the caller spelled it. A file under no root is returned as
    given, in POSIX form.

    A relative *file* is the caller's own input echoed back (a not-found
    ``file``), relative to their project: it is returned as given. Testing it
    would resolve it against the server's cwd, which can lie inside a root and
    give a wrong absolute path (#852 review).
    """
    if not Path(file).is_absolute():
        return Path(file).as_posix()
    for root in roots:
        rel = relative_within(file, root)
        if rel is not None:
            return (Path(root) / rel).as_posix()
    return Path(file).as_posix()


def respell_paths(obj: Any, roots: list[Path]) -> Any:
    """A copy of *obj* with every file path re-spelled under *roots* (:func:`respell_under`).

    Walks dicts and lists; rewrites ``file`` values and ``unresolved_importers``
    entries. Everything else is returned unchanged.
    """
    if isinstance(obj, dict):
        out: dict[Any, Any] = {}
        for key, value in obj.items():
            if key in _FILE_KEYS and isinstance(value, str):
                out[key] = respell_under(value, roots)
            elif key in _FILE_LIST_KEYS and isinstance(value, list):
                out[key] = [respell_under(v, roots) if isinstance(v, str) else v for v in value]
            else:
                out[key] = respell_paths(value, roots)
        return out
    if isinstance(obj, list):
        return [respell_paths(v, roots) for v in obj]
    return obj


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

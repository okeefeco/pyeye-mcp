"""Async file operations utilities for non-blocking I/O."""

import asyncio
import logging
import os
import re
from collections.abc import Iterator
from pathlib import Path, PurePosixPath

import aiofiles

from .path_utils import normalize_path, path_to_key, relative_within
from .validation import restricted_dir

logger = logging.getLogger(__name__)


async def read_file_async(path: Path) -> str:
    """Read file contents asynchronously.

    Args:
        path: Path to the file to read

    Returns:
        File contents as string

    Raises:
        FileNotFoundError: If file doesn't exist
        IOError: If file cannot be read
    """
    async with aiofiles.open(path, encoding="utf-8") as f:
        content: str = await f.read()
        return content


_GITDIR_PREFIX = "gitdir:"


def _gitdir_pointer(directory: Path) -> Path | None:
    """Return the gitdir a ``.git`` *file* points at, or ``None``.

    Both linked worktrees and submodules replace ``.git`` with a file holding
    ``gitdir: <path>``; the path may be relative to ``directory``.
    """
    dot_git = directory / ".git"
    try:
        if not dot_git.is_file():
            return None
        pointer = dot_git.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    if not pointer.startswith(_GITDIR_PREFIX):
        return None
    target = Path(pointer[len(_GITDIR_PREFIX) :].strip())
    if not target.name:
        return None
    return target if target.is_absolute() else directory / target


#: A ``path = <dir>`` line of a ``.gitmodules`` file (git-config syntax).
_GITMODULES_PATH = re.compile(r"^\s*path\s*=\s*(.+?)\s*$")


def _declared_submodules(directory: Path) -> set[str]:
    """``path_to_key`` of every submodule path that ``directory/.gitmodules`` declares.

    The file is read as text: no git dependency, and an unreadable or absent
    file declares nothing. A quoted value (``path = "a b"``) is unquoted.
    """
    try:
        text = (directory / ".gitmodules").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    declared: set[str] = set()
    for line in text.splitlines():
        match = _GITMODULES_PATH.match(line)
        if match:
            value = match.group(1)
            if len(value) >= 2 and value[0] == value[-1] == '"':
                value = value[1:-1]
            declared.add(path_to_key(directory / value))
    return declared


def _is_nested_repo(directory: Path, declared_submodules: set[str]) -> bool:
    """Whether ``directory`` is an independent nested git repository (#810).

    Its ``.git`` is a **directory** (a clone, not a pointer file) and no
    ``.gitmodules`` declares it as a submodule. A submodule written by git
    1.7.8 or later has a ``.git`` *file* and is never matched here; an older
    one with a ``.git`` directory is kept by its ``.gitmodules`` entry. A
    linked worktree also has a ``.git`` file and is :func:`_is_linked_worktree`'s.
    """
    try:
        if not (directory / ".git").is_dir():
            return False
    except OSError:
        return False
    return path_to_key(directory) not in declared_submodules


def _is_linked_worktree(directory: Path) -> bool:
    """Whether ``directory`` is the root of a linked git worktree (#507).

    A linked worktree duplicates the tree it was created from, so indexing one
    gives every project symbol a second definition site. A **submodule** has
    the same kind of ``.git`` pointer file but is a distinct project whose
    source the parent often imports, so the two must be told apart.

    git's own structural distinction is used: a linked worktree's gitdir
    (``<common-dir>/worktrees/<name>``) holds a ``commondir`` back-pointer to
    the shared repository, while a submodule's gitdir
    (``<super>/.git/modules/<name>``) is a full standalone repository and has
    none. Path shape is *not* used to decide this — a submodule checked out at
    ``worktrees/lib`` has ``worktrees`` in its gitdir path too.

    Only when the gitdir is missing entirely — ``git worktree prune`` deletes
    it but leaves the checkout on disk, still a full duplicate tree — does the
    pointer's layout decide, since nothing is left to inspect.
    """
    target = _gitdir_pointer(directory)
    if target is None:
        return False
    try:
        if (target / "commondir").is_file():
            return True
        if target.exists():
            return False
    except OSError:
        return False
    return target.parent.name == "worktrees"


def pruned_walk(path: Path) -> Iterator[tuple[Path, list[str], list[str]]]:
    """``os.walk(path)`` that never enters a restricted directory (#856 ruling).

    The ONE directory walk: every recursive scan goes through it, so a route
    the input checks miss (a symlinked parent, a new scope form) still can't
    descend into ``/etc`` and the like. Each directory is judged by its
    RESOLVED form: *path* is resolved once, and a directory below it resolves
    to that plus its relative path, since ``os.walk`` never follows a symlinked
    subdirectory. A restricted *path* yields nothing.

    Entries are judged too, so a scan never reads a restricted target through a
    link: a symlinked FILE or directory is judged by what it points at, and one
    that resolves into a restricted location (``x.py`` -> ``~/.netrc``) is
    dropped from ``filenames`` / ``dirnames`` (#909 review).

    Yields ``(dir, dirnames, filenames)`` as ``os.walk`` does; a caller may
    prune ``dirnames`` in place, and the walk honours it.
    """
    try:
        real_root = normalize_path(path)
    except (OSError, RuntimeError):
        return
    if restricted_dir(real_root):
        logger.warning(f"Not walking {path.as_posix()}: it resolves into a restricted location")
        return
    real_of: dict[str, Path] = {}
    for dirpath, dirnames, filenames in os.walk(path):
        real_here = real_of.pop(dirpath, real_root)
        dirnames[:] = [
            d for d in dirnames if not restricted_dir(_entry_target(dirpath, d, real_here))
        ]
        for d in dirnames:
            real_of[os.path.join(dirpath, d)] = real_here / d
        filenames[:] = [
            f for f in filenames if not restricted_dir(_entry_target(dirpath, f, real_here))
        ]
        yield Path(dirpath), dirnames, filenames


def _entry_target(dirpath: str, name: str, real_here: Path) -> Path:
    """Where entry *name* of *dirpath* really is: a symlink's target, else *real_here*/*name*."""
    entry = os.path.join(dirpath, name)
    if os.path.islink(entry):
        try:
            return normalize_path(entry)
        except (OSError, RuntimeError):
            pass  # a broken or looping link: judged where it sits
    return real_here / name


def pruned_rglob(pattern: str, path: Path) -> list[Path]:
    """``rglob``-style matching over :func:`pruned_walk`: no restricted directory is entered.

    For the walks that must NOT apply the project-scan exclusions (a venv's
    ``site-packages``, a framework's ``templates`` tree); a project scan uses
    :func:`filtered_rglob`.
    """
    return [
        here / name
        for here, dirnames, filenames in pruned_walk(path)
        for name in (*dirnames, *filenames)
        if _tail_matches(here / name, path, (pattern,))
    ]


#: One glob pattern, or several matched in the same walk (#933).
Patterns = str | tuple[str, ...]


def _tail_matches(candidate: Path, path: Path, patterns: tuple[str, ...]) -> bool:
    """``rglob`` semantics: any of *patterns* matches *candidate*'s tail below *path*."""
    below = relative_within(candidate, path)
    if below is None:
        return False
    tail = PurePosixPath(below.as_posix())
    return any(tail.match(p) for p in patterns)


def filtered_rglob(pattern: Patterns, path: Path) -> list[Path]:
    """Recursively glob under *path*, excluding non-project directories (#507, #517).

    The ONE home of the project-scan exclusion rule: :func:`rglob_async` and
    every whole-tree scan (the framework plugins) call it, so none of them can
    walk into a nested worktree or ``.venv`` on its own.

    Three exclusion rules apply:

    1. **Name-based** — any path component *below* ``path`` in
       ``EXCLUDED_DIRS`` (virtual envs, caches, build artifacts). Components of
       ``path`` itself and its ancestors are never tested, so a project that
       lives under e.g. ``~/dev/build/`` scans normally (#515).
    2. **Nested checkouts** (#507) — any directory *strictly below* ``path``
       that is a linked git worktree root. A linked worktree is a duplicate of
       the tree it was created from, so scanning one gives every project symbol
       a second definition site, possibly on another branch or mid-edit.
    3. **Nested independent repositories** (#810) — any directory *strictly
       below* ``path`` whose ``.git`` is a directory (a clone, vendored or
       provisioned, e.g. ``.scenario-repos/django``), unless a ``.gitmodules``
       in a directory walked so far, or in ``path`` or one of its ancestors,
       declares it as a submodule. A clone is another project; a user who
       wants one indexed adds it with ``configure_packages``, which scans it
       from its own root, where this rule never applies.

    A directory is a linked worktree when its ``.git`` is a **file** holding a
    ``gitdir:`` pointer *and* that gitdir is git's linked-worktree kind — see
    :func:`_is_linked_worktree`. Submodules also have a ``.git`` file (they
    point at ``<super>/.git/modules/<name>``) and are deliberately still
    scanned: their source is frequently imported by the parent project.
    ``path`` itself is never tested, so scanning from *inside* a worktree works
    normally.

    Args:
        pattern: Glob pattern, or a tuple of them matched in ONE walk: listing
            ``.py`` and ``.pyi`` with two calls walks the tree twice (#933).
        path: Base path to search in

    Returns:
        List of matching paths (excludes .venv, __pycache__, .git, nested
        worktrees, nested independent clones, etc.)
    """
    patterns = (pattern,) if isinstance(pattern, str) else pattern
    from .constants import EXCLUDED_DIRS

    def _excluded(name: str) -> bool:
        return name in EXCLUDED_DIRS or name.endswith(".egg-info")

    # Excluded directories are PRUNED, never descended into (#738): on a repo
    # with a ``.venv`` that is ~30x cheaper than walking everything and
    # filtering after, with the same result. Only names BELOW the scan root are
    # tested, so an ancestor named e.g. ``build`` doesn't exclude the project
    # (#515); ``path`` itself is never tested as a worktree.
    results: list[Path] = []
    # Submodules declared by a superproject above the scan root, or at it (#810).
    declared: set[str] = set()
    for ancestor in (path, *path.parents):
        declared |= _declared_submodules(ancestor)
    for here, dirnames, filenames in pruned_walk(path):
        if here != path and ".gitmodules" in filenames:
            declared |= _declared_submodules(here)  # a nested superproject's own
        dirnames[:] = [
            d
            for d in dirnames
            if not _excluded(d)
            and not _is_linked_worktree(here / d)
            and not _is_nested_repo(here / d, declared)
        ]
        for name in (*dirnames, *filenames):
            if not _excluded(name) and _tail_matches(here / name, path, patterns):
                results.append(here / name)
    return results


async def rglob_async(pattern: Patterns, path: Path) -> list[Path]:
    """:func:`filtered_rglob` on a worker thread.

    Args:
        pattern: Glob pattern
        path: Base path to search in

    Returns:
        The matching paths, with the :func:`filtered_rglob` exclusions applied.
    """
    return await asyncio.to_thread(filtered_rglob, pattern, path)

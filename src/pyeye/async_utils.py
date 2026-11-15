"""Async file operations utilities for non-blocking I/O."""

import asyncio
import logging
from pathlib import Path

import aiofiles

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


async def rglob_async(pattern: str, path: Path) -> list[Path]:
    """Recursively glob files asynchronously, excluding non-project directories.

    Two exclusion rules apply:

    1. **Name-based** — any path component *below* ``path`` in
       ``EXCLUDED_DIRS`` (virtual envs, caches, build artifacts). Components of
       ``path`` itself and its ancestors are never tested, so a project that
       lives under e.g. ``~/dev/build/`` scans normally (#515).
    2. **Nested checkouts** (#507) — any directory *strictly below* ``path``
       that is a linked git worktree root. A linked worktree is a duplicate of
       the tree it was created from, so scanning one gives every project symbol
       a second definition site, possibly on another branch or mid-edit.

    A directory is a linked worktree when its ``.git`` is a **file** holding a
    ``gitdir:`` pointer *and* that gitdir is git's linked-worktree kind — see
    :func:`_is_linked_worktree`. Submodules also have a ``.git`` file (they
    point at ``<super>/.git/modules/<name>``) and are deliberately still
    scanned: their source is frequently imported by the parent project.
    ``path`` itself is never tested, so scanning from *inside* a worktree works
    normally.

    Args:
        pattern: Glob pattern
        path: Base path to search in

    Returns:
        List of matching paths (excludes .venv, __pycache__, .git, nested
        worktrees, etc.)
    """
    from .constants import EXCLUDED_DIRS

    def _filtered_rglob() -> list[Path]:
        # A single scan revisits the same ancestor directories thousands of
        # times; probe each one once.
        is_worktree_root: dict[Path, bool] = {}

        def _under_nested_worktree(candidate: Path) -> bool:
            for parent in candidate.parents:
                if parent == path:
                    return False
                cached = is_worktree_root.get(parent)
                if cached is None:
                    cached = _is_linked_worktree(parent)
                    is_worktree_root[parent] = cached
                if cached:
                    return True
            return False

        results = []
        for p in path.rglob(pattern):
            # Test only components below the scan root: an ancestor named e.g.
            # ``build`` must not exclude the whole project (#515).
            rel_parts = p.relative_to(path).parts
            if any(part in EXCLUDED_DIRS or part.endswith(".egg-info") for part in rel_parts):
                continue
            if _under_nested_worktree(p):
                continue
            results.append(p)
        return results

    return await asyncio.to_thread(_filtered_rglob)

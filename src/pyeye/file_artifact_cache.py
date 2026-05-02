"""File artifact cache for shared source text, AST, and jedi.Script objects.

This module provides a process-level cache keyed by ``(resolved_path, mtime_ns)``
(and additionally by project path for Script objects).  It serves as the
foundation of the lookup-performance overhaul (Task 1.2).

Key design decisions
--------------------
* **Two independent eviction policies**: a *byte cap* on source-text entries
  and an *LRU count cap* on AST/Script entries.  They operate independently
  on their own ``OrderedDict`` stores.
* **mtime-based invalidation**: every ``get_*`` call checks ``os.stat()`` for
  the current mtime and treats a changed mtime as a cache miss.
* **Thread safety**: a single ``threading.RLock`` guards all mutations, making
  the cache safe when watchdog callbacks fire from a background thread and
  asyncio tasks run ``get_*`` calls concurrently via ``run_in_executor``.
* **Project-keyed Scripts**: ``get_script`` keys on ``(path, mtime_ns,
  project_path)`` rather than ``id(project)`` so two distinct
  ``jedi.Project`` instances rooted at the same directory correctly share an
  entry.
* **Parso composition**: ``jedi.Script`` internally calls parso, which keeps
  its own in-memory parse cache keyed by file path with mtime-based
  invalidation.  We cache the already-constructed ``jedi.Script`` object
  (whose setup overhead exceeds the parse step alone) and let parso's cache
  handle the underlying parse tree.  We never fight parso's cache; we benefit
  from it.
* **AST-biased LRU eviction**: when both the AST store and Script store are
  non-empty and the combined count cap is exceeded, the implementation evicts
  from the AST store first.  This is intentional: ``jedi.Script`` objects are
  more expensive to reconstruct than ASTs because Script setup involves
  inference-state initialisation, not just a parso parse.  Keeping Scripts
  warm and re-parsing ASTs via parso's own cache is a better trade-off under
  memory pressure.  See ``_enforce_ast_cap`` for details.
* **UTF-8 assumption**: source files are read with ``encoding="utf-8"``.
  Non-UTF-8 files (e.g. PEP 263 ``# -*- coding: latin-1 -*-``) are not
  supported.  Modern Python 3 codebases are overwhelmingly UTF-8; adding
  general encoding detection would add complexity better deferred to a
  dedicated issue.
"""

from __future__ import annotations

import ast
import logging
import os
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any

import jedi

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

# Key for the source/AST stores: (resolved_posix_path, mtime_ns)
_FileKey = tuple[str, int]

# Key for Script store: (resolved_posix_path, mtime_ns, project_posix_path)
_ScriptKey = tuple[str, int, str]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _stat_mtime_ns(path: Path) -> int:
    """Return nanosecond mtime for *path* via ``os.stat``."""
    return os.stat(path).st_mtime_ns


def _resolve_posix(path: Path | str) -> str:
    """Return the canonical, POSIX-format absolute path string for *path*."""
    return Path(path).resolve().as_posix()


def _project_key(project: jedi.Project) -> str:
    """Return a stable string key for *project*, derived from its root path."""
    return Path(project.path).resolve().as_posix()


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------


class FileArtifactCache:
    """Process-level cache for file source text, AST, and jedi.Script objects.

    Instances are fully independent; tests construct them with custom caps.
    A module-level singleton ``_default_cache`` is provided for production use.

    Parameters
    ----------
    ast_max_entries:
        Maximum number of AST **and** Script entries combined.  When exceeded,
        the least-recently-used entry is evicted.  Defaults to 500.
    file_max_bytes:
        Maximum total byte size of cached source text.  When adding a new
        source entry would exceed this cap, the least-recently-used source
        entry is evicted until the total fits.  Defaults to 100 MB.
    """

    def __init__(
        self,
        ast_max_entries: int = 500,
        file_max_bytes: int = 100_000_000,
    ) -> None:
        """Initialise the cache with the given entry and byte caps."""
        self._ast_max_entries = ast_max_entries
        self._file_max_bytes = file_max_bytes

        # Source store: _FileKey -> str
        # Ordered by LRU (most-recently used at the end).
        self._source_store: OrderedDict[_FileKey, str] = OrderedDict()
        # Byte count per source entry for the cap calculation.
        self._source_bytes: dict[_FileKey, int] = {}
        self._total_source_bytes: int = 0

        # AST store: _FileKey -> ast.Module (LRU, shared count cap with Script)
        self._ast_store: OrderedDict[_FileKey, ast.Module] = OrderedDict()

        # Script store: _ScriptKey -> jedi.Script (LRU, shared count cap)
        self._script_store: OrderedDict[_ScriptKey, jedi.Script] = OrderedDict()

        # Stats counters
        self._hits: int = 0
        self._misses: int = 0
        self._evictions: int = 0

        # Single re-entrant lock guards all mutations
        self._lock = threading.RLock()

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def get_source(self, path: Path | str) -> str:
        """Return the source text of *path*, reading from disk on cache miss.

        The cache is keyed by ``(resolved_path, mtime_ns)``; a changed mtime
        forces a fresh disk read and updates the cached entry.

        .. note::
            Files are read with ``encoding="utf-8"``.  Non-UTF-8 source files
            (PEP 263 ``# -*- coding: latin-1 -*-`` etc.) are not supported and
            will raise ``UnicodeDecodeError``.  When that error is raised after
            ``_misses`` has already been incremented, the miss counter has no
            corresponding cache entry — this is correct because the operation
            truly was a cache miss that subsequently failed.

        Parameters
        ----------
        path:
            Path to a Python source file.

        Returns
        -------
        str
            Source text of the file.
        """
        resolved = _resolve_posix(path)
        mtime_ns = _stat_mtime_ns(Path(path))
        key: _FileKey = (resolved, mtime_ns)

        with self._lock:
            if key in self._source_store:
                # Cache hit — move to MRU position
                self._source_store.move_to_end(key)
                self._hits += 1
                return self._source_store[key]

            # Cache miss — evict any stale entry for this path (different mtime)
            self._evict_stale_source(resolved, key)

            # Read from disk
            self._misses += 1
            source = Path(path).read_text(encoding="utf-8")

            # Insert, then enforce byte cap
            byte_size = len(source.encode("utf-8"))
            self._source_store[key] = source
            self._source_bytes[key] = byte_size
            self._total_source_bytes += byte_size
            self._enforce_byte_cap()

            return source

    def get_ast(self, path: Path | str) -> ast.Module:
        """Return the parsed AST for *path*, rebuilding on cache miss or mtime change.

        Shares the LRU count cap with :meth:`get_script`.

        Parameters
        ----------
        path:
            Path to a Python source file.

        Returns
        -------
        ast.Module
            Parsed abstract syntax tree.
        """
        resolved = _resolve_posix(path)
        mtime_ns = _stat_mtime_ns(Path(path))
        key: _FileKey = (resolved, mtime_ns)

        with self._lock:
            if key in self._ast_store:
                self._ast_store.move_to_end(key)
                self._hits += 1
                return self._ast_store[key]

            # Evict any stale AST for this path
            self._evict_stale_ast(resolved, key)

            self._misses += 1
            # Obtain source (benefits from or populates the source cache)
            source = self.get_source(path)

            tree = ast.parse(source, filename=resolved)
            self._ast_store[key] = tree
            self._enforce_ast_cap()

            return tree

    def get_script(self, path: Path | str, project: jedi.Project) -> jedi.Script:
        """Return a ``jedi.Script`` for *path* under *project*, caching by project path.

        The cache key is ``(resolved_path, mtime_ns, project_root_path)`` so
        two distinct ``jedi.Project`` instances rooted at the same directory
        share a cached entry, while projects at different roots do not.

        Parameters
        ----------
        path:
            Path to a Python source file.
        project:
            ``jedi.Project`` instance that provides import resolution context.

        Returns
        -------
        jedi.Script
            Constructed jedi Script object.
        """
        resolved = _resolve_posix(path)
        mtime_ns = _stat_mtime_ns(Path(path))
        proj_key = _project_key(project)
        key: _ScriptKey = (resolved, mtime_ns, proj_key)

        with self._lock:
            if key in self._script_store:
                self._script_store.move_to_end(key)
                self._hits += 1
                return self._script_store[key]

            # Evict any stale Scripts for this (path, project) combination
            self._evict_stale_script(resolved, proj_key, key)

            self._misses += 1
            source = self.get_source(path)

            script = jedi.Script(code=source, path=Path(path), project=project)
            self._script_store[key] = script
            self._enforce_ast_cap()

            return script

    def invalidate(self, path: Path | str) -> None:
        """Evict all cached entries for *path*.

        Safe to call on a path that has no cached entries.

        Parameters
        ----------
        path:
            Path whose entries should be dropped from the cache.
        """
        resolved = _resolve_posix(path)
        with self._lock:
            self._evict_all_for_resolved(resolved)

    def invalidate_all(self) -> None:
        """Clear the entire cache.

        ``stats()["evictions"]`` is incremented by the total number of items
        cleared, matching the per-item semantics of :meth:`invalidate`.
        """
        with self._lock:
            cleared = len(self._source_store) + len(self._ast_store) + len(self._script_store)
            self._evictions += cleared
            self._source_store.clear()
            self._source_bytes.clear()
            self._total_source_bytes = 0
            self._ast_store.clear()
            self._script_store.clear()

    def stats(self) -> dict[str, Any]:
        """Return a snapshot of cache statistics.

        Returns
        -------
        dict
            Keys: ``hits``, ``misses``, ``evictions``, ``cached_bytes``.
        """
        with self._lock:
            return {
                "hits": self._hits,
                "misses": self._misses,
                "evictions": self._evictions,
                "cached_bytes": self._total_source_bytes,
            }

    # -----------------------------------------------------------------------
    # Internal helpers — must be called with _lock held
    # -----------------------------------------------------------------------

    def _evict_stale_source(self, resolved: str, current_key: _FileKey) -> None:
        """Remove source entries for *resolved* whose mtime differs from *current_key*."""
        stale = [k for k in self._source_store if k[0] == resolved and k != current_key]
        for k in stale:
            self._remove_source_entry(k)

    def _evict_stale_ast(self, resolved: str, current_key: _FileKey) -> None:
        """Remove AST entries for *resolved* whose mtime differs from *current_key*."""
        stale = [k for k in self._ast_store if k[0] == resolved and k != current_key]
        for k in stale:
            del self._ast_store[k]
            self._evictions += 1

    def _evict_stale_script(self, resolved: str, proj_key: str, current_key: _ScriptKey) -> None:
        """Remove Script entries for *(resolved, proj_key)* that are stale."""
        stale = [
            k
            for k in self._script_store
            if k[0] == resolved and k[2] == proj_key and k != current_key
        ]
        for k in stale:
            del self._script_store[k]
            self._evictions += 1

    def _evict_all_for_resolved(self, resolved: str) -> None:
        """Remove all cached entries (source, AST, Script) for *resolved*."""
        src_stale = [k for k in self._source_store if k[0] == resolved]
        for k in src_stale:
            self._remove_source_entry(k)

        ast_stale = [k for k in self._ast_store if k[0] == resolved]
        for k in ast_stale:
            del self._ast_store[k]
            self._evictions += 1

        script_stale: list[_ScriptKey] = [k for k in self._script_store if k[0] == resolved]
        for sk in script_stale:
            del self._script_store[sk]
            self._evictions += 1

    def _remove_source_entry(self, key: _FileKey) -> None:
        """Remove a single source entry and update byte accounting."""
        byte_size = self._source_bytes.pop(key, 0)
        self._total_source_bytes -= byte_size
        del self._source_store[key]
        self._evictions += 1

    def _enforce_byte_cap(self) -> None:
        """Evict LRU source entries until total cached bytes <= _file_max_bytes."""
        while self._total_source_bytes > self._file_max_bytes and self._source_store:
            # OrderedDict pops from the front (LRU end)
            lru_key, _ = next(iter(self._source_store.items()))
            self._remove_source_entry(lru_key)

    def _enforce_ast_cap(self) -> None:
        """Evict LRU AST/Script entries (combined) until total count <= _ast_max_entries.

        AST and Script entries share the same count cap.  When the combined
        count exceeds the cap we evict the globally-least-recently-used entry
        across both stores.
        """
        while (len(self._ast_store) + len(self._script_store)) > self._ast_max_entries:
            # Determine which store has the globally oldest entry.
            # OrderedDict preserves insertion/access order; first element is LRU.
            ast_lru = next(iter(self._ast_store), None)
            script_lru = next(iter(self._script_store), None)

            if ast_lru is not None and script_lru is None:
                del self._ast_store[ast_lru]
                self._evictions += 1
            elif script_lru is not None and ast_lru is None:
                del self._script_store[script_lru]
                self._evictions += 1
            else:
                # Both stores have entries.  Evict from the AST store first.
                #
                # Rationale: ``jedi.Script`` objects are more expensive to
                # reconstruct than ASTs because Script setup involves
                # inference-state initialisation, not just a parso parse call.
                # parso keeps its own in-memory parse cache keyed by file path
                # with mtime-based invalidation, so evicted ASTs are cheap to
                # rebuild.  Under cap pressure it is therefore better to keep
                # Scripts warm and let ASTs be re-parsed via parso's cache.
                del self._ast_store[ast_lru]  # type: ignore[arg-type]
                self._evictions += 1


# ---------------------------------------------------------------------------
# Module-level singleton for production use
# ---------------------------------------------------------------------------

# Default process-global cache instance.
# Most callers should use the module-level functions below which delegate to
# this singleton.  Tests should construct their own ``FileArtifactCache``
# instances with custom caps.
_default_cache: FileArtifactCache = FileArtifactCache()


def get_source(path: Path | str) -> str:
    """Return cached source text for *path* using the default cache."""
    return _default_cache.get_source(path)


def get_ast(path: Path | str) -> ast.Module:
    """Return cached AST for *path* using the default cache."""
    return _default_cache.get_ast(path)


def get_script(path: Path | str, project: jedi.Project) -> jedi.Script:
    """Return cached jedi.Script for *path* under *project* using the default cache."""
    return _default_cache.get_script(path, project)


def invalidate(path: Path | str) -> None:
    """Invalidate cached entries for *path* in the default cache."""
    _default_cache.invalidate(path)


def invalidate_all() -> None:
    """Invalidate all entries in the default cache."""
    _default_cache.invalidate_all()


def stats() -> dict[str, Any]:
    """Return stats from the default cache."""
    return _default_cache.stats()

"""File artifact cache for shared AST and ``jedi.Script`` objects.

This module provides a process-level cache keyed by ``(resolved_path, (mtime_ns, size))``
(and additionally by project path for Script objects).  It serves as the
foundation of the lookup-performance overhaul (Task 1.2 / 1.5).

Layering principle
------------------
Pyeye is the *semantic* layer.  Source text is *content* that the agent reads
through its dedicated Read tool.  The cache therefore holds **only**
``ast.Module`` and ``jedi.Script`` objects — never raw source text.  When a
miss occurs, source is read from disk inline for the parse / Script
construction step and immediately discarded.  Source bytes never escape the
cache boundary.

Key design decisions
--------------------
* **Single LRU count cap** on AST/Script entries (combined).  Defaults to 500.
* **Version-based invalidation**: every ``get_*`` call checks ``os.stat()`` for
  the current ``(mtime_ns, size)`` and treats any change as a cache miss. The
  size catches a rewrite inside the filesystem's mtime resolution (#731); a
  same-size rewrite inside that window is still a hit.
* **Thread safety**: a single ``threading.RLock`` guards all mutations, making
  the cache safe when watchdog callbacks fire from a background thread and
  asyncio tasks run ``get_*`` calls concurrently via ``run_in_executor``.
* **Project-keyed Scripts**: ``get_script`` keys on ``(path, version,
  project_path)`` rather than ``id(project)`` so two distinct
  ``jedi.Project`` instances rooted at the same directory correctly share an
  entry.
* **Parso composition**: ``jedi.Script`` internally calls parso, which keeps
  its own in-memory parse cache keyed by file path (bounded by
  ``PYEYE_PARSO_CACHE_MAX_ENTRIES``, #713).  We cache the already-constructed
  ``jedi.Script`` object (whose setup overhead exceeds the parse step alone)
  and let parso's cache handle the underlying parse tree.
* **Script cap** (#713): each cached ``jedi.Script`` owns a Jedi inference
  state that keeps every module it inferred alive, parse trees included,
  whatever parso's cache holds.  So Scripts have their own LRU cap,
  ``PYEYE_SCRIPT_CACHE_MAX_ENTRIES``, inside the combined cap; it is what
  actually bounds the memory of Jedi's parse trees.
* **AST-biased LRU eviction**: when both the AST store and Script store are
  non-empty and the combined count cap is exceeded, the implementation evicts
  from the AST store first.  ``jedi.Script`` objects are more expensive to
  reconstruct than ASTs because Script setup involves inference-state
  initialisation, not just a parso parse.  Keeping Scripts warm and
  re-parsing ASTs via parso's own cache is a better trade-off under memory
  pressure.  See ``_enforce_ast_cap`` for details.
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
import weakref
from collections import OrderedDict
from pathlib import Path
from typing import Any

import jedi

from .path_utils import path_to_key

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

# A file's version: (mtime_ns, size) from one ``os.stat``. The size catches a
# rewrite inside the filesystem's mtime resolution (2 s on FAT/exFAT, #731).
_Version = tuple[int, int]

# Key for the AST store: (resolved_posix_path, version)
_FileKey = tuple[str, _Version]

# Key for Script store: (resolved_posix_path, version, project_posix_path)
_ScriptKey = tuple[str, _Version, str]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _stat_version(path: Path) -> _Version:
    """Return *path*'s ``(st_mtime_ns, st_size)`` from one ``os.stat`` (#731)."""
    st = os.stat(path)
    return st.st_mtime_ns, st.st_size


def _project_key(project: jedi.Project) -> str:
    """Return a stable string key for *project*'s import resolution.

    The root alone is not enough (#618): two Projects on one root with different
    ``added_sys_path`` resolve imports, and so name modules, differently, and must
    not share Scripts. The key therefore covers the root, the added sys.path in
    order, and whether Jedi's smart sys.path is on.
    """
    root = path_to_key(project.path)
    added = [Path(p).as_posix() for p in (getattr(project, "added_sys_path", None) or [])]
    smart = getattr(project, "_smart_sys_path", None)
    return "\n".join([root, "|".join(added), f"smart={smart}"])


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------


class FileArtifactCache:
    """Process-level cache for AST and ``jedi.Script`` objects.

    Instances are fully independent; tests construct them with custom caps.
    A module-level singleton ``_default_cache`` is provided for production use.

    The cache deliberately does **not** store source text.  Pyeye's role is
    semantic; raw source belongs to the agent's Read tool.  When a get_*
    method misses, source is read from disk for the parse / Script
    construction step and immediately discarded.

    Parameters
    ----------
    ast_max_entries:
        Maximum number of AST **and** Script entries combined.  When exceeded,
        the least-recently-used entry is evicted.
    script_max_entries:
        Maximum number of Script entries (#713), enforced within the combined
        cap.  When exceeded, the least-recently-used Script is evicted.
    """

    def __init__(
        self,
        ast_max_entries: int | None = None,
        script_max_entries: int | None = None,
    ) -> None:
        """Initialise the cache with the given entry caps.

        A cap left as ``None`` comes from settings: the combined cap from
        ``settings.artifact_cache_max_entries`` (env
        ``PYEYE_ARTIFACT_CACHE_MAX_ENTRIES``, #397), the Script cap from
        ``settings.script_cache_max_entries`` (env
        ``PYEYE_SCRIPT_CACHE_MAX_ENTRIES``, #713). An explicit argument always
        wins; tests and targeted tuning use it.
        """
        from .settings import settings

        if ast_max_entries is None:
            ast_max_entries = settings.artifact_cache_max_entries
        if script_max_entries is None:
            script_max_entries = settings.script_cache_max_entries
        self._ast_max_entries = ast_max_entries
        self._script_max_entries = script_max_entries

        # AST store: _FileKey -> ast.Module (LRU, shared count cap with Script)
        self._ast_store: OrderedDict[_FileKey, ast.Module] = OrderedDict()

        # Script store: _ScriptKey -> jedi.Script (LRU, shared count cap)
        self._script_store: OrderedDict[_ScriptKey, jedi.Script] = OrderedDict()
        #: Each cached Script's ``get_names(all_scopes=True, ...)``, read once
        #: (#1044). Weak keys: a Script evicted or invalidated takes its names
        #: with it, with no bookkeeping in the eviction paths.
        self._names_by_script: weakref.WeakKeyDictionary[jedi.Script, tuple[Any, ...]] = (
            weakref.WeakKeyDictionary()
        )

        # Stats counters
        self._hits: int = 0
        self._misses: int = 0
        # Evictions by cause (#401): the cap (raise the cap?) vs a file that
        # changed (healthy churn). ``stats()["evictions"]`` is their sum.
        self._cap_evictions: int = 0
        self._stale_evictions: int = 0

        # Single re-entrant lock guards all mutations
        self._lock = threading.RLock()

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def get_ast(self, path: Path | str) -> ast.Module:
        """Return the parsed AST for *path*, rebuilding on a cache miss or a version change.

        On a miss the source is read from disk, parsed, and the source is then
        discarded — only the resulting :class:`ast.Module` is retained.  This
        keeps pyeye in its semantic role and leaves source-text handling to
        the agent's Read tool.

        Parameters
        ----------
        path:
            Path to a Python source file.

        Returns
        -------
        ast.Module
            Parsed abstract syntax tree.
        """
        resolved = path_to_key(path)
        key: _FileKey = (resolved, _stat_version(Path(path)))

        with self._lock:
            if key in self._ast_store:
                self._ast_store.move_to_end(key)
                self._hits += 1
                return self._ast_store[key]

            # Evict any stale AST for this path
            self._evict_stale_ast(resolved, key)

            self._misses += 1
            # Read source inline for the parse step; do NOT cache the source.
            source = Path(path).read_text(encoding="utf-8")

            tree = ast.parse(source, filename=resolved)
            self._ast_store[key] = tree
            self._enforce_ast_cap()

            return tree

    def get_script(self, path: Path | str, project: jedi.Project) -> jedi.Script:
        """Return a ``jedi.Script`` for *path* under *project*, caching by project path.

        The cache key is ``(resolved_path, (mtime_ns, size), project_root_path)`` so
        two distinct ``jedi.Project`` instances rooted at the same directory
        share a cached entry, while projects at different roots do not.

        On a miss the source is read from disk, passed to the Script
        constructor, and then discarded — only the resulting ``jedi.Script``
        is retained.  parso's internal parse cache (mtime-keyed) covers the
        re-parse cost should the Script be evicted.

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
        resolved = path_to_key(path)
        version = _stat_version(Path(path))
        proj_key = _project_key(project)
        key: _ScriptKey = (resolved, version, proj_key)

        with self._lock:
            if key in self._script_store:
                self._script_store.move_to_end(key)
                self._hits += 1
                return self._script_store[key]

            # Evict any stale Scripts for this (path, project) combination
            self._evict_stale_script(resolved, proj_key, key)

            self._misses += 1
            # Read source inline for the Script constructor; do NOT cache it.
            source = Path(path).read_text(encoding="utf-8")

            # Jedi gets the resolved path, the form it compares with its
            # (resolved) project root and sys.path; a symlinked spelling makes
            # it name the module ``__main__`` (#714).
            script = jedi.Script(code=source, path=Path(resolved), project=project)
            self._script_store[key] = script
            self._enforce_ast_cap()

            return script

    def get_all_scope_names(self, path: Path | str, project: jedi.Project) -> tuple[Any, ...]:
        """Every definition name in *path*, in all scopes, read once per cached Script (#1044).

        ``Script.get_names(all_scopes=True, definitions=True, references=False)``,
        as a tuple: it is shared by every caller of this Script, so it can't be
        mutated. Jedi rebuilds the values of nested scopes on each such call
        and memoises them on contexts that are never seen again (a class
        defined in a method, with an assignment in its body, adds one entry per
        call), so calling it per request grew a long-lived Script's inference
        state without bound: past 3 GB over django's tests. Reading it once per
        Script stops that, and makes later ``goto``/``infer`` on the same names
        hits. A new file version gets a new Script, and so new names.

        Like every Jedi call, it runs on the Jedi worker thread.
        """
        return self.all_scope_names(self.get_script(path, project))

    def all_scope_names(self, script: jedi.Script) -> tuple[Any, ...]:
        """:meth:`get_all_scope_names` for a Script already in hand, read once per Script."""
        with self._lock:
            names = self._names_by_script.get(script)
        if names is None:
            names = tuple(script.get_names(all_scopes=True, definitions=True, references=False))
            with self._lock:
                names = self._names_by_script.setdefault(script, names)
        return names

    def invalidate(self, path: Path | str) -> None:
        """Evict all cached entries for *path*.

        Safe to call on a path that has no cached entries.

        Parameters
        ----------
        path:
            Path whose entries should be dropped from the cache.
        """
        resolved = path_to_key(path)
        with self._lock:
            self._evict_all_for_resolved(resolved)

    def invalidate_all(self) -> None:
        """Clear the entire cache.

        ``stats()["evictions"]`` is incremented by the total number of items
        cleared, matching the per-item semantics of :meth:`invalidate`. A clear
        is an invalidation, not cap pressure, so they count as stale (#401).
        """
        with self._lock:
            cleared = len(self._ast_store) + len(self._script_store)
            self._stale_evictions += cleared
            self._ast_store.clear()
            self._script_store.clear()

    def stats(self) -> dict[str, Any]:
        """Return a snapshot of cache statistics.

        Returns
        -------
        dict
            Keys: ``hits``, ``misses``, ``evictions``, ``cap_evictions`` and
            ``stale_evictions``. ``cap_evictions`` are entries dropped to keep
            under the caps (``PYEYE_ARTIFACT_CACHE_MAX_ENTRIES``,
            ``PYEYE_SCRIPT_CACHE_MAX_ENTRIES``): cap pressure. ``stale_evictions``
            are entries dropped because their file changed, or by an
            invalidation. ``evictions`` is their sum (#401).
        """
        with self._lock:
            return {
                "hits": self._hits,
                "misses": self._misses,
                "evictions": self._cap_evictions + self._stale_evictions,
                "cap_evictions": self._cap_evictions,
                "stale_evictions": self._stale_evictions,
            }

    # -----------------------------------------------------------------------
    # Internal helpers — must be called with _lock held
    # -----------------------------------------------------------------------

    def _evict_stale_ast(self, resolved: str, current_key: _FileKey) -> None:
        """Remove AST entries for *resolved* whose version differs from *current_key*."""
        stale = [k for k in self._ast_store if k[0] == resolved and k != current_key]
        for k in stale:
            del self._ast_store[k]
            self._stale_evictions += 1

    def _evict_stale_script(self, resolved: str, proj_key: str, current_key: _ScriptKey) -> None:
        """Remove Script entries for *(resolved, proj_key)* that are stale."""
        stale = [
            k
            for k in self._script_store
            if k[0] == resolved and k[2] == proj_key and k != current_key
        ]
        for k in stale:
            del self._script_store[k]
            self._stale_evictions += 1

    def _evict_all_for_resolved(self, resolved: str) -> None:
        """Remove all cached entries (AST, Script) for *resolved*."""
        ast_stale = [k for k in self._ast_store if k[0] == resolved]
        for k in ast_stale:
            del self._ast_store[k]
            self._stale_evictions += 1

        script_stale: list[_ScriptKey] = [k for k in self._script_store if k[0] == resolved]
        for sk in script_stale:
            del self._script_store[sk]
            self._stale_evictions += 1

    def _enforce_ast_cap(self) -> None:
        """Enforce both caps: Scripts <= _script_max_entries, then combined <= _ast_max_entries.

        The Script cap (#713) evicts least-recently-used Scripts first.  Then,
        while the combined count exceeds its cap, ASTs are evicted before Scripts
        (see below).
        """
        while len(self._script_store) > self._script_max_entries:
            self._script_store.popitem(last=False)
            self._cap_evictions += 1
        while (len(self._ast_store) + len(self._script_store)) > self._ast_max_entries:
            # Determine which store has the globally oldest entry.
            # OrderedDict preserves insertion/access order; first element is LRU.
            ast_lru = next(iter(self._ast_store), None)
            script_lru = next(iter(self._script_store), None)

            if ast_lru is not None and script_lru is None:
                del self._ast_store[ast_lru]
                self._cap_evictions += 1
            elif script_lru is not None and ast_lru is None:
                del self._script_store[script_lru]
                self._cap_evictions += 1
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
                self._cap_evictions += 1


# ---------------------------------------------------------------------------
# Module-level singleton for production use
# ---------------------------------------------------------------------------

# Default process-global cache instance.
# Most callers should use the module-level functions below which delegate to
# this singleton.  Tests should construct their own ``FileArtifactCache``
# instances with custom caps.
_default_cache: FileArtifactCache = FileArtifactCache()


def get_ast(path: Path | str) -> ast.Module:
    """Return cached AST for *path* using the default cache."""
    return _default_cache.get_ast(path)


def get_script(path: Path | str, project: jedi.Project) -> jedi.Script:
    """Return cached jedi.Script for *path* under *project* using the default cache."""
    return _default_cache.get_script(path, project)


def get_all_scope_names(path: Path | str, project: jedi.Project) -> tuple[Any, ...]:
    """Every definition name in *path*, all scopes, read once per cached Script (#1044).

    Through the module's :func:`get_script`, the one seam for loading a file's
    Script, so a failure there propagates here too (#704).
    """
    return _default_cache.all_scope_names(get_script(path, project))


def invalidate(path: Path | str) -> None:
    """Invalidate cached entries for *path* in the default cache."""
    _default_cache.invalidate(path)


def invalidate_all() -> None:
    """Invalidate all entries in the default cache."""
    _default_cache.invalidate_all()


def stats() -> dict[str, Any]:
    """Return stats from the default cache."""
    return _default_cache.stats()

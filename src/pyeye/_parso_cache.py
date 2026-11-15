"""pyeye's policy for parso's in-memory parse cache (#684, #713).

parso keeps every parsed module in ``parso.cache.parser_cache``, and Jedi reads
entries back for modules it already holds:

- ``jedi.inference.filters`` (``_AbstractUsedNamesFilter``) looks up the
  module's entry with ``get_parso_cache_node`` and uses it **only** as the key
  of a weak memo of definition names. ``_get_definition_names`` already
  computes the same names without the memo when that key is ``None``.
- ``get_cached_code_lines`` returns the entry's source lines. Five Jedi modules
  import it by name.

When an entry was evicted, both raised ``KeyError``, and pyeye reported
``unresolved`` (#684: stdlib and typeshed modules vanished from a cache over 600
entries, because parso's GC ages entries by file mtime). #706 switched the GC
off, which left the cache unbounded at about 0.35 MB per resident file (#713).

This module makes eviction harmless, then bounds the cache:

1. **Recovery** (:func:`_install_recovery`). The filter gets ``None`` for a
   missing entry, so it computes the definition names directly from the
   module's own tree, with an identical answer and no memo. A missing entry's
   code lines are re-read and split exactly as parso does. Nothing is
   re-parsed, so Jedi never sees nodes other than its own.
2. **Bound** (:func:`_install_lru`). Inserts go through an LRU that stamps
   ``last_used`` with the parse time, not the file mtime, and evicts the
   least-recently-used entries over ``PYEYE_PARSO_CACHE_MAX_ENTRIES``. parso
   already refreshes ``last_used`` on every cache hit.

Both pin Jedi and parso internals. ``tests/unit/test_parso_cache_gc.py`` asserts
each one still exists and is still wrapped, so an upgrade that moves one fails
CI instead of quietly bringing #684 back.
"""

from __future__ import annotations

import importlib.abc
import importlib.util
import sys
import time
from collections.abc import Callable, Sequence
from importlib.machinery import ModuleSpec
from types import ModuleType
from typing import Any

import parso.cache

#: Jedi modules that bind ``get_cached_code_lines`` by name.
_CODE_LINES_MODULES = (
    "jedi.parser_utils",
    "jedi.inference.imports",
    "jedi.inference.gradual.typeshed",
    "jedi.inference.compiled.mixed",
    "jedi.inference.sys_path",
)
#: The one Jedi module that binds ``get_parso_cache_node`` for the filter memo.
_FILTER_MODULE = "jedi.inference.filters"
#: When over the cap, evict down to this fraction of it, so eviction (a sort of
#: the whole cache) runs once per tenth of the cap rather than on every insert.
_EVICT_TO = 0.9
#: Marks pyeye's wrappers, so installing twice never wraps a wrapper.
_MARK = "_pyeye_713"


def apply_parso_cache_policy(max_entries: int) -> None:
    """Install the LRU bound of *max_entries* entries, and recovery. Idempotent.

    Called once from ``pyeye/__init__.py``, before any pyeye module uses Jedi.
    Everything it patches is module-global, so the Jedi worker thread (#650)
    is covered. Calling it again only changes the cap.

    Importing pyeye must not import Jedi: the #623 layering keeps modules such
    as ``pyeye.project_layout`` Jedi-free at import time. So recovery is
    installed now only if Jedi is already imported. Otherwise a one-shot import
    hook installs it the moment ``import jedi`` finishes, before anything can
    use Jedi. ``import jedi`` loads every module recovery patches.
    """
    # parso's own mtime-aged GC must never run: the LRU replaces it.
    parso.cache._CACHED_SIZE_TRIGGER = sys.maxsize
    _install_lru(max_entries)
    if "jedi" in sys.modules:
        _install_recovery()
    elif not any(isinstance(finder, _RecoverAfterJediImport) for finder in sys.meta_path):
        sys.meta_path.insert(0, _RecoverAfterJediImport())


class _RecoverAfterJediImport(importlib.abc.MetaPathFinder):
    """Install recovery right after the top-level ``jedi`` package executes. One-shot.

    *package* is the watched top-level package; only tests pass anything but
    ``"jedi"``.
    """

    def __init__(self, package: str = "jedi") -> None:
        self._package = package

    def find_spec(
        self,
        fullname: str,
        path: Sequence[str] | None,  # noqa: ARG002 (MetaPathFinder signature)
        target: ModuleType | None = None,  # noqa: ARG002
    ) -> ModuleSpec | None:
        if fullname != self._package:
            return None
        sys.meta_path.remove(self)  # one-shot, and lets the real finders run below
        spec = importlib.util.find_spec(fullname)
        if spec is None or spec.loader is None:
            return spec
        loader = spec.loader
        exec_module = loader.exec_module

        def exec_then_recover(module: ModuleType) -> None:
            exec_module(module)
            _install_recovery()

        loader.exec_module = exec_then_recover  # type: ignore[method-assign]
        return spec


def _install_recovery() -> None:
    import importlib

    import jedi.parser_utils

    original_node = getattr(
        jedi.parser_utils.get_parso_cache_node,
        "__wrapped__",
        jedi.parser_utils.get_parso_cache_node,
    )

    def node_or_none(grammar: Any, path: Any) -> Any:
        """The module's parso cache entry, or ``None`` if it was evicted (#713)."""
        try:
            return original_node(grammar, path)
        except KeyError:
            return None  # the filter then computes without its memo

    def code_lines(grammar: Any, path: Any) -> list[str]:
        """The module's source lines, from the cache or re-read from disk (#713)."""
        try:
            lines: list[str] = original_node(grammar, path).lines
            return lines
        except KeyError:
            return _read_lines(path)

    _mark(node_or_none, original_node)
    _mark(code_lines, original_node)
    filters = importlib.import_module(_FILTER_MODULE)
    if not _is_marked(filters.get_parso_cache_node):
        setattr(filters, "get_parso_cache_node", node_or_none)  # noqa: B010
    for name in _CODE_LINES_MODULES:
        module: ModuleType = importlib.import_module(name)
        if not _is_marked(module.get_cached_code_lines):
            setattr(module, "get_cached_code_lines", code_lines)  # noqa: B010


def _read_lines(path: Any) -> list[str]:
    """Split *path*'s source into lines exactly as parso does when it parses."""
    from parso.utils import python_bytes_to_unicode, split_lines

    with open(path, "rb") as f:
        return split_lines(python_bytes_to_unicode(f.read()), keepends=True)


_max_entries = 600


def _install_lru(max_entries: int) -> None:
    global _max_entries
    _max_entries = max(1, max_entries)
    if not _is_marked(parso.cache._set_cache_item):
        _mark(_set_cache_item_lru, parso.cache._set_cache_item)
        parso.cache._set_cache_item = _set_cache_item_lru


def _set_cache_item_lru(hashed_grammar: str, path: Any, module_cache_item: Any) -> None:
    """Replace parso's ``_set_cache_item`` with an LRU by last use instead of its mtime GC."""
    # parso stamps last_used with the FILE's mtime; the LRU needs the parse time.
    module_cache_item.last_used = time.time()
    cache: dict[str, dict[Any, Any]] = parso.cache.parser_cache
    total = sum(len(items) for items in cache.values())
    if total >= _max_entries:
        keep = int(_max_entries * _EVICT_TO)
        by_age = sorted(
            (
                (item.last_used, grammar, key)
                for grammar, items in cache.items()
                for key, item in items.items()
            ),
            key=lambda entry: entry[0],
        )
        for _, grammar, key in by_age[: max(1, total - keep)]:
            cache[grammar].pop(key, None)
    cache.setdefault(hashed_grammar, {})[path] = module_cache_item


def _mark(wrapper: Callable[..., Any], wrapped: Callable[..., Any]) -> None:
    setattr(wrapper, _MARK, True)
    wrapper.__wrapped__ = wrapped  # type: ignore[attr-defined]


def _is_marked(func: Any) -> bool:
    return bool(getattr(func, _MARK, False))

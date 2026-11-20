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

3. **Network paths** (:func:`_install_sys_path_filter`, #1048). Jedi adds the
   ``sys.path`` changes it reads in a project's own files (``sys.path.insert``,
   and a ``buildout.cfg`` project's ``bin/`` scripts) to its import search,
   and on Windows searching a UNC path connects to its host over SMB. The
   paths ``jedi.inference.sys_path.check_sys_path_modifications`` returns are
   filtered through :func:`pyeye.path_utils.repo_path_refusal`.

All three pin Jedi and parso internals. ``tests/unit/test_parso_cache_gc.py`` asserts
each one still exists and is still wrapped, so an upgrade that moves one fails
CI instead of quietly bringing #684 back.
"""

from __future__ import annotations

import importlib.abc
import importlib.util
import logging
import sys
import time
from collections.abc import Callable, Sequence
from importlib.machinery import ModuleSpec
from types import ModuleType
from typing import Any

import parso.cache

logger = logging.getLogger(__name__)

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

    # First and on its own (#1056): a later step failing after a Jedi upgrade
    # must not skip the network-path filter, nor it the recovery shims.
    _install_sys_path_filter_isolated()

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
    _install_own_tree_guard(filters._AbstractUsedNamesFilter)
    for name in _CODE_LINES_MODULES:
        module: ModuleType = importlib.import_module(name)
        if not _is_marked(module.get_cached_code_lines):
            setattr(module, "get_cached_code_lines", code_lines)  # noqa: B010


def _install_own_tree_guard(filter_class: Any) -> None:
    """A filter uses parso's cache node only when it is the filter's own tree (#783).

    The filter takes the node **by path** and keys its definition-name memo
    and ``get_cached_parent_scope`` on it, but reads ``_used_names`` from its
    module's own tree. After the LRU evicts a file and another Script re-parses
    it, the path names a different tree. A Script still holding the old one
    would then read the other parse's names and reject them all, so ``goto``
    answered ``[]``. A foreign node is treated like an evicted one: the filter
    computes without its memo, with an identical answer.

    Every ``_AbstractUsedNamesFilter`` subclass reaches this through
    ``super().__init__``; ``tests/unit/test_parso_cache_node_identity.py`` pins
    that, the signature, and that no other Jedi module takes the node by path.
    """
    original_init = filter_class.__init__
    if _is_marked(original_init):
        return

    def init_own_tree(self: Any, parent_context: Any, node_context: Any = None) -> None:
        original_init(self, parent_context, node_context)
        item = self._parso_cache_node
        # A missing entry is already None (node_or_none); this catches a
        # PRESENT entry that belongs to another parse of the same path.
        if item is not None and item.node is not self._node_context.get_root_context().tree_node:
            self._parso_cache_node = None

    _mark(init_own_tree, original_init)
    filter_class.__init__ = init_own_tree


def _install_sys_path_filter_isolated() -> None:
    """:func:`_install_sys_path_filter`, whose failure warns instead of stopping the other patches."""
    try:
        _install_sys_path_filter()
    except Exception as error:
        logger.warning(
            f"Could not install the sys.path network filter ({error}): network paths in a "
            "project's own sys.path changes are NOT filtered (#1048)"
        )


def _install_sys_path_filter() -> None:
    """Drop network paths from the ``sys.path`` changes Jedi reads in project code (#1048).

    One patch point covers both of Jedi's sources: ``imports.Importer`` calls
    ``sys_path.check_sys_path_modifications`` through the module attribute on
    every import, and ``discover_buildout_paths`` calls it as that module's
    global. Verified against Jedi 0.20.1. Local paths pass unchanged: a repo
    putting its own directories on the path is Jedi's normal behaviour.

    If an upgrade removes the function, there is no other stable point to
    filter at, so this warns and installs nothing; the behaviour tests in
    ``tests/test_network_paths.py`` then fail. It does not fail closed.
    """
    import jedi.inference.sys_path as jedi_sys_path

    original = getattr(jedi_sys_path, "check_sys_path_modifications", None)
    if original is None:
        logger.warning(
            "jedi.inference.sys_path.check_sys_path_modifications is gone: network "
            "paths in a project's own sys.path changes are NOT filtered (#1048)"
        )
        return
    if _is_marked(original):
        return

    def local_only(module_context: Any) -> list[Any]:
        """Jedi's sys.path changes for *module_context*, minus network paths (#1048)."""
        from .path_utils import repo_path_refusal

        kept = []
        for path in original(module_context):
            if (why := repo_path_refusal(str(path))) is None:
                kept.append(path)
            else:
                logger.warning(
                    f"Not searching sys.path entry {str(path)!r} from project code: {why}"
                )
        return kept

    _mark(local_only, original)
    jedi_sys_path.check_sys_path_modifications = local_only


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
